"""Kakao OAuth authorization-code flow and signed HttpOnly service session."""
from __future__ import annotations

import logging
import secrets
from datetime import timedelta
from hashlib import sha256
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Cookie, Depends, HTTPException, Request, Response, status
from fastapi.responses import RedirectResponse
from itsdangerous import BadSignature, URLSafeTimedSerializer
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from ..database import (
    FacilityReport,
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
        # 탈퇴한 계정은 사용자 행이 이미 삭제됐으므로 여기서 걸러진다.
        # 다른 기기에 남은 세션 쿠키로도 들어올 수 없다.
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unknown session user.")
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
    return db.get(User, user_id)


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


def withdrawal_subject_hash(kakao_id: str) -> str | None:
    """반복 탈퇴 판별용 해시. salt가 없으면 보관하지 않는다.

    회원번호는 숫자라 salt 없이 해시하면 무차별 대입으로 역산된다. 안전하지
    않은 값을 안전한 척 남기지 않고, 그 경우 부정 이용 방지 기능만 비활성한다.
    """
    if not settings.withdrawal_hashing_configured:
        return None
    salt = settings.withdrawal_hash_salt.strip()
    return sha256(f"{salt}:{kakao_id}".encode("utf-8")).hexdigest()


async def unlink_kakao_account(kakao_id: str) -> bool:
    """앱 어드민 키로 카카오 연결을 끊는다. 성공 여부만 돌려준다.

    로그인 시 액세스 토큰을 저장하지 않으므로 사용자 토큰으로는 연결을 끊을 수
    없고, 어드민 키가 유일한 경로다. 키가 없거나 공급자가 실패해도 예외를
    올리지 않는다. 외부 장애 때문에 사용자가 탈퇴하지 못하는 상황을 만들지
    않고, 실패는 탈퇴 기록에 남겨 파기 배치가 재시도한다.
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
    """회원 탈퇴를 처리한다. 되돌릴 수 없다.

    계정·프로필·서비스 데이터는 이 요청에서 즉시 삭제한다. 사용자 행을 지우면
    설정·후기·추천 표시 기록이 외래키 정책으로 함께 사라진다.

    시설 신고만 남긴다. 시설 식별과 유지보수에 쓰이는 공익적 기록이기
    때문이다. 대신 작성자 연결을 끊고 자유입력 설명을 비워, 시설 자체를
    식별·관리하는 데 필요한 정보(시설명·유형·위치·오류 유형·처리 상태)만
    남긴다.

    그 밖에 남는 것은 부정 가입·탈퇴 반복 방지와 처리 오류 대응에 필요한 최소
    정보뿐이며 ``scripts/purge_withdrawn_users.py``가 보관기간 후 지운다.
    """
    if user.is_admin:
        # reviewed_by가 SET NULL이라 관리자를 지우면 후기 검수 이력의 담당자가
        # 통째로 비어 감사 추적이 끊긴다. 권한 회수 후 탈퇴해야 한다.
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Administrator accounts cannot be withdrawn. "
                   "Revoke the administrator role first.",
        )

    kakao_id = user.kakao_id
    unlinked = await unlink_kakao_account(kakao_id)
    db.add(UserWithdrawal(
        user_ref=user.id,
        subject_hash=withdrawal_subject_hash(kakao_id),
        purge_after=utc_now_naive()
        + timedelta(days=settings.withdrawal_retention_days),
        status="completed" if unlinked else "provider_unlink_pending",
        # 연결 끊기에 성공했으면 회원번호를 남기지 않는다. 실패한 건에 한해
        # 재시도를 위해 예외적으로 보관하고, 재시도가 성공하면 즉시 지운다.
        pending_provider_id=None if unlinked else kakao_id,
    ))
    # 시설 신고는 시설 식별·유지보수 가치가 있어 보존하되, 탈퇴자의 개인정보는
    # 지운다. 외래키로 처리할 수 없는 필드라 명시적으로 갱신한다.
    #   description   자유입력이라 무엇이 적혔는지 통제할 수 없다
    #   reported_lat/lng  시설 좌표가 아니라 신고 시점 사용자의 GPS 위치다
    # 시설명·유형·오류 유형·처리 상태·관리자 메모는 남긴다.
    db.execute(
        update(FacilityReport)
        .where(FacilityReport.user_id == user.id)
        .values(description=None, reported_lat=None, reported_lng=None)
    )
    # 사용자 행 삭제 하나로 나머지 외래키 정책이 적용된다.
    db.delete(user)
    db.commit()

    response = Response(status_code=204)
    response.delete_cookie(_SESSION_COOKIE, secure=_secure_cookie(), samesite="lax")
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
