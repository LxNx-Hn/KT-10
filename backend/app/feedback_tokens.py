"""추천 당시 서버 피처를 위변조 없이 후기와 연결하는 서명 토큰."""
from __future__ import annotations

from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from .settings import settings

SALT = "route-feedback-v1"


def _serializer() -> URLSafeTimedSerializer:
    if not settings.session_signing_configured:
        raise RuntimeError(
            "SESSION_SECRET must be at least 32 characters for signed feedback snapshots."
        )
    return URLSafeTimedSerializer(settings.session_secret, salt=SALT)


def _validated_payload(payload: object) -> dict:
    if not isinstance(payload, dict) or not isinstance(payload.get("features"), dict):
        raise ValueError("Invalid feedback token payload.")
    route_id = payload.get("route_id")
    model_version = payload.get("model_version")
    displayed_rank = payload.get("displayed_rank")
    if not isinstance(route_id, str) or not 1 <= len(route_id) <= 120:
        raise ValueError("Invalid feedback token route.")
    if not isinstance(model_version, str) or not 1 <= len(model_version) <= 64:
        raise ValueError("Invalid feedback token model version.")
    if (
        isinstance(displayed_rank, bool)
        or not isinstance(displayed_rank, int)
        or not 1 <= displayed_rank <= 20
    ):
        raise ValueError("Invalid feedback token displayed rank.")
    feature_route_id = payload["features"].get("route_id")
    if feature_route_id is not None and feature_route_id != route_id:
        raise ValueError("Feedback token feature route does not match.")
    return payload


def create_feedback_token(
    route_id: str,
    model_version: str,
    features: dict,
    *,
    displayed_rank: int,
) -> str | None:
    if not settings.session_signing_configured:
        return None
    payload = _validated_payload({
        "route_id": route_id,
        "model_version": model_version,
        "displayed_rank": displayed_rank,
        "features": features,
    })
    return _serializer().dumps(payload)


def verify_feedback_token(token: str, max_age_seconds: int = 60 * 60 * 24) -> dict:
    try:
        payload = _serializer().loads(token, max_age=max_age_seconds)
    except SignatureExpired as exc:
        raise ValueError("Feedback token expired.") from exc
    except BadSignature as exc:
        raise ValueError("Invalid feedback token.") from exc
    return _validated_payload(payload)
