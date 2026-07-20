"""추천 당시 서버 피처를 위변조 없이 후기와 연결하는 서명 토큰."""
from __future__ import annotations

from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from .settings import settings

SALT = "route-feedback-v1"


def _serializer() -> URLSafeTimedSerializer:
    if not settings.session_secret:
        raise RuntimeError("SESSION_SECRET is required for signed feedback snapshots.")
    return URLSafeTimedSerializer(settings.session_secret, salt=SALT)


def create_feedback_token(route_id: str, model_version: str, features: dict) -> str | None:
    if not settings.session_secret:
        return None
    return _serializer().dumps({
        "route_id": route_id,
        "model_version": model_version,
        "features": features,
    })


def verify_feedback_token(token: str, max_age_seconds: int = 60 * 60 * 24) -> dict:
    try:
        payload = _serializer().loads(token, max_age=max_age_seconds)
    except SignatureExpired as exc:
        raise ValueError("Feedback token expired.") from exc
    except BadSignature as exc:
        raise ValueError("Invalid feedback token.") from exc
    if not isinstance(payload, dict) or not isinstance(payload.get("features"), dict):
        raise ValueError("Invalid feedback token payload.")
    return payload
