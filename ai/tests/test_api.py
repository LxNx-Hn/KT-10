"""AI API의 모델 준비 상태와 부산 범위 계약 테스트."""
from fastapi.testclient import TestClient
import numpy as np

import api.router as api_router
from main import app
from api.router import RecommendRequest, _context_features
from scoring.train import FEATURE_COLS, ModelNotReady


client = TestClient(app)


def test_model_status_reports_not_ready_without_fabricated_model(monkeypatch):
    monkeypatch.setattr(api_router, "_rankers", None)
    monkeypatch.setattr(api_router, "load_rankers", lambda: (_ for _ in ()).throw(ModelNotReady("라벨 필요")))
    response = client.get("/model/status")
    assert response.status_code == 200
    assert response.json() == {
        "ready": False,
        "configured_tier": "human_validated",
        "profiles": [],
        "detail": "라벨 필요",
    }


def test_model_status_loads_judge_only_when_explicitly_configured(monkeypatch):
    monkeypatch.setattr(api_router, "_rankers", None)
    monkeypatch.setattr(api_router.settings, "RANKER_TIER", "judge_baseline")
    monkeypatch.setattr(
        api_router,
        "load_judge_baseline_rankers",
        lambda: {profile: object() for profile in (
            "general", "elderly", "child", "youth", "disabled", "pregnant"
        )},
    )
    monkeypatch.setattr(
        api_router,
        "load_judge_baseline_metadata",
        lambda: {
            "model_tier": "judge_baseline",
            "model_version": "judge-test",
            "label_origin": "llm_judge",
            "metrics": {},
        },
    )

    response = client.get("/model/status")

    assert response.status_code == 200
    body = response.json()
    assert body["ready"] is True
    assert body["configured_tier"] == "judge_baseline"
    assert body["model_tier"] == "judge_baseline"
    assert len(body["profiles"]) == 6


def test_direct_recommend_is_disabled_to_preserve_backend_shade_contract():
    response = client.post("/recommend", json={
        "origin_lat": 35.115, "origin_lng": 129.04, "origin_name": "부산역",
        "dest_lat": 35.157, "dest_lng": 129.059, "dest_name": "서면역",
        "profile": "general",
    })
    assert response.status_code == 409
    assert "backend /api/routes/recommend" in response.json()["detail"]


def test_recommend_rejects_coordinates_outside_busan():
    response = client.post("/recommend", json={
        "origin_lat": 37.5665, "origin_lng": 126.978, "origin_name": "서울",
        "dest_lat": 35.157, "dest_lng": 129.059, "dest_name": "서면역",
        "profile": "general",
    })
    assert response.status_code == 422


def test_labeling_candidates_does_not_require_trained_model(monkeypatch):
    feature = {
        "_sources": ["osmnx"],
        "_path": [{"lat": 35.11, "lng": 129.04}, {"lat": 35.12, "lng": 129.05}],
        "_segments": [{"mode": "walk", "description": "보행"}],
        "_geometry_quality": "exact",
        "_duration_min": 12.0,
        "_distance_m": 800.0,
        "temp_c": 20.0,
        "walk_distance_m": 800.0,
    }

    async def fake_collect(_request):
        return [feature], {
            "sources_attempted": ["osmnx"],
            "sources_succeeded": ["osmnx"],
            "sources_failed": [],
            "source_errors": {},
        }

    monkeypatch.setattr(api_router, "_collect_featured_routes", fake_collect)
    response = client.post("/labeling/candidates", json={
        "origin_lat": 35.11, "origin_lng": 129.04, "origin_name": "부산역",
        "dest_lat": 35.12, "dest_lng": 129.05, "dest_name": "테스트",
        "profile": "general", "weather": "normal",
    })
    assert response.status_code == 200
    body = response.json()
    assert body["candidates"][0]["features"]["walk_distance_m"] == 800.0
    assert body["candidates"][0]["route_id"].startswith("route-")
    assert body["candidates"][0]["feature_snapshot"]["snapshot_kind"] == "live_route_candidate"
    trait = body["candidates"][0]["trait_labels"]
    assert trait["feature_snapshot_hash"] == body["candidates"][0]["feature_snapshot"]["feature_snapshot_hash"]
    assert "shortest" in {label["label_id"] for label in trait["labels"]}


def test_rank_candidates_uses_backend_enriched_complete_features(monkeypatch):
    class Ranker:
        def predict(self, _frame):
            return np.array([0.2, 0.8])

    monkeypatch.setattr(api_router, "_rankers", {"general": Ranker()})
    monkeypatch.setattr(api_router, "_get_model_metadata", lambda: {
        "model_version": "judge-test",
        "model_tier": "judge_baseline",
        "label_origin": "llm_judge",
    })
    base = {name: None for name in FEATURE_COLS}
    response = client.post("/rank/candidates", json={
        "profile": "general",
        "candidates": [
            {
                "route_id": "route-a",
                "features": {
                    **base,
                    "shade_ratio": 0.2,
                    "shaded_walk_m": 100,
                    "shade_building_height_coverage": 1.0,
                },
            },
            {
                "route_id": "route-b",
                "features": {
                    **base,
                    "shade_ratio": 0.8,
                    "shaded_walk_m": 400,
                    "shade_building_height_coverage": 1.0,
                },
            },
        ],
    })

    assert response.status_code == 200
    body = response.json()
    assert [item["route_id"] for item in body["ranked"]] == [
        "route-b",
        "route-a",
    ]
    assert body["ranked"][0]["relative_fit_score"] == 1.0
    assert body["metadata"]["model_tier"] == "judge_baseline"


def test_rank_candidates_rejects_incomplete_features(monkeypatch):
    monkeypatch.setattr(api_router, "_rankers", {"general": object()})
    monkeypatch.setattr(api_router, "_get_model_metadata", lambda: {
        "model_tier": "human_validated",
    })

    response = client.post("/rank/candidates", json={
        "profile": "general",
        "candidates": [{"route_id": "route-a", "features": {}}],
    })

    assert response.status_code == 422
    assert response.json()["detail"]["message"] == "순위화 피처가 누락되었습니다."


def test_enriched_snapshot_identity_changes_with_shade_evaluation_time():
    features = {
        **{name: None for name in FEATURE_COLS},
        "total_duration_min": 20.0,
        "walk_distance_m": 500.0,
        "transfer_count": 0,
        "shade_ratio": 0.6,
        "shaded_walk_m": 300.0,
        "shade_building_height_coverage": 1.0,
        "shade_priority_unshaded_walk_m": 200.0,
    }

    def request_at(shade_evaluated_at: str):
        return client.post("/labeling/enriched-snapshots", json={
            "base_group_id": "source-group",
            "holdout_group_id": "od-busan-seomyeon",
            "captured_at": "2026-07-24T12:00:00+09:00",
            "shade_evaluated_at": shade_evaluated_at,
            "candidates": [{
                "route_id": "route-a",
                "base_snapshot_hash": "a" * 64,
                "sources": ["odsay", "demo-buildings-v1"],
                "geometry_quality": "mixed",
                "features": features,
            }],
        })

    morning = request_at("2026-08-01T09:00:00+09:00")
    afternoon = request_at("2026-08-01T14:00:00+09:00")

    assert morning.status_code == 200
    assert afternoon.status_code == 200
    morning_body = morning.json()
    afternoon_body = afternoon.json()
    assert morning_body["group_id"] != afternoon_body["group_id"]
    assert (
        morning_body["candidates"][0]["feature_snapshot"]["holdout_group_id"]
        == afternoon_body["candidates"][0]["feature_snapshot"]["holdout_group_id"]
        == "od-busan-seomyeon"
    )
    assert (
        morning_body["candidates"][0]["feature_snapshot"]["captured_at"]
        == afternoon_body["candidates"][0]["feature_snapshot"]["captured_at"]
    )
    assert (
        morning_body["candidates"][0]["feature_snapshot"]["shade_evaluated_at"]
        != afternoon_body["candidates"][0]["feature_snapshot"]["shade_evaluated_at"]
    )
    assert (
        morning_body["candidates"][0]["feature_snapshot"]["feature_snapshot_hash"]
        != afternoon_body["candidates"][0]["feature_snapshot"]["feature_snapshot_hash"]
    )
    trait = afternoon_body["candidates"][0]["trait_labels"]
    assert trait["feature_snapshot_hash"] == (
        afternoon_body["candidates"][0]["feature_snapshot"]["feature_snapshot_hash"]
    )
    assert "most_shade" in {
        label["label_id"] for label in trait["labels"]
    }


def test_context_features_preserve_unknown_for_enabled_situations():
    request = RecommendRequest(
        origin_lat=35.11,
        origin_lng=129.04,
        origin_name="부산역",
        dest_lat=35.12,
        dest_lng=129.05,
        dest_name="테스트",
        profile="pregnant",
        stroller=True,
        shade_priority=True,
        minimize_transfers=True,
    )
    features = _context_features({
        "walk_distance_m": None,
        "stair_count": None,
        "elevator_ratio": None,
        "transfer_count": None,
        "shade_ratio": None,
        "shaded_walk_m": None,
        "is_low_floor_bus": None,
    }, request)

    assert features["stroller_walk_burden"] is None
    assert features["stroller_stair_burden"] is None
    assert features["stroller_elevator_gap"] is None
    assert features["shade_priority_unshaded_walk_m"] is None
    assert features["minimize_transfers_burden"] is None


def test_context_features_compute_known_situational_burdens():
    request = RecommendRequest(
        origin_lat=35.11,
        origin_lng=129.04,
        origin_name="부산역",
        dest_lat=35.12,
        dest_lng=129.05,
        dest_name="테스트",
        profile="general",
        stroller=True,
        shade_priority=True,
        minimize_transfers=True,
    )
    features = _context_features({
        "walk_distance_m": 1000.0,
        "stair_count": 2,
        "elevator_ratio": 0.25,
        "transfer_count": 3,
        "shade_ratio": 0.6,
        "shaded_walk_m": 600.0,
        "is_low_floor_bus": None,
    }, request)

    assert features["stroller_walk_burden"] == 1000.0
    assert features["stroller_stair_burden"] == 2
    assert features["stroller_elevator_gap"] == 0.75
    assert features["shade_priority_unshaded_walk_m"] == 400.0
    assert features["minimize_transfers_burden"] == 3
