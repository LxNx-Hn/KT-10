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
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..agreements import (
    consume_current_terms_agreement,
    has_current_terms_agreement,
)
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
_SIGNUP_COOKIE = "dongnet_signup_state"
_SIGNUP_COOKIE_PATH = "/api/auth/signup"
_SIGNUP_MAX_AGE = 600
_SIGNUP_SALT = "dongnet-signup-pending-v1"
_DELETION_COOKIE = "dongnet_deletion_state"
_DELETION_COOKIE_PATH = "/api/auth/deletion"
_DELETION_MAX_AGE = 600
_DELETION_OAUTH_SALT = "dongnet-deletion-oauth-v1"
_DELETION_CREDENTIAL_SALT = "dongnet-deletion-credential-v1"
_DELETION_STATE_PREFIX = "delete."
_KAKAO_UNLINK_URL = "https://kapi.kakao.com/v1/user/unlink"


class SignupCompleteInput(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    accept_terms: bool = False


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


def _signup_serializer() -> URLSafeTimedSerializer:
    _configured()
    return URLSafeTimedSerializer(settings.session_secret, salt=_SIGNUP_SALT)


def _deletion_oauth_serializer() -> URLSafeTimedSerializer:
    _configured()
    return URLSafeTimedSerializer(settings.session_secret, salt=_DELETION_OAUTH_SALT)


def _deletion_credential_serializer() -> URLSafeTimedSerializer:
    _configured()
    return URLSafeTimedSerializer(
        settings.session_secret,
        salt=_DELETION_CREDENTIAL_SALT,
    )


def _frontend_path(path: str) -> str:
    return f"{settings.frontend_url.rstrip('/')}{path}"


def _clear_cookie(response: Response, name: str) -> None:
    response.delete_cookie(name, secure=_secure_cookie(), samesite="lax")


def _clear_signup_cookie(response: Response) -> None:
    response.delete_cookie(
        _SIGNUP_COOKIE,
        path=_SIGNUP_COOKIE_PATH,
        secure=_secure_cookie(),
        samesite="lax",
    )


def _set_session_cookie(response: Response, user_id: str) -> None:
    response.set_cookie(
        _SESSION_COOKIE,
        _serializer().dumps(user_id),
        httponly=True,
        secure=_secure_cookie(),
        samesite="lax",
        max_age=60 * 60 * 24 * 14,
    )


def _set_signup_cookie(response: Response, payload: dict) -> None:
    # URLSafeTimedSerializer는 서명이지 암호화가 아니다. kakao_id는
    # HttpOnly·짧은 만료·signup API path로만 노출을 제한한다.
    response.set_cookie(
        _SIGNUP_COOKIE,
        _signup_serializer().dumps(payload),
        httponly=True,
        secure=_secure_cookie(),
        samesite="lax",
        max_age=_SIGNUP_MAX_AGE,
        path=_SIGNUP_COOKIE_PATH,
    )


def _validated_signup_payload(payload: object) -> dict:
    if not isinstance(payload, dict):
        raise ValueError("Signup payload is not an object.")
    kind = payload.get("kind")
    if kind == "new":
        kakao_id = payload.get("kakao_id")
        nickname = payload.get("nickname")
        if (
            not isinstance(kakao_id, str)
            or not kakao_id.isdigit()
            or int(kakao_id) <= 0
            or len(kakao_id) > 64
        ):
            raise ValueError("Signup payload kakao identity is invalid.")
        if nickname is not None and (
            not isinstance(nickname, str)
            or not nickname.strip()
            or len(nickname) > 100
        ):
            raise ValueError("Signup payload nickname is invalid.")
        return {"kind": "new", "kakao_id": kakao_id, "nickname": nickname}
    if kind == "existing":
        user_id = payload.get("user_id")
        if not isinstance(user_id, str) or not user_id.strip() or len(user_id) > 36:
            raise ValueError("Signup payload user identity is invalid.")
        return {"kind": "existing", "user_id": user_id}
    raise ValueError("Signup payload kind is invalid.")


def _read_signup_payload(cookie: str | None) -> dict:
    if not cookie:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Signup session required.",
        )
    try:
        payload = _signup_serializer().loads(cookie, max_age=_SIGNUP_MAX_AGE)
    except SignatureExpired as exc:
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail="Signup session expired.",
        ) from exc
    except BadSignature as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid signup session.",
        ) from exc
    try:
        return _validated_signup_payload(payload)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid signup session.",
        ) from exc


def _pending_consent_redirect(payload: dict) -> Response:
    response = RedirectResponse(_frontend_path("/signup/consent"))
    _clear_cookie(response, _STATE_COOKIE)
    _clear_cookie(response, _SESSION_COOKIE)
    _clear_deletion_cookie(response)
    _set_signup_cookie(response, payload)
    return response


def _issue_session_redirect(user_id: str) -> Response:
    response = RedirectResponse(_frontend_path("/"))
    _clear_cookie(response, _STATE_COOKIE)
    _clear_signup_cookie(response)
    _clear_deletion_cookie(response)
    _set_session_cookie(response, user_id)
    return response


def _clear_deletion_cookie(response: Response) -> None:
    response.delete_cookie(
        _DELETION_COOKIE,
        path=_DELETION_COOKIE_PATH,
        secure=_secure_cookie(),
        samesite="lax",
    )


def _set_deletion_cookie(response: Response, user_id: str) -> None:
    # URLSafeTimedSerializer는 서명이지 암호화가 아니다. user_id만 넣고
    # kakao_id는 넣지 않으며, HttpOnly·짧은 만료·deletion API path로만
    # 노출을 제한한다. frontend에는 이 값을 반환하지 않는다.
    response.set_cookie(
        _DELETION_COOKIE,
        _deletion_credential_serializer().dumps({
            "kind": "existing",
            "user_id": user_id,
        }),
        httponly=True,
        secure=_secure_cookie(),
        samesite="lax",
        max_age=_DELETION_MAX_AGE,
        path=_DELETION_COOKIE_PATH,
    )


def _validated_deletion_payload(payload: object) -> dict:
    if not isinstance(payload, dict):
        raise ValueError("Deletion payload is not an object.")
    if payload.get("kind") != "existing":
        raise ValueError("Deletion payload kind is invalid.")
    user_id = payload.get("user_id")
    if not isinstance(user_id, str) or not user_id.strip() or len(user_id) > 36:
        raise ValueError("Deletion payload user identity is invalid.")
    return {"kind": "existing", "user_id": user_id}


def _read_deletion_payload(cookie: str | None) -> dict:
    if not cookie:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Deletion session required.",
        )
    try:
        payload = _deletion_credential_serializer().loads(
            cookie,
            max_age=_DELETION_MAX_AGE,
        )
    except SignatureExpired as exc:
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail="Deletion session expired.",
        ) from exc
    except BadSignature as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid deletion session.",
        ) from exc
    try:
        return _validated_deletion_payload(payload)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid deletion session.",
        ) from exc


def _is_deletion_oauth_state(state: str) -> bool:
    return state.startswith(_DELETION_STATE_PREFIX)


def _validate_deletion_oauth_state(state: str) -> None:
    token = state[len(_DELETION_STATE_PREFIX):]
    try:
        payload = _deletion_oauth_serializer().loads(
            token,
            max_age=_DELETION_MAX_AGE,
        )
    except (BadSignature, SignatureExpired) as exc:
        raise HTTPException(
            status_code=400,
            detail="Kakao authorization was rejected or state validation failed.",
        ) from exc
    if (
        not isinstance(payload, dict)
        or payload.get("intent") != "deletion"
        or not isinstance(payload.get("nonce"), str)
        or not payload["nonce"]
    ):
        raise HTTPException(
            status_code=400,
            detail="Kakao authorization was rejected or state validation failed.",
        )


def _clear_identity_cookies(response: Response) -> None:
    """브라우저에 남은 서비스·가입·삭제 identity를 모두 지운다."""
    _clear_cookie(response, _STATE_COOKIE)
    _clear_cookie(response, _SESSION_COOKIE)
    _clear_signup_cookie(response)
    _clear_deletion_cookie(response)


def _deletion_callback_redirect(db: Session, kakao_id: str) -> Response:
    user = db.scalar(select(User).where(User.kakao_id == kakao_id))
    if user is None:
        response = RedirectResponse(
            _frontend_path("/account-deletion?result=not-found"),
        )
        _clear_identity_cookies(response)
        return response
    response = RedirectResponse(_frontend_path("/account-deletion"))
    _clear_identity_cookies(response)
    _set_deletion_cookie(response, user.id)
    return response


def _create_user_with_preference(
    db: Session,
    *,
    kakao_id: str,
    nickname: str | None,
) -> User:
    """kakao_id unique race를 흡수해 한 계정만 남긴다."""
    user = db.scalar(select(User).where(User.kakao_id == kakao_id))
    if user is not None:
        return user
    created = User(kakao_id=kakao_id, nickname=nickname)
    try:
        with db.begin_nested():
            db.add(created)
            db.flush()
            db.add(UserPreference(user_id=created.id))
            db.flush()
        return created
    except IntegrityError:
        user = db.scalar(select(User).where(User.kakao_id == kakao_id))
        if user is None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Signup could not be completed. Try Kakao login again.",
            )
        return user


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


@router.get("/deletion/kakao/login")
def deletion_kakao_login() -> Response:
    """계정 삭제 본인 확인용 Kakao OAuth. 가입·세션 발급 경로와 분리한다."""
    _configured()
    signed = _deletion_oauth_serializer().dumps({
        "intent": "deletion",
        "nonce": secrets.token_urlsafe(32),
    })
    state = f"{_DELETION_STATE_PREFIX}{signed}"
    query = urlencode({
        "client_id": settings.kakao_rest_api_key,
        "redirect_uri": settings.kakao_oauth_redirect_uri,
        "response_type": "code",
        "state": state,
    })
    response = RedirectResponse(f"https://kauth.kakao.com/oauth/authorize?{query}")
    response.set_cookie(
        _STATE_COOKIE, state, httponly=True, secure=_secure_cookie(),
        samesite="lax", max_age=_DELETION_MAX_AGE,
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
    deletion_oauth = bool(state and _is_deletion_oauth_state(state))
    if deletion_oauth:
        assert state is not None
        _validate_deletion_oauth_state(state)
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
    if deletion_oauth:
        return _deletion_callback_redirect(db, kakao_id)
    user = db.scalar(select(User).where(User.kakao_id == kakao_id))
    if user is None:
        return _pending_consent_redirect({
            "kind": "new",
            "kakao_id": kakao_id,
            "nickname": nickname,
        })
    user.nickname = nickname
    if has_current_terms_agreement(db, user):
        db.commit()
        return _issue_session_redirect(user.id)
    db.commit()
    return _pending_consent_redirect({
        "kind": "existing",
        "user_id": user.id,
    })


@router.get("/signup/status", response_model=None)
def signup_status(
    signup_cookie: str | None = Cookie(default=None, alias=_SIGNUP_COOKIE),
) -> dict | Response:
    """가입을 이어서 완료할 수 있는지만 알린다. 신원은 반환하지 않는다."""
    if not signup_cookie:
        return Response(status_code=204)
    try:
        _read_signup_payload(signup_cookie)
    except HTTPException:
        return Response(status_code=204)
    return {"pending": True}


@router.post("/signup/complete", response_model=None)
def signup_complete(
    payload: SignupCompleteInput,
    signup_cookie: str | None = Cookie(default=None, alias=_SIGNUP_COOKIE),
    db: Session = Depends(database_session),
) -> Response:
    pending = _read_signup_payload(signup_cookie)
    if payload.accept_terms is not True:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Terms acceptance is required.",
        )
    if pending["kind"] == "existing":
        user = db.get(User, pending["user_id"])
        if user is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Signup session is no longer valid.",
            )
    else:
        user = _create_user_with_preference(
            db,
            kakao_id=pending["kakao_id"],
            nickname=pending["nickname"],
        )
    consumed = consume_current_terms_agreement(db, user)
    db.commit()
    response = Response(
        status_code=status.HTTP_204_NO_CONTENT if consumed else status.HTTP_409_CONFLICT,
    )
    _clear_signup_cookie(response)
    _clear_deletion_cookie(response)
    if consumed:
        _set_session_cookie(response, user.id)
    return response


@router.post("/signup/cancel", status_code=204)
def signup_cancel() -> Response:
    response = Response(status_code=204)
    _clear_signup_cookie(response)
    return response


@router.post("/logout", status_code=204)
def logout() -> Response:
    response = Response(status_code=204)
    _clear_cookie(response, _SESSION_COOKIE)
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


async def _perform_account_withdrawal(db: Session, user: User) -> None:
    """인앱 탈퇴와 외부 계정 삭제가 공유하는 데이터 삭제 정책.

    정책을 바꾸지 않는다. admin 가드, Kakao unlink, 최소 분리 보관,
    시설 신고 익명화, 사용자 행 삭제와 commit까지 이 함수가 담당한다.
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
    await _perform_account_withdrawal(db, user)
    response = Response(status_code=204)
    response.delete_cookie(_SESSION_COOKIE, secure=_secure_cookie(), samesite="lax")
    _clear_deletion_cookie(response)
    return response


@router.get("/deletion/status", response_model=None)
def deletion_status(
    deletion_cookie: str | None = Cookie(default=None, alias=_DELETION_COOKIE),
) -> dict | Response:
    """삭제 본인 확인이 유효한지만 알린다. 신원은 반환하지 않는다."""
    if not deletion_cookie:
        return Response(status_code=204)
    try:
        _read_deletion_payload(deletion_cookie)
    except HTTPException:
        return Response(status_code=204)
    return {"verified": True}


@router.post("/deletion/confirm", response_model=None)
async def deletion_confirm(
    deletion_cookie: str | None = Cookie(default=None, alias=_DELETION_COOKIE),
    db: Session = Depends(database_session),
) -> Response:
    try:
        pending = _read_deletion_payload(deletion_cookie)
    except HTTPException as exc:
        if exc.status_code in (
            status.HTTP_401_UNAUTHORIZED,
            status.HTTP_410_GONE,
        ):
            response = Response(status_code=exc.status_code)
            _clear_deletion_cookie(response)
            return response
        raise
    user = db.scalar(
        select(User).where(User.id == pending["user_id"]).with_for_update()
    )
    if user is None:
        response = Response(status_code=status.HTTP_410_GONE)
        _clear_deletion_cookie(response)
        response.delete_cookie(
            _SESSION_COOKIE,
            secure=_secure_cookie(),
            samesite="lax",
        )
        return response
    await _perform_account_withdrawal(db, user)
    response = Response(status_code=204)
    _clear_deletion_cookie(response)
    response.delete_cookie(_SESSION_COOKIE, secure=_secure_cookie(), samesite="lax")
    return response


@router.post("/deletion/cancel", status_code=204)
def deletion_cancel() -> Response:
    response = Response(status_code=204)
    _clear_deletion_cookie(response)
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
