"""AI API의 모델 준비 상태와 부산 범위 계약 테스트."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
import time

from fastapi.testclient import TestClient
import numpy as np

import api.router as api_router
import main as ai_main
from main import app
from api.router import (
    RecommendRequest,
    _analysis_route_parts,
    _context_features,
    _parse_api_features,
    _public_segments,
)
from collectors.base import Coordinate, RouteCandidate
from merger.route_merger import MergedRoute
from scoring.train import FEATURE_COLS, ModelNotReady


client = TestClient(app)
REQUIRED_LAYERS = {
    name: [object()]
    for name in ai_main.REQUIRED_LAYER_NAMES
}


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


def test_liveness_does_not_claim_candidate_pipeline_readiness():
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "ai"}


def test_readiness_requires_odsay_but_not_model_artifact(monkeypatch):
    monkeypatch.setattr(ai_main.settings, "ODSAY_API_KEY", "")
    monkeypatch.setattr(ai_main, "_get_layers", lambda: REQUIRED_LAYERS)

    response = client.get("/ready")

    assert response.status_code == 503
    body = response.json()
    assert body["checks"] == {
        "odsay_configured": False,
        "spatial_layers_loaded": True,
    }
    assert body["model_artifact_required"] is False


def test_readiness_fails_without_raw_spatial_layers(monkeypatch):
    def missing_layers():
        raise FileNotFoundError("secret local source path")

    monkeypatch.setattr(ai_main.settings, "ODSAY_API_KEY", "configured-key")
    monkeypatch.setattr(ai_main, "_get_layers", missing_layers)

    response = client.get("/ready")

    assert response.status_code == 503
    assert response.json()["layer_error"] == "FileNotFoundError"
    assert "secret local source path" not in response.text


def test_readiness_accepts_candidate_pipeline_without_ranker(monkeypatch):
    monkeypatch.setattr(ai_main.settings, "ODSAY_API_KEY", "configured-key")
    monkeypatch.setattr(ai_main.settings, "TMAP_API_KEY", "")
    monkeypatch.setattr(
        ai_main.settings,
        "OSMNX_WALK_GEOMETRY_ENABLED",
        False,
    )
    monkeypatch.setattr(ai_main, "_get_layers", lambda: REQUIRED_LAYERS)

    response = client.get("/ready")

    assert response.status_code == 200
    assert response.json()["ready"] is True
    assert response.json()["spatial_layer_count"] == 9
    assert response.json()["capabilities"] == {
        "exact_walking_geometry_configured": False,
    }


def test_readiness_reports_exact_walk_geometry_capability(monkeypatch):
    monkeypatch.setattr(ai_main.settings, "ODSAY_API_KEY", "configured-key")
    monkeypatch.setattr(ai_main.settings, "TMAP_API_KEY", "tmap-key")
    monkeypatch.setattr(
        ai_main.settings,
        "OSMNX_WALK_GEOMETRY_ENABLED",
        False,
    )
    monkeypatch.setattr(
        ai_main,
        "_get_layers",
        lambda: {**REQUIRED_LAYERS, "future_layer": [object()]},
    )

    response = client.get("/ready")

    assert response.status_code == 200
    assert response.json()["ready"] is True
    assert response.json()["spatial_layer_count"] == 10
    assert response.json()["capabilities"] == {
        "exact_walking_geometry_configured": True,
    }


def test_spatial_layer_initialization_is_single_flight(monkeypatch):
    calls = 0

    def slow_load(*, use_cache):
        nonlocal calls
        calls += 1
        time.sleep(0.05)
        return REQUIRED_LAYERS

    monkeypatch.setattr(api_router, "_layers", None)
    monkeypatch.setattr(api_router, "load_all_layers", slow_load)
    with ThreadPoolExecutor(max_workers=4) as executor:
        results = list(executor.map(
            lambda _: api_router._get_layers(),
            range(4),
        ))

    assert calls == 1
    assert all(result is results[0] for result in results)


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


def test_odsay_boarding_counts_are_converted_to_actual_transfers():
    candidate = RouteCandidate(
        source="odsay",
        path=[],
        duration_min=20.0,
        distance_m=5000.0,
        raw_response={
            "info": {
                "busTransitCount": 1,
                "subwayTransitCount": 0,
                "totalWalk": 200,
            },
            "subPath": [],
        },
    )

    features = _parse_api_features(candidate)

    assert features["transfer_count"] == 0


def test_null_stair_count_is_unknown_not_confirmed_zero():
    candidate = RouteCandidate(
        source="odsay",
        path=[],
        duration_min=20.0,
        distance_m=5000.0,
        raw_response={
            "info": {
                "busTransitCount": 1,
                "subwayTransitCount": 0,
            },
            "subPath": [{
                "trafficType": 3,
                "stairInfo": {"stairCount": None},
            }],
        },
    )

    features = _parse_api_features(candidate)

    assert features["stair_count"] is None


def test_complete_route_facilities_preserve_known_false_for_ui_and_model():
    sub_paths = [
        {
            "trafficType": 2,
            "sectionTime": 5,
            "distance": 1000,
            "lane": [{"busNo": "10", "lowFloorYn": "Y"}],
        },
        {
            "trafficType": 3,
            "sectionTime": 3,
            "distance": 200,
            "stairInfo": {"stairCount": 0, "elevatorYN": "Y"},
        },
        {
            "trafficType": 2,
            "sectionTime": 5,
            "distance": 1000,
            "lane": [{"busNo": "20", "lowFloorYn": "N"}],
        },
        {
            "trafficType": 3,
            "sectionTime": 2,
            "distance": 100,
            "stairInfo": {"stairCount": 2, "elevatorYN": "N"},
        },
    ]
    point = Coordinate(35.1000, 129.0000)
    candidate = RouteCandidate(
        source="odsay",
        path=[point, Coordinate(35.1100, 129.0100)],
        duration_min=15,
        distance_m=2300,
        raw_response={
            "info": {"transferCount": 1, "totalWalk": 300},
            "subPath": sub_paths,
        },
        segments=[
            {
                "mode": {2: "bus", 3: "walk"}[sub_path["trafficType"]],
                "duration_min": sub_path["sectionTime"],
                "distance_m": sub_path["distance"],
                "path": [],
                "raw": sub_path,
            }
            for sub_path in sub_paths
        ],
    )

    features = _parse_api_features(candidate)
    segments = _public_segments(candidate)

    assert features["is_low_floor_bus"] is False
    assert features["stair_count"] == 2
    assert features["elevator_ratio"] == 0.5
    assert [
        segment["is_low_floor_bus"]
        for segment in segments
        if segment["mode"] == "bus"
    ] == [True, False]
    assert [
        segment["stairs_count"]
        for segment in segments
        if segment["mode"] == "walk"
    ] == [0, 2]
    assert [
        segment["has_elevator"]
        for segment in segments
        if segment["mode"] == "walk"
    ] == [True, False]


def test_partial_route_facilities_remain_unknown_for_ui_and_model():
    sub_paths = [
        {
            "trafficType": 2,
            "sectionTime": 5,
            "distance": 1000,
            "lane": [{"busNo": "10", "lowFloorYn": "Y"}],
        },
        {
            "trafficType": 2,
            "sectionTime": 5,
            "distance": 1000,
            "lane": [{"busNo": "20"}],
        },
        {
            "trafficType": 3,
            "sectionTime": 3,
            "distance": 200,
            "stairInfo": {"stairCount": 0, "elevatorYN": "Y"},
        },
        {
            "trafficType": 3,
            "sectionTime": 2,
            "distance": 100,
            "stairInfo": {"stairCount": None},
        },
    ]
    candidate = RouteCandidate(
        source="odsay",
        path=[],
        duration_min=15,
        distance_m=2300,
        raw_response={
            "info": {"transferCount": 1, "totalWalk": 300},
            "subPath": sub_paths,
        },
        segments=[
            {
                "mode": {2: "bus", 3: "walk"}[sub_path["trafficType"]],
                "duration_min": sub_path["sectionTime"],
                "distance_m": sub_path["distance"],
                "path": [],
                "raw": sub_path,
            }
            for sub_path in sub_paths
        ],
    )

    features = _parse_api_features(candidate)
    segments = _public_segments(candidate)

    assert features["is_low_floor_bus"] is None
    assert features["stair_count"] is None
    assert features["elevator_ratio"] is None
    assert all(
        segment["is_low_floor_bus"] is None
        for segment in segments
        if segment["mode"] == "bus"
    )
    assert all(
        segment["stairs_count"] is None
        for segment in segments
        if segment["mode"] == "walk"
    )
    assert all(
        segment["has_elevator"] is None
        for segment in segments
        if segment["mode"] == "walk"
    )


def test_facility_parsing_defends_nested_provider_types_without_false_zero():
    candidate = RouteCandidate(
        source="odsay",
        path=[],
        duration_min=10,
        distance_m=1000,
        raw_response={
            "info": [],
            "subPath": [
                {"trafficType": 2, "lane": {"lowFloorYn": "Y"}},
                {"trafficType": 3, "stairInfo": []},
                [],
            ],
            "features": [{"properties": []}],
        },
        segments=[
            {
                "mode": "bus",
                "duration_min": 5,
                "distance_m": 800,
                "path": [],
                "raw": {"lane": {"lowFloorYn": "Y"}},
            },
            {
                "mode": "walk",
                "duration_min": 5,
                "distance_m": 200,
                "path": [],
                "raw": {"stairInfo": []},
            },
        ],
    )

    features = _parse_api_features(candidate)
    segments = _public_segments(candidate)

    assert features["transfer_count"] is None
    assert features["is_low_floor_bus"] is None
    assert features["stair_count"] is None
    assert features["elevator_ratio"] is None
    assert segments[0]["is_low_floor_bus"] is None
    assert segments[1]["has_stairs"] is None
    assert segments[1]["has_elevator"] is None
    assert segments[1]["needs_vertical_move"] is None


def test_boolean_traffic_type_does_not_create_observed_facility_values():
    candidate = RouteCandidate(
        source="odsay",
        path=[],
        duration_min=10,
        distance_m=1000,
        raw_response={
            "info": {"transferCount": 0, "totalWalk": 100},
            "subPath": [{
                "trafficType": True,
                "stairInfo": {
                    "stairCount": 0,
                    "elevatorYN": "Y",
                },
            }],
        },
    )

    features = _parse_api_features(candidate)

    assert features["stair_count"] is None
    assert features["elevator_ratio"] is None
    assert features["is_low_floor_bus"] is None


def test_public_segments_cannot_outclaim_incomplete_route_payload():
    candidate = RouteCandidate(
        source="odsay",
        path=[],
        duration_min=10,
        distance_m=1000,
        raw_response={
            "info": {"transferCount": 0, "totalWalk": 200},
            "subPath": [
                {
                    "trafficType": 2,
                    "lane": [{"busNo": "10"}],
                },
                {
                    "trafficType": 3,
                    "stairInfo": {"stairCount": None},
                },
            ],
        },
        segments=[
            {
                "mode": "bus",
                "duration_min": 5,
                "distance_m": 800,
                "path": [],
                "raw": {
                    "lane": [{"busNo": "10", "lowFloorYn": "Y"}],
                },
            },
            {
                "mode": "walk",
                "duration_min": 5,
                "distance_m": 200,
                "path": [],
                "raw": {
                    "stairInfo": {
                        "stairCount": 0,
                        "elevatorYN": "Y",
                    },
                },
            },
        ],
    )

    features = _parse_api_features(candidate)
    segments = _public_segments(candidate)

    assert features["is_low_floor_bus"] is None
    assert features["stair_count"] is None
    assert features["elevator_ratio"] is None
    assert segments[0]["is_low_floor_bus"] is None
    assert segments[1]["has_stairs"] is None
    assert segments[1]["stairs_count"] is None
    assert segments[1]["has_elevator"] is None


def test_odsay_analysis_uses_only_declared_walk_parts_without_joining_them():
    display_path = [
        Coordinate(35.1000, 129.0000),
        Coordinate(35.1100, 129.0000),
        Coordinate(35.1200, 129.0000),
        Coordinate(35.1300, 129.0000),
    ]
    candidate = MergedRoute(
        sources=["odsay"],
        source="odsay",
        path=display_path,
        duration_min=30,
        distance_m=5000,
        segments=[
            {
                "mode": "walk",
                "path": display_path[:2],
                "geometry_quality": "exact",
                "duration_min": 5,
                "distance_m": 300,
            },
            {
                "mode": "subway",
                "path": display_path[1:3],
                "duration_min": 15,
                "distance_m": 4000,
            },
            {
                "mode": "walk",
                "path": display_path[2:],
                "geometry_quality": "exact",
                "duration_min": 5,
                "distance_m": 300,
            },
        ],
    )

    parts = _analysis_route_parts(candidate)

    assert parts == [
        [(35.1000, 129.0000), (35.1100, 129.0000)],
        [(35.1200, 129.0000), (35.1300, 129.0000)],
    ]
    assert candidate.path == display_path


def test_tmap_standalone_analysis_uses_full_walking_path():
    path = [
        Coordinate(35.1000, 129.0000),
        Coordinate(35.1100, 129.0000),
    ]
    candidate = MergedRoute(
        sources=["tmap"],
        source="tmap",
        path=path,
        duration_min=10,
        distance_m=900,
    )

    assert _analysis_route_parts(candidate) == [[
        (35.1000, 129.0000),
        (35.1100, 129.0000),
    ]]


def test_estimated_walk_geometry_is_not_used_as_observed_feature_path():
    path = [
        Coordinate(35.1000, 129.0000),
        Coordinate(35.1100, 129.0000),
    ]
    odsay = MergedRoute(
        sources=["odsay"],
        source="odsay",
        path=path,
        duration_min=10,
        distance_m=900,
        geometry_quality="mixed",
        segments=[{
            "mode": "walk",
            "path": path,
            "geometry_quality": "estimated",
            "duration_min": 10,
            "distance_m": 900,
        }],
    )
    tmap = MergedRoute(
        sources=["tmap"],
        source="tmap",
        path=path,
        duration_min=10,
        distance_m=900,
        geometry_quality="estimated",
    )

    assert _analysis_route_parts(odsay) == []
    assert _analysis_route_parts(tmap) == []


def test_walk_segment_outdoor_state_remains_unknown_without_provider_evidence():
    point = Coordinate(35.1000, 129.0000)
    candidate = MergedRoute(
        sources=["odsay"],
        source="odsay",
        path=[point, Coordinate(35.1010, 129.0000)],
        duration_min=5,
        distance_m=100,
        segments=[{
            "mode": "walk",
            "path": [point, Coordinate(35.1010, 129.0000)],
            "duration_min": 5,
            "distance_m": 100,
            "raw": {"trafficType": 3},
        }],
    )

    assert _public_segments(candidate)[0]["outdoor"] is None


def test_feature_pipeline_keeps_display_path_but_analyzes_walk_parts(
    monkeypatch,
):
    display_path = [
        Coordinate(35.1000, 129.0000),
        Coordinate(35.1100, 129.0000),
        Coordinate(35.1200, 129.0000),
        Coordinate(35.1300, 129.0000),
    ]
    route = RouteCandidate(
        source="odsay",
        path=display_path,
        duration_min=30,
        distance_m=5000,
        raw_response={
            "info": {
                "transferCount": 0,
                "totalWalk": 600,
            },
            "subPath": [],
        },
        segments=[
            {
                "mode": "walk",
                "path": display_path[:2],
                "geometry_quality": "exact",
                "duration_min": 5,
                "distance_m": 300,
                "raw": {"trafficType": 3},
            },
            {
                "mode": "subway",
                "path": display_path[1:3],
                "duration_min": 15,
                "distance_m": 4000,
                "raw": {"trafficType": 1},
            },
            {
                "mode": "walk",
                "path": display_path[2:],
                "geometry_quality": "exact",
                "duration_min": 5,
                "distance_m": 300,
                "raw": {"trafficType": 3},
            },
        ],
        geometry_quality="mixed",
    )
    observed: list[tuple[str, list[list[tuple[float, float]]]]] = []

    async def collect_odsay(self, origin, destination):
        return [route]

    async def collect_tmap(self, origin, destination):
        raise RuntimeError("not configured")

    async def elevation(parts):
        observed.append(("elevation", parts))
        return {
            "avg_slope_percent": 0,
            "max_slope_percent": 0,
            "min_slope_percent": 0,
            "slope_iqr": 0,
            "uphill_distance_m": 0,
            "downhill_distance_m": 0,
            "elevation_gain_m": 0,
            "elevation_loss_m": 0,
            "elevation_source": "test",
            "elevation_resolution_m": 90,
            "elevation_status": "estimated_90m",
        }

    def spatial(parts, layers):
        observed.append(("spatial", parts))
        return {
            "cctv_density_50m": None,
            "crosswalk_count": None,
            "crosswalk_signal_ratio": None,
            "shelter_nearby": None,
            "aed_nearby": None,
            "wheelchair_charger_nearby": None,
            "smart_shelter_nearby": None,
            "smart_shelter_has_ac": None,
            "dongbaekjeon_store_count_200m": None,
            "bus_stop_count_200m": None,
        }

    monkeypatch.setattr(
        api_router.OdsayRouteCollector,
        "collect",
        collect_odsay,
    )
    monkeypatch.setattr(
        api_router.TmapRouteCollector,
        "collect",
        collect_tmap,
    )
    monkeypatch.setattr(api_router, "_get_layers", lambda: {})
    monkeypatch.setattr(
        api_router,
        "extract_elevation_features_for_parts",
        elevation,
    )
    monkeypatch.setattr(
        api_router,
        "extract_route_features_for_parts",
        spatial,
    )

    features, _ = asyncio.run(api_router._collect_featured_routes(
        RecommendRequest(
            origin_lat=35.10,
            origin_lng=129.00,
            origin_name="출발",
            dest_lat=35.13,
            dest_lng=129.00,
            dest_name="도착",
            profile="general",
        )
    ))

    expected_parts = [
        [(35.1000, 129.0000), (35.1100, 129.0000)],
        [(35.1200, 129.0000), (35.1300, 129.0000)],
    ]
    assert observed == [
        ("elevation", expected_parts),
        ("spatial", expected_parts),
    ]
    assert features[0]["_path"] == [
        {"lat": point.lat, "lng": point.lng}
        for point in display_path
    ]
