"""Kakao OAuth authorization-code flow and signed HttpOnly service session."""
from __future__ import annotations

import logging
import secrets
from datetime import timedelta
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Cookie, Depends, HTTPException, Request, Response, status
from fastapi.responses import RedirectResponse
from itsdangerous import BadSignature, URLSafeTimedSerializer
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import (
    User,
    UserPreference,
    UserWithdrawal,
    database_session,
    optional_database_session,
    utc_now_naive,
)
from ..settings import settings

router = APIRouter(prefix="/api/auth", tags=["auth"])
log = logging.getLogger("api.auth")
_STATE_COOKIE = "kakao_oauth_state"
_SESSION_COOKIE = "mobility_session"
_KAKAO_UNLINK_URL = "https://kapi.kakao.com/v1/user/unlink"


def _secure_cookie() -> bool:
    # 운영에서는 설정 실수로 redirect URI가 잘못돼도 세션 쿠키를 평문
    # 전송 가능 상태로 낮추지 않는다.
    return (
        settings.app_env == "production"
        or settings.kakao_oauth_redirect_uri.startswith("https://")
    )


def _configured() -> None:
    if not settings.kakao_login_configured:
        raise HTTPException(status_code=503, detail="Kakao login or PostgreSQL is not configured.")


def _serializer() -> URLSafeTimedSerializer:
    _configured()
    return URLSafeTimedSerializer(settings.session_secret, salt="mobility-session-v1")


def _provider_identity(profile: object) -> tuple[str, str | None]:
    if not isinstance(profile, dict):
        raise ValueError("Kakao user profile is not an object.")
    raw_id = profile.get("id")
    if (
        isinstance(raw_id, bool)
        or not isinstance(raw_id, (int, str))
        or not str(raw_id).isdigit()
        or int(raw_id) <= 0
        or len(str(raw_id)) > 64
    ):
        raise ValueError("Kakao user profile ID is invalid.")
    properties = profile.get("properties")
    if properties is None:
        nickname = None
    elif not isinstance(properties, dict):
        raise ValueError("Kakao user profile properties are invalid.")
    else:
        raw_nickname = properties.get("nickname")
        if raw_nickname is None:
            nickname = None
        elif (
            not isinstance(raw_nickname, str)
            or not raw_nickname.strip()
            or len(raw_nickname) > 100
        ):
            raise ValueError("Kakao user profile nickname is invalid.")
        else:
            nickname = raw_nickname
    return str(raw_id), nickname


def current_user(
    session_cookie: str | None = Cookie(default=None, alias=_SESSION_COOKIE),
    db: Session = Depends(database_session),
) -> User:
    if not session_cookie:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Login required.")
    try:
        user_id = _serializer().loads(session_cookie, max_age=60 * 60 * 24 * 14)
    except BadSignature as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid session.") from exc
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unknown session user.")
    if _withdrawal_pending(db, user.id):
        # 탈퇴 신청 계정은 파기 전이라 행이 남아 있을 뿐 접근 권한은 없다.
        # 다른 기기에 남은 세션 쿠키로도 들어올 수 없어야 한다.
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Withdrawn account.",
        )
    return user


def optional_current_user(
    session_cookie: str | None = Cookie(default=None, alias=_SESSION_COOKIE),
    db: Session | None = Depends(optional_database_session),
) -> User | None:
    """게스트는 None, 유효한 Kakao 로그인 사용자는 User를 반환한다."""
    if not session_cookie or db is None:
        return None
    try:
        user_id = _serializer().loads(session_cookie, max_age=60 * 60 * 24 * 14)
    except BadSignature:
        return None
    user = db.get(User, user_id)
    if user is None or _withdrawal_pending(db, user.id):
        return None
    return user


def _withdrawal_pending(db: Session, user_id: str) -> bool:
    return db.get(UserWithdrawal, user_id) is not None


@router.get("/kakao/login")
def kakao_login() -> Response:
    _configured()
    state = secrets.token_urlsafe(32)
    query = urlencode({
        "client_id": settings.kakao_rest_api_key,
        "redirect_uri": settings.kakao_oauth_redirect_uri,
        "response_type": "code",
        "state": state,
    })
    response = RedirectResponse(f"https://kauth.kakao.com/oauth/authorize?{query}")
    response.set_cookie(
        _STATE_COOKIE, state, httponly=True, secure=_secure_cookie(),
        samesite="lax", max_age=600,
    )
    return response


@router.get("/kakao/callback")
async def kakao_callback(
    request: Request,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    db: Session = Depends(database_session),
) -> Response:
    _configured()
    cookie_state = request.cookies.get(_STATE_COOKIE)
    state_valid = bool(
        state
        and cookie_state
        and secrets.compare_digest(state, cookie_state)
    )
    if error or not code or not state_valid:
        raise HTTPException(status_code=400, detail="Kakao authorization was rejected or state validation failed.")
    try:
        async with httpx.AsyncClient(timeout=settings.request_timeout) as client:
            token_response = await client.post("https://kauth.kakao.com/oauth/token", data={
                "grant_type": "authorization_code",
                "client_id": settings.kakao_rest_api_key,
                "client_secret": settings.kakao_oauth_client_secret,
                "redirect_uri": settings.kakao_oauth_redirect_uri,
                "code": code,
            })
            token_response.raise_for_status()
            access_token = token_response.json()["access_token"]
            user_response = await client.get(
                "https://kapi.kakao.com/v2/user/me",
                headers={"Authorization": f"Bearer {access_token}"},
            )
            user_response.raise_for_status()
        profile = user_response.json()
        kakao_id, nickname = _provider_identity(profile)
    except (httpx.HTTPError, KeyError, TypeError, ValueError) as exc:
        log.warning("Kakao OAuth provider response failed (%s)", type(exc).__name__)
        raise HTTPException(status_code=502, detail="Kakao login provider request failed.") from exc
    user = db.scalar(select(User).where(User.kakao_id == kakao_id))
    if user is None:
        user = User(kakao_id=kakao_id, nickname=nickname)
        db.add(user)
        db.flush()
        db.add(UserPreference(user_id=user.id))
    else:
        # 보관기간 안에 다시 로그인하면 탈퇴를 철회한다. 유예기간을 둔 이유가
        # 실수로 신청한 사용자를 되살리는 것이기 때문이다. 연결 끊기 후
        # 회원번호가 바뀌는 경우에는 위의 신규 가입 분기로 흘러 충돌하지 않는다.
        withdrawal = db.get(UserWithdrawal, user.id)
        if withdrawal is not None:
            db.delete(withdrawal)
            log.info("탈퇴 신청이 재로그인으로 철회되었습니다.")
        user.nickname = nickname
    db.commit()
    service_session = _serializer().dumps(user.id)
    response = RedirectResponse(f"{settings.frontend_url.rstrip('/')}/")
    response.delete_cookie(_STATE_COOKIE, secure=_secure_cookie(), samesite="lax")
    response.set_cookie(
        _SESSION_COOKIE, service_session, httponly=True, secure=_secure_cookie(),
        samesite="lax", max_age=60 * 60 * 24 * 14,
    )
    return response


@router.post("/logout", status_code=204)
def logout() -> Response:
    response = Response(status_code=204)
    response.delete_cookie(_SESSION_COOKIE, secure=_secure_cookie(), samesite="lax")
    return response


async def unlink_kakao_account(kakao_id: str) -> bool:
    """앱 어드민 키로 카카오 연결을 끊는다. 성공 여부만 돌려준다.

    로그인 시 액세스 토큰을 저장하지 않으므로 사용자 토큰으로는 연결을 끊을 수
    없고, 어드민 키가 유일한 경로다. 키가 없거나 공급자가 실패해도 예외를
    올리지 않는다. 외부 장애 때문에 사용자가 탈퇴하지 못하는 상황을 만들지
    않고, 실패는 대기열에 남겨 파기 배치가 재시도한다.
    """
    admin_key = settings.kakao_admin_key.strip()
    if not admin_key:
        return False
    try:
        async with httpx.AsyncClient(timeout=settings.request_timeout) as client:
            response = await client.post(
                _KAKAO_UNLINK_URL,
                headers={
                    "Authorization": f"KakaoAK {admin_key}",
                    "Content-Type":
                        "application/x-www-form-urlencoded;charset=utf-8",
                },
                data={"target_id_type": "user_id", "target_id": kakao_id},
            )
            response.raise_for_status()
    except httpx.HTTPError as exc:
        # 회원번호와 응답 본문은 남기지 않는다. 재시도 판단에는 실패 사실이면
        # 충분하고, 로그는 개인 식별자를 담지 않는다.
        log.warning("Kakao unlink failed (%s)", type(exc).__name__)
        return False
    return True


@router.post("/withdraw", status_code=204)
async def withdraw(
    user: User = Depends(current_user),
    db: Session = Depends(database_session),
) -> Response:
    """회원 탈퇴를 신청한다.

    즉시 로그인을 막고 표시용 개인정보를 지우되, 사용자 행은 보관기간 동안
    남긴다. 기한이 지나면 ``scripts/purge_withdrawn_users.py``가 삭제하고
    그때 외래키 정책이 나머지를 정리한다.
    """
    if user.is_admin:
        # reviewed_by가 SET NULL이라 관리자를 지우면 후기 검수 이력의 담당자가
        # 통째로 비어 감사 추적이 끊긴다. 권한 회수 후 탈퇴해야 한다.
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Administrator accounts cannot be withdrawn. "
                   "Revoke the administrator role first.",
        )

    response = Response(status_code=204)
    response.delete_cookie(_SESSION_COOKIE, secure=_secure_cookie(), samesite="lax")
    if _withdrawal_pending(db, user.id):
        # 이미 신청한 계정의 재요청은 기한을 늘리거나 줄이지 않는다.
        return response

    unlinked = await unlink_kakao_account(user.kakao_id)
    db.add(UserWithdrawal(
        user_id=user.id,
        purge_after=utc_now_naive()
        + timedelta(days=settings.withdrawal_retention_days),
        provider_unlinked=unlinked,
    ))
    # 닉네임은 파기를 기다릴 이유가 없는 표시용 개인정보라 즉시 지운다.
    user.nickname = None
    db.commit()
    return response


@router.get("/me", response_model=None)
def me(user: User | None = Depends(optional_current_user)) -> dict | Response:
    # 로그인 여부 확인은 정상적인 게스트 흐름이다. 401을 반환하면 브라우저가
    # 처리된 응답도 콘솔 오류로 기록하므로, 게스트는 본문 없는 204로 구분한다.
    if user is None:
        return Response(status_code=204)
    pref = user.preference
    return {
        "id": user.id,
        "nickname": user.nickname,
        "isAdmin": user.is_admin,
        "preference": _preference_dict(pref),
    }


def _preference_dict(pref: UserPreference | None) -> dict:
    if pref is None:
        return {}
    return {
        "profile": pref.profile,
        "usesWheelchair": pref.uses_wheelchair,
        "usesWalkingAid": pref.uses_walking_aid,
        "visualSupportRequired": pref.visual_support_required,
        "hearingSupportRequired": pref.hearing_support_required,
        "avoidStairsRequired": pref.avoid_stairs_required,
        "maxWalkDistanceM": pref.max_walk_distance_m,
        "trainingConsent": pref.training_consent,
    }
