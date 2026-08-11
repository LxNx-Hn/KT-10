"""관리자 전용 후기 열람·검토 API의 권한, 필터, 원문 보존 계약."""
from __future__ import annotations

import json
from datetime import datetime

import pytest
from fastapi import Depends
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.api.auth import current_user, optional_current_user
from app.database import Base, RouteImpression, RouteReview, User, database_session
from app.main import app


@pytest.fixture()
def admin_api(tmp_path):
    engine = create_engine(
        f"sqlite+pysqlite:///{(tmp_path / 'admin-reviews.sqlite3').as_posix()}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        admin = User(id="admin", kakao_id="100", nickname="관리자", is_admin=True)
        member = User(id="member", kakao_id="200", nickname="사용자", is_admin=False)
        impression = RouteImpression(
            id="impression-1",
            user_id=member.id,
            route_id="route-1",
            model_version="rules-live-v1",
            profile="disabled",
            rank=2,
            feature_snapshot=json.dumps({
                "avg_slope_percent": 4.2,
                "max_slope_percent": 8.1,
                "stairs_count": None,
                "training_eligible": True,
            }),
        )
        db.add_all([admin, member, impression])
        db.add_all([
            RouteReview(
                id="review-pending",
                user_id=member.id,
                impression_id=impression.id,
                route_id=impression.route_id,
                was_usable=False,
                rating=2,
                issue_type="slope",
                slope_difficulty=5,
                information_accurate=False,
                comment="표시보다 경사가 훨씬 가팔랐습니다.",
                training_consent=False,
                moderation_status="pending",
                created_at=datetime(2026, 8, 11, 1, 0),
            ),
            RouteReview(
                id="review-verified",
                user_id=member.id,
                impression_id=None,
                route_id="route-old",
                was_usable=True,
                rating=4,
                issue_type="elevator",
                information_accurate=True,
                training_consent=True,
                moderation_status="verified",
                resolution_note="현장 자료와 일치",
                reviewed_by=admin.id,
                reviewed_at=datetime(2026, 8, 11, 2, 0),
                created_at=datetime(2026, 8, 10, 1, 0),
            ),
        ])
        db.commit()

    def test_database_session():
        with Session(engine) as db:
            yield db
            db.commit()

    def authenticated_admin(db: Session = Depends(test_database_session)) -> User:
        user = db.get(User, "admin")
        assert user is not None
        return user

    app.dependency_overrides[database_session] = test_database_session
    app.dependency_overrides[current_user] = authenticated_admin
    app.dependency_overrides[optional_current_user] = authenticated_admin
    try:
        yield TestClient(app), engine
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def test_admin_list_filters_paginates_and_excludes_provider_identity(admin_api):
    client, _ = admin_api
    response = client.get(
        "/api/admin/route-reviews",
        params={"status": "pending", "issueType": "slope", "limit": 1},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["limit"] == 1
    assert body["offset"] == 0
    assert [item["id"] for item in body["items"]] == ["review-pending"]
    item = body["items"][0]
    assert item["profile"] == "disabled"
    assert item["rank"] == 2
    assert "kakaoId" not in item
    assert "nickname" not in item
    assert "userId" not in item


def test_admin_detail_returns_review_and_displayed_feature_snapshot(admin_api):
    client, _ = admin_api
    response = client.get("/api/admin/route-reviews/review-pending")

    assert response.status_code == 200
    body = response.json()
    assert body["comment"] == "표시보다 경사가 훨씬 가팔랐습니다."
    assert body["slopeDifficulty"] == 5
    assert body["featureSnapshot"]["avg_slope_percent"] == 4.2
    assert body["featureSnapshot"]["stairs_count"] is None
    assert body["trainingConsent"] is False


def test_admin_moderation_records_audit_metadata_without_mutating_review(admin_api):
    client, engine = admin_api
    response = client.patch(
        "/api/admin/route-reviews/review-pending",
        json={"status": "verified", "resolutionNote": "현장 사진과 경로 선형을 대조함"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["moderationStatus"] == "verified"
    assert body["resolutionNote"] == "현장 사진과 경로 선형을 대조함"
    assert body["reviewedAt"] is not None
    assert body["trainingConsent"] is False
    assert body["comment"] == "표시보다 경사가 훨씬 가팔랐습니다."

    with Session(engine) as db:
        saved = db.get(RouteReview, "review-pending")
        assert saved is not None
        assert saved.reviewed_by == "admin"
        assert saved.training_consent is False
        assert saved.rating == 2
        assert saved.comment == "표시보다 경사가 훨씬 가팔랐습니다."


def test_non_admin_cannot_list_detail_or_moderate(admin_api):
    client, engine = admin_api

    def authenticated_member(db: Session = Depends(database_session)) -> User:
        user = db.get(User, "member")
        assert user is not None
        return user

    app.dependency_overrides[current_user] = authenticated_member

    assert client.get("/api/admin/route-reviews").status_code == 403
    assert client.get("/api/admin/route-reviews/review-pending").status_code == 403
    assert client.patch(
        "/api/admin/route-reviews/review-pending",
        json={"status": "rejected", "resolutionNote": "권한 없는 변경"},
    ).status_code == 403

    with Session(engine) as db:
        saved = db.get(RouteReview, "review-pending")
        assert saved is not None
        assert saved.moderation_status == "pending"


def test_admin_api_rejects_invalid_input_and_missing_review(admin_api):
    client, _ = admin_api
    assert client.get(
        "/api/admin/route-reviews",
        params={"limit": 101},
    ).status_code == 422
    assert client.patch(
        "/api/admin/route-reviews/review-pending",
        json={"status": "verified", "resolutionNote": "x"},
    ).status_code == 422
    assert client.get("/api/admin/route-reviews/missing").status_code == 404
    assert client.patch(
        "/api/admin/route-reviews/missing",
        json={"status": "verified", "resolutionNote": "대상 없음"},
    ).status_code == 404


def test_auth_me_exposes_only_admin_flag_not_provider_id(admin_api):
    client, _ = admin_api
    response = client.get("/api/auth/me")

    assert response.status_code == 200
    assert response.json()["isAdmin"] is True
    assert "kakaoId" not in response.json()
