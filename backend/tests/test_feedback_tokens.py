import pytest

from app.feedback_tokens import create_feedback_token, verify_feedback_token
from app.settings import settings


def test_signed_feedback_snapshot_roundtrip(monkeypatch):
    monkeypatch.setattr(settings, "session_secret", "test-secret-with-enough-entropy")
    token = create_feedback_token("route-1", "model-v1", {"stair_count": 2})
    assert token is not None
    payload = verify_feedback_token(token)
    assert payload == {
        "route_id": "route-1",
        "model_version": "model-v1",
        "features": {"stair_count": 2},
    }


def test_tampered_feedback_snapshot_is_rejected(monkeypatch):
    monkeypatch.setattr(settings, "session_secret", "test-secret-with-enough-entropy")
    token = create_feedback_token("route-1", "model-v1", {})
    with pytest.raises(ValueError, match="Invalid"):
        verify_feedback_token(token + "tampered")
