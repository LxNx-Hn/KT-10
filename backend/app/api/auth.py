"""Kakao OAuth authorization-code flow and signed HttpOnly service session."""
from __future__ import annotations

import logging
import secrets
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Cookie, Depends, HTTPException, Request, Response, status
from fastapi.responses import RedirectResponse
from itsdangerous import BadSignature, URLSafeTimedSerializer
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import User, UserPreference, database_session, optional_database_session
from ..settings import settings

router = APIRouter(prefix="/api/auth", tags=["auth"])
log = logging.getLogger("api.auth")
_STATE_COOKIE = "kakao_oauth_state"
_SESSION_COOKIE = "mobility_session"


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


@router.get("/me", response_model=None)
def me(user: User | None = Depends(optional_current_user)) -> dict | Response:
    # 로그인 여부 확인은 정상적인 게스트 흐름이다. 401을 반환하면 브라우저가
    # 처리된 응답도 콘솔 오류로 기록하므로, 게스트는 본문 없는 204로 구분한다.
    if user is None:
        return Response(status_code=204)
    pref = user.preference
    return {"id": user.id, "nickname": user.nickname, "preference": _preference_dict(pref)}


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
