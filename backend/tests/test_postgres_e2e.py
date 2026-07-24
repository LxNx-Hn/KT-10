"""실제 PostgreSQL을 선택적으로 사용하는 후기 개인화 종단 테스트.

기본 CI에서는 외부 서비스 의존을 만들지 않으며, 로컬 검증 시
RUN_POSTGRES_E2E=1과 DATABASE_URL을 지정해 실행한다.
"""
from __future__ import annotations

import json
import os
from uuid import uuid4

import pytest
from fastapi import Depends
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, delete, select
from sqlalchemy.orm import Session

from app.api.auth import current_user, optional_current_user
from app.database import (
    RouteImpression,
    RouteReview,
    User,
    UserPreference,
    database_session,
    init_database,
)
from app.main import app
from app.settings import settings


pytestmark = pytest.mark.skipif(
    os.getenv("RUN_POSTGRES_E2E") != "1",
    reason="RUN_POSTGRES_E2E=1에서만 실제 PostgreSQL을 사용합니다.",
)


def test_postgres_review_updates_user_personalization(monkeypatch):
    assert settings.database_configured
    monkeypatch.setattr(
        settings,
        "session_secret",
        "postgres-e2e-only-secret-with-32-chars",
    )
    monkeypatch.setattr(settings, "route_mode", "demo")
    monkeypatch.setattr(settings, "building_source", "demo")
    monkeypatch.setattr(settings, "openweather_api_key", "")
    init_database()

    engine = create_engine(settings.database_url, pool_pre_ping=True)
    kakao_id = f"e2e-{uuid4()}"
    with Session(engine) as db:
        user = User(kakao_id=kakao_id, nickname="E2E")
        db.add(user)
        db.flush()
        db.add(UserPreference(user_id=user.id, profile="disabled"))
        db.commit()
        user_id = user.id

    def authenticated_user(
        db: Session = Depends(database_session),
    ) -> User:
        user = db.get(User, user_id)
        assert user is not None
        return user

    app.dependency_overrides[current_user] = authenticated_user
    app.dependency_overrides[optional_current_user] = authenticated_user
    try:
        with TestClient(app) as client:
            recommendation = client.post(
                "/api/routes/recommend",
                json={
                    "origin": {
                        "id": "gu-office",
                        "name": "부산진구청",
                        "lat": 35.1629,
                        "lng": 129.0532,
                    },
                    "destination": {
                        "id": "seomyeon-stn",
                        "name": "서면역",
                        "lat": 35.1578,
                        "lng": 129.0592,
                    },
                    "profile": "disabled",
                    "weatherScenario": "normal",
                    "options": {
                        "lowFloorPriority": False,
                        "departureAt": "2026-07-23T14:00:00+09:00",
                    },
                    "topN": 3,
                },
            )
            assert recommendation.status_code == 200
            first = recommendation.json()[0]
            token = first["score"]["feedbackToken"]
            route_id = first["route"]["id"]

            impression = client.post(
                "/api/route-impressions",
                json={"routeId": route_id, "rank": 1, "feedbackToken": token},
            )
            assert impression.status_code == 201
            impression_id = impression.json()["id"]

            review = client.post(
                "/api/route-reviews",
                json={
                    "routeId": route_id,
                    "impressionId": impression_id,
                    "wasUsable": True,
                    "rating": 5,
                    "crowdingDifficulty": 2,
                    "transferInformationDifficulty": 3,
                    "accessibilityFacilityDifficulty": 1,
                    "wouldReuse": True,
                    "trainingConsent": False,
                },
            )
            assert review.status_code == 201
            assert review.json()["acceptedForTraining"] is False
            duplicate = client.post(
                "/api/route-reviews",
                json={
                    "routeId": route_id,
                    "impressionId": impression_id,
                    "wasUsable": False,
                    "rating": 1,
                    "wouldReuse": False,
                    "trainingConsent": True,
                },
            )
            assert duplicate.status_code == 409

        with Session(engine) as db:
            saved_review = db.scalar(
                select(RouteReview).where(RouteReview.user_id == user_id)
            )
            preference = db.get(UserPreference, user_id)
            assert saved_review is not None
            assert preference is not None
            assert saved_review.crowding_difficulty == 2
            assert saved_review.transfer_information_difficulty == 3
            assert saved_review.accessibility_facility_difficulty == 1
            state = json.loads(preference.personalization_state)
            assert state["updates"] == 1
            assert state["weights"]
    finally:
        app.dependency_overrides.pop(current_user, None)
        app.dependency_overrides.pop(optional_current_user, None)
        with Session(engine) as db:
            db.execute(delete(RouteReview).where(RouteReview.user_id == user_id))
            db.execute(delete(RouteImpression).where(RouteImpression.user_id == user_id))
            db.execute(delete(UserPreference).where(UserPreference.user_id == user_id))
            db.execute(delete(User).where(User.id == user_id))
            db.commit()
