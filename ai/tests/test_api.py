"""AI API의 모델 준비 상태와 부산 범위 계약 테스트."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
import time

from fastapi.testclient import TestClient
import geopandas as gpd
import numpy as np
import pytest
from fastapi import HTTPException

import api.router as api_router
import main as ai_main
from main import app
from api.router import (
    RecommendRequest,
    _analysis_route_parts,
    _collect_static_featured_routes,
    _context_features,
    _enrich_subway_elevator_accessibility,
    _parse_api_features,
    _public_segments,
    _static_features_cacheable,
    _wheelchair_candidate_constrained,
)
from collectors.base import CollectorNotConfigured, Coordinate, RouteCandidate
from collectors.odsay_collector import OdsayRouteCollector
from collectors.ors_collector import (
    WHEELCHAIR_RESTRICTIONS,
    OrsWheelchairRouteCollector,
)
from collectors.tmap_collector import TmapRouteCollector
from merger.route_merger import MergedRoute
from scoring.train import FEATURE_COLS, ModelNotReady
from shapely.geometry import Point


client = TestClient(app)
REQUIRED_LAYERS = {
    name: [object()]
    for name in ai_main.REQUIRED_LAYER_NAMES
}


def test_static_route_cache_accepts_only_exact_90m_features():
    complete = {
        "_geometry_quality": "exact",
        "elevation_status": "estimated_90m",
        "_slope_segments": [{"distance_m": 90}],
    }

    assert _static_features_cacheable([complete]) is True
    # 보행 geometry가 확인되지 않은 mixed 후보는 캐시하지 않는다.
    assert _static_features_cacheable([
        {**complete, "_geometry_quality": "mixed"},
    ]) is False
    # 대중교통 표시 선형만 estimated인 지연 정밀화 후보는
    # 보행 exact + 90m 경사가 완성되면 캐시할 수 있다.
    assert _static_features_cacheable([
        {
            **complete,
            "_geometry_quality": "mixed",
            "_segments": [
                {"mode": "walk", "geometry_quality": "exact"},
                {"mode": "bus", "geometry_quality": "estimated"},
            ],
        },
    ]) is True
    assert _static_features_cacheable([
        {
            **complete,
            "_geometry_quality": "mixed",
            "_segments": [
                {"mode": "walk", "geometry_quality": "estimated"},
                {"mode": "bus", "geometry_quality": "estimated"},
            ],
        },
    ]) is False
    assert _static_features_cacheable([
        {**complete, "elevation_status": "unavailable"},
    ]) is False
    assert _static_features_cacheable([
        {**complete, "_slope_segments": []},
    ]) is False


def test_model_status_reports_not_ready_without_fabricated_model(monkeypatch):
    monkeypatch.setattr(api_router.settings, "RANKER_TIER", "human_validated")
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


def test_lifespan_preloads_regional_walk_graph_when_enabled(monkeypatch):
    calls = []
    monkeypatch.setattr(
        ai_main.settings,
        "OSMNX_WALK_GEOMETRY_ENABLED",
        True,
    )
    monkeypatch.setattr(
        ai_main,
        "prepare_regional_graph",
        lambda: calls.append(True)
        or {"nodes": 10, "edges": 20, "routable_nodes": 9},
    )

    async def run():
        async with ai_main.lifespan(app):
            return None

    asyncio.run(run())

    assert calls == [True]


def test_readiness_requires_odsay_but_not_model_artifact(monkeypatch):
    monkeypatch.setattr(ai_main.settings, "ODSAY_API_KEY", "")
    monkeypatch.setattr(ai_main.settings, "TMAP_API_KEY", "")
    monkeypatch.setattr(ai_main.settings, "ORS_API_KEY", "")
    monkeypatch.setattr(
        ai_main.settings,
        "OSMNX_WALK_GEOMETRY_ENABLED",
        False,
    )
    monkeypatch.setattr(ai_main, "_get_layers", lambda: REQUIRED_LAYERS)
    monkeypatch.setattr(ai_main, "regional_dem_ready", lambda: True)

    response = client.get("/ready")

    assert response.status_code == 503
    body = response.json()
    assert body["checks"] == {
        "odsay_configured": False,
        "spatial_layers_loaded": True,
        "regional_dem_precomputed": True,
        "exact_walking_geometry_ready": False,
        "wheelchair_routing_configured": False,
        "internal_service_auth": True,
    }
    assert body["model_artifact_required"] is False


def test_readiness_fails_without_raw_spatial_layers(monkeypatch):
    def missing_layers():
        raise FileNotFoundError("secret local source path")

    monkeypatch.setattr(ai_main.settings, "ODSAY_API_KEY", "configured-key")
    monkeypatch.setattr(ai_main.settings, "TMAP_API_KEY", "tmap-key")
    monkeypatch.setattr(ai_main.settings, "ORS_API_KEY", "ors-key")
    monkeypatch.setattr(ai_main, "_get_layers", missing_layers)
    monkeypatch.setattr(ai_main, "regional_dem_ready", lambda: True)

    response = client.get("/ready")

    assert response.status_code == 503
    assert response.json()["layer_error"] == "FileNotFoundError"
    assert "secret local source path" not in response.text


def test_readiness_rejects_candidate_pipeline_without_exact_walk_geometry(
    monkeypatch,
):
    monkeypatch.setattr(ai_main.settings, "ODSAY_API_KEY", "configured-key")
    monkeypatch.setattr(ai_main.settings, "TMAP_API_KEY", "")
    monkeypatch.setattr(ai_main.settings, "ORS_API_KEY", "ors-key")
    monkeypatch.setattr(
        ai_main.settings,
        "OSMNX_WALK_GEOMETRY_ENABLED",
        False,
    )
    monkeypatch.setattr(ai_main, "_get_layers", lambda: REQUIRED_LAYERS)
    monkeypatch.setattr(ai_main, "regional_dem_ready", lambda: True)

    response = client.get("/ready")

    assert response.status_code == 503
    assert response.json()["ready"] is False
    assert response.json()["spatial_layer_count"] == 12
    assert response.json()["capabilities"] == {
        "exact_walking_geometry_configured": False,
        "wheelchair_routing_configured": True,
    }


def test_readiness_reports_exact_walk_geometry_capability(monkeypatch):
    monkeypatch.setattr(ai_main.settings, "ODSAY_API_KEY", "configured-key")
    monkeypatch.setattr(ai_main.settings, "TMAP_API_KEY", "tmap-key")
    monkeypatch.setattr(ai_main.settings, "ORS_API_KEY", "ors-key")
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
    monkeypatch.setattr(ai_main, "regional_dem_ready", lambda: True)

    response = client.get("/ready")

    assert response.status_code == 200
    assert response.json()["ready"] is True
    assert response.json()["spatial_layer_count"] == 13
    assert response.json()["capabilities"] == {
        "exact_walking_geometry_configured": True,
        "wheelchair_routing_configured": True,
    }


def test_readiness_rejects_missing_wheelchair_routing_provider(monkeypatch):
    monkeypatch.setattr(ai_main.settings, "ODSAY_API_KEY", "configured-key")
    monkeypatch.setattr(ai_main.settings, "TMAP_API_KEY", "tmap-key")
    monkeypatch.setattr(ai_main.settings, "ORS_API_KEY", "")
    monkeypatch.setattr(ai_main, "_get_layers", lambda: REQUIRED_LAYERS)
    monkeypatch.setattr(ai_main, "regional_dem_ready", lambda: True)

    response = client.get("/ready")

    assert response.status_code == 503
    assert response.json()["checks"]["wheelchair_routing_configured"] is False
    assert response.json()["capabilities"][
        "wheelchair_routing_configured"
    ] is False


def test_production_readiness_rejects_short_internal_token(monkeypatch):
    """production은 32자 미만 내부 토큰이면 다른 준비 조건과 무관하게 실패한다."""
    monkeypatch.setattr(ai_main.settings, "APP_ENV", "production")
    monkeypatch.setattr(ai_main.settings, "AI_INTERNAL_SERVICE_TOKEN", "short")
    monkeypatch.setattr(ai_main.settings, "ODSAY_API_KEY", "configured-key")
    monkeypatch.setattr(ai_main.settings, "TMAP_API_KEY", "tmap-key")
    monkeypatch.setattr(ai_main.settings, "ORS_API_KEY", "ors-key")
    monkeypatch.setattr(ai_main, "_get_layers", lambda: REQUIRED_LAYERS)
    monkeypatch.setattr(ai_main, "regional_dem_ready", lambda: True)

    response = client.get("/ready")

    assert response.status_code == 503
    assert response.json()["ready"] is False
    assert response.json()["checks"]["internal_service_auth"] is False


def test_spatial_layer_initialization_is_single_flight(monkeypatch):
    calls = 0

    def slow_load(*, use_cache):
        nonlocal calls
        calls += 1
        time.sleep(0.05)
        return REQUIRED_LAYERS

    monkeypatch.setattr(api_router, "_layers", None)
    monkeypatch.setattr(api_router, "load_all_layers", slow_load)
    monkeypatch.setattr(
        api_router,
        "prepare_spatial_layers",
        lambda layers: layers,
    )
    with ThreadPoolExecutor(max_workers=4) as executor:
        results = list(executor.map(
            lambda _: api_router._get_layers(),
            range(4),
        ))

    assert calls == 1
    assert all(result is results[0] for result in results)


def test_model_status_loads_bootstrap_only_when_explicitly_configured(
    monkeypatch,
):
    monkeypatch.setattr(api_router, "_rankers", None)
    monkeypatch.setattr(
        api_router.settings,
        "RANKER_TIER",
        "bootstrap_baseline",
    )
    monkeypatch.setattr(
        api_router,
        "load_bootstrap_baseline_rankers",
        lambda: {profile: object() for profile in (
            "general", "elderly", "child", "youth", "disabled", "pregnant"
        )},
    )
    monkeypatch.setattr(
        api_router,
        "load_bootstrap_baseline_metadata",
        lambda: {
            "model_tier": "bootstrap_baseline",
            "model_version": "bootstrap-test",
            "label_origin": "bootstrap_evaluation",
            "metrics": {},
        },
    )

    response = client.get("/model/status")

    assert response.status_code == 200
    body = response.json()
    assert body["ready"] is True
    assert body["configured_tier"] == "bootstrap_baseline"
    assert body["model_tier"] == "bootstrap_baseline"
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
        "_slope_segments": [
            {
                "start": {"lat": 35.11, "lng": 129.04},
                "end": {"lat": 35.12, "lng": 129.05},
                "slope_percent": 2.5,
                "distance_m": 90.0,
            }
        ],
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
    assert body["candidates"][0]["slope_segments"][0]["slope_percent"] == 2.5
    assert body["candidates"][0]["feature_snapshot"]["snapshot_kind"] == "live_route_candidate"
    trait = body["candidates"][0]["trait_labels"]
    assert trait["feature_snapshot_hash"] == body["candidates"][0]["feature_snapshot"]["feature_snapshot_hash"]
    assert "shortest" in {label["label_id"] for label in trait["labels"]}


def test_rank_candidates_uses_backend_enriched_complete_features(monkeypatch):
    class Ranker:
        received_columns = None

        def predict(self, frame):
            self.received_columns = list(frame.columns)
            return np.array([0.2, 0.8])

    ranker = Ranker()
    monkeypatch.setattr(api_router, "_rankers", {"general": ranker})
    monkeypatch.setattr(api_router, "_get_model_metadata", lambda: {
        "model_version": "bootstrap-test",
        "model_tier": "bootstrap_baseline",
        "label_origin": "bootstrap_evaluation",
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
                    "dongbaekjeon_store_count_200m": 1,
                },
            },
            {
                "route_id": "route-b",
                "features": {
                    **base,
                    "shade_ratio": 0.8,
                    "shaded_walk_m": 400,
                    "shade_building_height_coverage": 1.0,
                    "dongbaekjeon_store_count_200m": 999,
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
    assert body["metadata"]["model_tier"] == "bootstrap_baseline"
    assert "dongbaekjeon_store_count_200m" not in ranker.received_columns


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
        "dongbaekjeon_store_count_200m": 12,
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
    assert (
        afternoon_body["candidates"][0]["feature_snapshot"]["features"][
            "dongbaekjeon_store_count_200m"
        ]
        == 12
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


def test_subway_accessibility_layer_keeps_station_inventory_separate_from_route():
    class SubwayLayer:
        def iterrows(self):
            return iter([
                (0, {
                    "역명": "부산역",
                    "elevator_accessible": 1,
                    "external_ramp_count": 2,
                    "wheelchair_lift_count": 1,
                }),
                (1, {
                    "역명": "서면역",
                    "elevator_accessible": 0,
                    "external_ramp_count": 0,
                    "wheelchair_lift_count": 4,
                }),
            ])

    segments = [{
        "mode": "subway",
        "station_name": "부산역",
        "has_elevator": None,
        "needs_vertical_move": None,
    }, {
        "mode": "subway",
        "station_name": "미등록역",
        "has_elevator": None,
        "needs_vertical_move": None,
    }]

    enriched = _enrich_subway_elevator_accessibility(
        segments,
        {"subway": SubwayLayer()},
    )

    assert enriched[0]["has_elevator"] is True
    assert enriched[0]["needs_vertical_move"] is None
    assert enriched[0]["station_external_ramp_count"] == 2
    assert enriched[0]["station_wheelchair_lift_count"] == 1
    assert enriched[0]["station_ramp_route_match"] is None
    assert "부산교통공사" in enriched[0][
        "station_accessibility_evidence_source"
    ]
    assert enriched[1]["has_elevator"] is None


def test_public_segments_preserve_existing_transit_guidance_and_lookup_ids():
    point = Coordinate(35.1000, 129.0000)
    bus_raw = {
        "trafficType": 2,
        "sectionTime": 5,
        "distance": 1000,
        "startName": "부산역",
        "endName": "서면역",
        "startLocalStationID": "505780000",
        "endLocalStationID": "505780100",
        "intervalTime": 8,
        "lane": [{
            "busNo": "100",
            "busID": 123,
            "busLocalBlID": "5200100000",
        }],
    }
    subway_raw = {
        "trafficType": 1,
        "sectionTime": 10,
        "distance": 4000,
        "startName": "서면역",
        "endName": "동래역",
        "startID": 119,
        "endID": 125,
        "way": "노포",
        "wayCode": 1,
        "door": "3-2",
        "startExitNo": "8",
        "endExitNo": "1",
        "intervalTime": 6,
        "lane": [{"name": "부산 1호선", "subwayCode": 1}],
    }
    candidate = RouteCandidate(
        source="odsay",
        path=[point, Coordinate(35.1100, 129.0100)],
        duration_min=15,
        distance_m=5000,
        raw_response={
            "info": {"transferCount": 1, "totalWalk": 0},
            "subPath": [bus_raw, subway_raw],
        },
        segments=[
            {
                "mode": "bus",
                "duration_min": 5,
                "distance_m": 1000,
                "path": [],
                "raw": bus_raw,
            },
            {
                "mode": "subway",
                "duration_min": 10,
                "distance_m": 4000,
                "path": [],
                "raw": subway_raw,
            },
        ],
    )

    bus, subway = _public_segments(candidate)

    assert bus["transit_start_id"] == "505780000"
    assert bus["transit_route_id"] == "5200100000"
    assert bus["transit_interval_min"] == 8
    assert subway["transit_start_id"] == "119"
    assert subway["transit_end_id"] == "125"
    assert subway["transit_direction"] == "노포"
    assert subway["transit_direction_code"] == 1
    assert subway["fast_boarding_position"] == "3-2"
    assert subway["start_exit_no"] == "8"
    assert subway["end_exit_no"] == "1"


def test_smart_shelter_requires_same_boarding_stop_name_and_nearby_coordinate():
    point = Coordinate(35.1151, 129.0414)
    raw = {
        "trafficType": 2,
        "sectionTime": 8,
        "distance": 1500,
        "startName": "부산역 정류장",
        "endName": "서면역",
        "startX": 129.0414,
        "startY": 35.1151,
        "lane": [{"busNo": "100"}],
    }
    candidate = RouteCandidate(
        source="odsay",
        path=[point, Coordinate(35.1500, 129.0600)],
        duration_min=8,
        distance_m=1500,
        raw_response={"info": {}, "subPath": [raw]},
        segments=[{
            "mode": "bus",
            "duration_min": 8,
            "distance_m": 1500,
            "path": [],
            "raw": raw,
        }],
    )
    shelters = gpd.GeoDataFrame(
        {"정류소명": ["부산역", "다른 정류장"]},
        geometry=[
            Point(129.0414, 35.1151),
            Point(129.04141, 35.11511),
        ],
        crs="EPSG:4326",
    ).to_crs("EPSG:5179")

    segment = _public_segments(
        candidate,
        {"smart_shelter": shelters},
    )[0]

    assert segment["smart_shelter_name"] == "부산역"


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


def test_odsay_analysis_ignores_confirmed_zero_distance_walk_part():
    first = Coordinate(35.1000, 129.0000)
    second = Coordinate(35.1100, 129.0000)
    transfer = Coordinate(35.1200, 129.0000)
    candidate = MergedRoute(
        sources=["odsay"],
        source="odsay",
        path=[first, second, transfer],
        duration_min=20,
        distance_m=3000,
        segments=[
            {
                "mode": "walk",
                "path": [first, second],
                "geometry_quality": "exact",
                "duration_min": 5,
                "distance_m": 300,
            },
            {
                "mode": "walk",
                "path": [transfer, transfer],
                "geometry_quality": "exact",
                "duration_min": 0,
                "distance_m": 0,
            },
        ],
    )

    assert _analysis_route_parts(candidate) == [[
        (35.1000, 129.0000),
        (35.1100, 129.0000),
    ]]

    candidate.segments[1]["path"] = [
        transfer,
        Coordinate(35.1210, 129.0000),
    ]
    assert _analysis_route_parts(candidate) == []


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


def test_ors_and_tmap_verified_walk_analysis_uses_shared_full_path():
    path = [
        Coordinate(35.1000, 129.0000),
        Coordinate(35.1100, 129.0000),
    ]
    candidate = MergedRoute(
        sources=["tmap", "ors"],
        source="tmap",
        path=path,
        duration_min=10,
        distance_m=900,
        accessibility_evidence={
            "wheelchair_constraints_applied": True,
        },
    )

    assert _analysis_route_parts(candidate) == [[
        (35.1000, 129.0000),
        (35.1100, 129.0000),
    ]]


def test_tmap_ramp_and_stair_exclusion_evidence_reaches_public_segment():
    candidate = MergedRoute(
        sources=["tmap"],
        source="tmap",
        path=[
            Coordinate(35.1000, 129.0000),
            Coordinate(35.1100, 129.0100),
        ],
        duration_min=10,
        distance_m=900,
        raw_response={"features": []},
        accessibility_evidence={
            "provider": "TMAP pedestrian",
            "search_option": "30",
            "stairs_excluded_by_provider": True,
            "stair_feature_count": 0,
            "ramp_points": [{
                "lat": 35.105,
                "lng": 129.005,
                "turn_type": 129,
                "replaces_stairs": True,
            }],
        },
    )

    features = _parse_api_features(candidate)
    segment = _public_segments(candidate)[0]

    assert features["stair_count"] is None
    assert segment["has_stairs"] is None
    assert segment["stairs_count"] is None
    assert segment["stairs_excluded_by_provider"] is True
    assert segment["has_slope"] is True
    assert segment["ramp_points"] == [{"lat": 35.105, "lng": 129.005}]
    assert segment["ramp_replaces_stairs"] is True
    assert segment["ramp_evidence_source"] == "TMAP pedestrian turnType 128/129"
    assert segment["needs_vertical_move"] is True


def test_combined_ors_constraints_and_tmap_ramp_reach_public_segment():
    candidate = MergedRoute(
        sources=["tmap", "ors"],
        source="tmap",
        path=[
            Coordinate(35.1000, 129.0000),
            Coordinate(35.1100, 129.0100),
        ],
        duration_min=10,
        distance_m=900,
        raw_response={"features": []},
        accessibility_evidence={
            "providers": [
                "TMAP pedestrian",
                "openrouteservice wheelchair",
            ],
            "stairs_excluded_by_provider": True,
            "stair_feature_count": 0,
            "ramp_points": [{
                "lat": 35.105,
                "lng": 129.005,
                "turn_type": 129,
                "replaces_stairs": True,
            }],
            "wheelchair_constraints_applied": True,
            "wheelchair_restrictions": WHEELCHAIR_RESTRICTIONS,
            "wheelchair_data_limitations": ["OSM 태그 누락 가능"],
            "wheelchair_constraint_categories": [
                "steps", "surface", "width", "wheelchair_access"
            ],
            "verified_extra_response_keys": {
                "steepness": "steepness",
                "suitability": "suitability",
                "surface": "surface",
                "waytype": "waytypes",
                "osmid": "osmId",
            },
            "extra_info_full_route_coverage": True,
        },
    )

    segment = _public_segments(candidate)[0]

    assert _wheelchair_candidate_constrained(candidate) is True
    assert segment["ramp_points"] == [{"lat": 35.105, "lng": 129.005}]
    assert segment["wheelchair_constraints_applied"] is True
    assert segment["wheelchair_constraint_source"] == (
        "openrouteservice wheelchair profile"
    )
    assert segment["wheelchair_restrictions"] == WHEELCHAIR_RESTRICTIONS
    assert segment["wheelchair_data_limitations"] == ["OSM 태그 누락 가능"]
    assert segment["wheelchair_constraint_categories"] == [
        "steps", "surface", "width", "wheelchair_access"
    ]
    assert segment["wheelchair_extra_info_full_route_coverage"] is True
    assert segment["wheelchair_extra_response_keys"]["osmid"] == "osmId"


def test_wheelchair_collection_fails_instead_of_using_tmap_without_ors(
    monkeypatch,
):
    route = RouteCandidate(
        source="tmap",
        path=[Coordinate(35.10, 129.00), Coordinate(35.11, 129.01)],
        duration_min=10,
        distance_m=900,
        accessibility_evidence={
            "stairs_excluded_by_provider": True,
            "stair_feature_count": 0,
        },
    )

    async def odsay_collect(_self, *_args, **_kwargs):
        return []

    async def tmap_collect(_self, *_args, **_kwargs):
        return [route]

    async def ors_collect(_self, *_args, **_kwargs):
        raise CollectorNotConfigured("ORS_API_KEY가 설정되지 않았습니다.")

    monkeypatch.setattr(OdsayRouteCollector, "collect", odsay_collect)
    monkeypatch.setattr(TmapRouteCollector, "collect", tmap_collect)
    monkeypatch.setattr(OrsWheelchairRouteCollector, "collect", ors_collect)
    request = RecommendRequest(
        origin_lat=35.10,
        origin_lng=129.00,
        origin_name="출발",
        dest_lat=35.11,
        dest_lng=129.01,
        dest_name="도착",
        profile="disabled",
        uses_wheelchair=True,
    )

    with pytest.raises(HTTPException) as captured:
        asyncio.run(_collect_static_featured_routes(request))

    assert captured.value.status_code == 503
    assert captured.value.detail["required_source"] == (
        "openrouteservice wheelchair"
    )


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

    async def collect_odsay(self, origin, destination, **_kwargs):
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


def test_labeling_candidates_rejects_over_limit_top_n(monkeypatch):
    """상한을 넘는 후보 수 요청은 조용한 절단 대신 명시적 422다."""
    from config import settings as ai_settings

    monkeypatch.setattr(ai_settings, "ODSAY_MAX_CANDIDATES", 5)
    response = client.post("/labeling/candidates", json={
        "origin_lat": 35.1151, "origin_lng": 129.0414, "origin_name": "부산역",
        "dest_lat": 35.1972, "dest_lng": 128.9902, "dest_name": "북구청",
        "profile": "general",
        "candidate_limit": 7,
    })

    assert response.status_code == 422
    assert "상한" in response.json()["detail"]


def test_refine_transit_endpoint_returns_exact_lane_paths(monkeypatch):
    async def fake_refine(self, map_object, origin, destination):
        assert map_object == "100:1:1:2"
        return [[
            Coordinate(lat=35.115, lng=129.04),
            Coordinate(lat=35.157, lng=129.059),
        ]]

    monkeypatch.setattr(
        api_router.OdsayRouteCollector,
        "refine_transit",
        fake_refine,
    )
    response = client.post("/routes/refine-transit", json={
        "origin_lat": 35.1151,
        "origin_lng": 129.0414,
        "dest_lat": 35.1972,
        "dest_lng": 128.9902,
        "map_object": "100:1:1:2",
    })

    assert response.status_code == 200
    body = response.json()
    assert body["geometry_quality"] == "exact"
    assert body["lane_paths"] == [[
        {"lat": 35.115, "lng": 129.04},
        {"lat": 35.157, "lng": 129.059},
    ]]
    assert body["refined_at"]


def test_refine_transit_endpoint_keeps_provider_failure_explicit(monkeypatch):
    from collectors.base import CollectorError as AiCollectorError

    async def fail_refine(self, map_object, origin, destination):
        raise AiCollectorError("ODsay loadLane 실패: quota exceeded")

    monkeypatch.setattr(
        api_router.OdsayRouteCollector,
        "refine_transit",
        fail_refine,
    )
    response = client.post("/routes/refine-transit", json={
        "origin_lat": 35.1151,
        "origin_lng": 129.0414,
        "dest_lat": 35.1972,
        "dest_lng": 128.9902,
        "map_object": "100:1:1:2",
    })

    assert response.status_code == 502
    detail = response.json()["detail"]
    # 오류 분류는 문자열 검색이 아니라 구조화된 code로 전달한다.
    assert "quota" in detail["message"]
    assert detail["code"] == "provider_error"
    assert detail["retryable"] is True


def _lazy_route_feature(transit_path, *, bus_name="100", quality="estimated"):
    walk_path = [
        {"lat": 35.1151, "lng": 129.0414},
        {"lat": 35.1160, "lng": 129.0420},
    ]
    return {
        "_sources": ["odsay"],
        "_path": [*walk_path, *transit_path],
        "_segments": [
            {
                "mode": "walk",
                "description": "보행 이동",
                "distance_m": 120,
                "path": walk_path,
                "geometry_quality": "exact",
            },
            {
                "mode": "bus",
                "description": f"{bus_name} · 부산역 → 서면역",
                "bus_route_name": bus_name,
                "station_name": None,
                "distance_m": 4900,
                "path": transit_path,
                "geometry_quality": quality,
            },
        ],
    }


def test_route_id_is_stable_across_transit_refinement():
    """정밀화 전(정류장 추정선)과 후(도로 선형)의 route ID가 같아야 한다."""
    estimated = _lazy_route_feature([
        {"lat": 35.1160, "lng": 129.0420},
        {"lat": 35.1400, "lng": 129.0500},
        {"lat": 35.1570, "lng": 129.0590},
    ])
    refined = _lazy_route_feature(
        [
            {"lat": 35.1160, "lng": 129.0420},
            {"lat": 35.1201, "lng": 129.0433},
            {"lat": 35.1298, "lng": 129.0461},
            {"lat": 35.1405, "lng": 129.0502},
            {"lat": 35.1570, "lng": 129.0590},
        ],
        quality="exact",
    )

    assert api_router._route_id(estimated) == api_router._route_id(refined)


def test_route_id_distinguishes_different_lanes_and_stops():
    base = _lazy_route_feature([
        {"lat": 35.1160, "lng": 129.0420},
        {"lat": 35.1570, "lng": 129.0590},
    ])
    other_lane = _lazy_route_feature(
        [
            {"lat": 35.1160, "lng": 129.0420},
            {"lat": 35.1570, "lng": 129.0590},
        ],
        bus_name="200",
    )
    other_stops = _lazy_route_feature([
        {"lat": 35.1160, "lng": 129.0420},
        {"lat": 35.1570, "lng": 129.0590},
    ])
    other_stops["_segments"][1]["description"] = "100 · 부산역 → 양정역"

    assert api_router._route_id(base) != api_router._route_id(other_lane)
    assert api_router._route_id(base) != api_router._route_id(other_stops)
