import pytest
from fastapi import HTTPException

from app.api.feedback import ImpressionInput, record_impression
from app.database import User
from app.feedback_tokens import create_feedback_token, verify_feedback_token
from app.settings import settings


def test_signed_feedback_snapshot_roundtrip(monkeypatch):
    monkeypatch.setattr(
        settings,
        "session_secret",
        "test-secret-with-at-least-32-characters",
    )
    token = create_feedback_token(
        "route-1",
        "model-v1",
        {"route_id": "route-1", "stair_count": 2},
        displayed_rank=2,
    )
    assert token is not None
    payload = verify_feedback_token(token)
    assert payload == {
        "route_id": "route-1",
        "model_version": "model-v1",
        "displayed_rank": 2,
        "features": {"route_id": "route-1", "stair_count": 2},
    }


def test_tampered_feedback_snapshot_is_rejected(monkeypatch):
    monkeypatch.setattr(
        settings,
        "session_secret",
        "test-secret-with-at-least-32-characters",
    )
    token = create_feedback_token(
        "route-1",
        "model-v1",
        {},
        displayed_rank=1,
    )
    assert token is not None
    with pytest.raises(ValueError, match="Invalid"):
        verify_feedback_token(token + "tampered")


def test_feedback_token_requires_strong_secret_and_signed_rank(monkeypatch):
    monkeypatch.setattr(settings, "session_secret", "too-short")
    assert (
        create_feedback_token(
            "route-1",
            "model-v1",
            {},
            displayed_rank=1,
        )
        is None
    )

    monkeypatch.setattr(
        settings,
        "session_secret",
        "test-secret-with-at-least-32-characters",
    )
    with pytest.raises(ValueError, match="displayed rank"):
        create_feedback_token(
            "route-1",
            "model-v1",
            {},
            displayed_rank=0,
        )


def test_feedback_token_rejects_mismatched_feature_route(monkeypatch):
    monkeypatch.setattr(
        settings,
        "session_secret",
        "test-secret-with-at-least-32-characters",
    )
    with pytest.raises(ValueError, match="feature route"):
        create_feedback_token(
            "route-1",
            "model-v1",
            {"route_id": "route-2"},
            displayed_rank=1,
        )


def test_impression_rejects_client_rank_different_from_signed_rank(monkeypatch):
    monkeypatch.setattr(
        settings,
        "session_secret",
        "test-secret-with-at-least-32-characters",
    )
    token = create_feedback_token(
        "route-1",
        "model-v1",
        {"route_id": "route-1", "profile": "general"},
        displayed_rank=2,
    )
    assert token is not None
    payload = ImpressionInput(
        route_id="route-1",
        rank=1,
        feedback_token=token,
    )
    user = User(id="user-1", kakao_id="kakao-1")

    with pytest.raises(HTTPException, match="displayed rank") as captured:
        record_impression(payload, user, object())
    assert captured.value.status_code == 400
