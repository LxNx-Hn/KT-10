"""REST API 스모크 테스트 (FastAPI TestClient). camelCase JSON 호환성 포함."""
import asyncio
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

import app.main as app_main
from app.data.places import find_place
from app.data.routes import demo_candidates
from app.data.weather import WEATHER_SCENARIOS
from app.main import _add_configured_shade, app
from app.providers.ai_pipeline import EnrichedCandidateBundle
from app.route_set_cache import route_set_cache
from app.settings import settings

client = TestClient(app)


@pytest.fixture(autouse=True)
def _isolated_demo_sources(monkeypatch):
    """개발자 로컬 .env 유무와 무관하게 고정 데모 계약만 검증한다."""
    for field in (
        "ai_server_url", "odsay_api_key", "kakao_rest_api_key",
        "openweather_api_key", "bus_service_key", "vworld_api_key",
        "labeling_api_token",
    ):
        monkeypatch.setattr(settings, field, "")
    monkeypatch.setattr(settings, "route_mode", "demo")
    monkeypatch.setattr(settings, "building_source", "demo")
    route_set_cache.clear()


def _place_payload(place_id: str) -> dict:
    p = find_place(place_id)
    assert p is not None
    return p.model_dump(by_alias=True)


def test_health():
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_readiness_reports_missing_configuration_without_secret_values():
    response = client.get("/api/readiness")
    assert response.status_code == 200
    body = response.json()
    assert body["ready"] is False
    assert body["checks"]["live_route_candidates"] is False
    assert "live_route_candidates" in body["missing"]
    serialized = response.text
    assert "SESSION_SECRET" not in serialized
    assert "ODSAY_API_KEY" not in serialized


def test_cors_preflight_allows_profile_update_from_frontend():
    response = client.options(
        "/api/me/preferences",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "PUT",
        },
    )
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"
    assert "PUT" in response.headers["access-control-allow-methods"]


def test_guest_auth_probe_is_no_content_instead_of_console_error():
    response = client.get("/api/auth/me")
    assert response.status_code == 204
    assert response.content == b""


def test_places_search():
    r = client.get(
        "/api/places/search",
        params={"q": "서면"},
        headers={"Origin": "http://localhost:5173"},
    )
    assert r.status_code == 200
    assert r.headers["X-Place-Search-Source"] == "demo"
    assert "x-place-search-source" in r.headers["access-control-expose-headers"].lower()
    names = [p["name"] for p in r.json()]
    assert "서면역" in names


def test_external_lookup_inputs_have_bounded_lengths():
    assert client.get(
        "/api/places/search",
        params={"q": "가" * 101},
    ).status_code == 422
    assert client.get(
        "/api/bus/stops",
        params={"q": "가" * 101},
    ).status_code == 422
    assert client.get(
        "/api/bus/arrivals/" + "1" * 65,
    ).status_code == 422


def test_weather_scenario_camel_case():
    r = client.get("/api/weather", params={"scenario": "heatwave"})
    assert r.status_code == 200
    body = r.json()
    assert body["isHeatwave"] is True  # camelCase alias 확인
    assert body["feelsLikeC"] == 39


def test_weather_unknown_scenario():
    assert client.get("/api/weather", params={"scenario": "nope"}).status_code == 400


def test_bus_stops_and_arrivals():
    stops = client.get("/api/bus/stops").json()
    assert any(s["stopId"] == "stop-gu-office" for s in stops)

    arr = client.get("/api/bus/arrivals/stop-gu-office")
    assert arr.status_code == 200
    buses = arr.json()["arrivals"]
    bus81 = next(b for b in buses if b["routeName"] == "81")
    assert bus81["isLowFloor"] is True
    # 미확인(None)은 응답에서 제외됨
    bus54 = next(b for b in buses if b["routeName"] == "54")
    assert "isLowFloor" not in bus54

    assert client.get("/api/bus/arrivals/nope").status_code == 404


def test_routes_candidates_demo_od():
    body = {
        "origin": _place_payload("gu-office"),
        "destination": _place_payload("seomyeon-stn"),
    }
    r = client.post("/api/routes/candidates", json=body)
    assert r.status_code == 200
    ids = [c["id"] for c in r.json()]
    assert ids == ["r1-overpass", "r2-subway", "r3-lowfloor", "r4-regularbus"]


def test_routes_candidates_rejects_outside_busan():
    body = {
        "origin": {"id": "seoul", "name": "서울역", "lat": 37.5547, "lng": 126.9707},
        "destination": _place_payload("seomyeon-stn"),
    }
    assert client.post("/api/routes/candidates", json=body).status_code == 422


def test_live_mode_missing_pipeline_does_not_silently_fall_back(monkeypatch):
    monkeypatch.setattr(settings, "route_mode", "live")
    monkeypatch.setattr(settings, "ai_server_url", "")
    body = {
        "origin": _place_payload("gu-office"),
        "destination": _place_payload("seomyeon-stn"),
    }
    response = client.post("/api/routes/candidates", json=body)
    assert response.status_code == 503
    assert "AI_SERVER_URL" in response.json()["detail"]


def test_vworld_mode_missing_key_does_not_silently_fall_back(monkeypatch):
    monkeypatch.setattr(settings, "building_source", "vworld")
    body = {
        "origin": _place_payload("gu-office"),
        "destination": _place_payload("seomyeon-stn"),
    }
    response = client.post("/api/routes/candidates", json=body)
    assert response.status_code == 503
    assert "VWORLD_API_KEY" in response.json()["detail"]


def test_explicit_demo_buildings_remain_labeled_when_used_with_live_routes(monkeypatch):
    monkeypatch.setattr(settings, "route_mode", "live")
    monkeypatch.setattr(settings, "building_source", "demo")
    routes = asyncio.run(_add_configured_shade(
        demo_candidates(),
        datetime(2026, 7, 24, 14, 0, tzinfo=ZoneInfo("Asia/Seoul")),
    ))
    assert all(route.shade is not None for route in routes)
    assert all(route.shade.status == "estimated_demo" for route in routes)
    assert all(route.shade.data_quality == "demo" for route in routes)
    assert settings.active_sources()["buildings"] == "synthetic-demo"


def test_labeling_shade_can_wait_for_complete_vworld_corridor(monkeypatch):
    monkeypatch.setattr(settings, "building_source", "vworld")
    monkeypatch.setattr(settings, "vworld_api_key", "configured")
    wait_values = []

    async def fake_buildings(
        _routes,
        *,
        wait_for_complete=False,
        cache_only=False,
    ):
        wait_values.append(wait_for_complete)
        assert cache_only is False
        return {
            "source": "test-buildings",
            "dataQuality": "demo",
            "buildings": [],
        }

    monkeypatch.setattr(app_main, "get_vworld_buildings", fake_buildings)

    asyncio.run(_add_configured_shade(
        demo_candidates(),
        datetime(2026, 7, 24, 14, 0, tzinfo=ZoneInfo("Asia/Seoul")),
        wait_for_buildings=True,
    ))

    assert wait_values == [True]


def test_vworld_night_skips_building_lookup(monkeypatch):
    monkeypatch.setattr(settings, "building_source", "vworld")
    monkeypatch.setattr(settings, "vworld_api_key", "configured")
    calls = []

    async def fail_if_called(*_args, **_kwargs):
        calls.append(True)
        raise AssertionError("야간에는 VWorld 건물 조회를 호출하면 안 됩니다.")

    monkeypatch.setattr(app_main, "get_vworld_buildings", fail_if_called)
    routes = asyncio.run(_add_configured_shade(
        demo_candidates(),
        datetime(2026, 7, 24, 2, 0, tzinfo=ZoneInfo("Asia/Seoul")),
    ))

    assert calls == []
    assert all(route.shade is not None for route in routes)
    assert all(route.shade.status == "not_daylight" for route in routes)
    assert all(route.shade.shadow_polygons == [] for route in routes)


def test_time_refresh_reuses_server_candidates_without_route_collection(monkeypatch):
    request = {
        "origin": _place_payload("gu-office"),
        "destination": _place_payload("seomyeon-stn"),
        "profile": "general",
        "weatherScenario": "normal",
        "options": {"departureAt": "2026-07-24T14:00:00+09:00"},
        "topN": 3,
    }
    initial = client.post("/api/routes/recommend", json=request)
    assert initial.status_code == 200
    initial_results = initial.json()
    token = initial_results[0]["routeSetToken"]
    assert token
    assert all(item["routeSetToken"] == token for item in initial_results)

    def fail_if_called(*_args, **_kwargs):
        raise AssertionError("시간 변경 시 경로 후보를 다시 수집하면 안 됩니다.")

    monkeypatch.setattr(app_main, "get_route_candidates", fail_if_called)
    refreshed = client.post("/api/routes/refresh-shade", json={
        "routeSetToken": token,
        "profile": "general",
        "options": {"departureAt": "2026-07-24T02:00:00+09:00"},
        "topN": 3,
    })

    assert refreshed.status_code == 200
    refreshed_results = refreshed.json()
    assert len(refreshed_results) == 3
    assert all(
        item["route"]["shade"]["status"] == "not_daylight"
        for item in refreshed_results
    )
    assert all(item["routeSetToken"] == token for item in refreshed_results)


@pytest.mark.parametrize(
    "profile",
    ["general", "elderly", "child", "youth", "disabled", "pregnant"],
)
def test_routes_recommend_returns_score_ranked_traits_and_shade(profile):
    body = {
        "origin": _place_payload("gu-office"),
        "destination": _place_payload("seomyeon-stn"),
        "profile": profile,
        "weatherScenario": "normal",
        "options": {
            "lowFloorPriority": False,
            "departureAt": "2026-07-23T14:00:00+09:00",
        },
        "topN": 3,
    }
    r = client.post("/api/routes/recommend", json=body)
    assert r.status_code == 200
    results = r.json()
    assert len(results) == 3
    scores = [result["score"]["finalScore"] for result in results]
    assert scores == sorted(scores, reverse=True)
    assert any(result["route"]["characteristics"] for result in results)
    assert all(result["route"]["shade"]["status"] == "estimated_demo" for result in results)
    assert all(
        0 <= result["route"]["shade"]["shadeRatio"] <= 1
        for result in results
    )
    assert all(
        result["route"]["shade"]["dataQuality"] == "demo"
        for result in results
    )
    # camelCase 점수 필드
    assert "finalScore" in results[0]["score"]
    assert results[0]["score"]["scoreKind"] == "rule_baseline"
    assert "lowFloorStatus" in results[0]["score"]


def test_routes_recommend_accepts_new_trip_conditions():
    body = {
        "origin": _place_payload("gu-office"),
        "destination": _place_payload("seomyeon-stn"),
        "profile": "pregnant",
        "weatherScenario": "normal",
        "options": {
            "carryLuggage": True,
            "stroller": True,
            "avoidStairs": True,
            "shadePriority": True,
            "lowFloorPriority": True,
            "minimizeTransfers": True,
            "departureAt": "2026-07-23T14:00:00+09:00",
        },
        "topN": 3,
    }
    response = client.post("/api/routes/recommend", json=body)
    assert response.status_code == 200
    assert len(response.json()) == 3


def test_labeling_candidates_requires_explicit_ai_mode():
    settings.labeling_api_token = "test-labeling-token-" + "x" * 32
    body = {
        "origin": _place_payload("gu-office"),
        "destination": _place_payload("seomyeon-stn"),
        "profile": "general",
        "weatherScenario": "normal",
    }
    response = client.post(
        "/api/routes/labeling-candidates",
        json=body,
        headers={"X-Labeling-Token": settings.labeling_api_token},
    )
    assert response.status_code == 503
    assert "ROUTE_MODE=ai" in response.json()["detail"]


def test_labeling_candidates_uses_weather_shade_and_enriched_provenance(
    monkeypatch,
):
    monkeypatch.setattr(settings, "route_mode", "ai")
    monkeypatch.setattr(settings, "ai_server_url", "http://ai.test")
    monkeypatch.setattr(settings, "building_source", "demo")
    monkeypatch.setattr(
        settings,
        "labeling_api_token",
        "test-labeling-token-" + "x" * 32,
    )

    async def fake_weather(_scenario):
        return WEATHER_SCENARIOS["normal"]

    async def fake_candidates(*_args, **_kwargs):
        routes = demo_candidates()[:2]
        for route in routes:
            route.model_group_id = "source-group"
            route.model_snapshot_hash = "a" * 64
            route.model_features = {"total_duration_min": route.total_duration_min}
        return routes

    async def fake_enrich(routes, _options):
        evaluated_at = routes[0].shade.evaluated_at.isoformat()
        assert all(
            route.shade.evaluated_at.isoformat() == evaluated_at
            for route in routes
        )
        snapshots = {}
        traits = {}
        for index, route in enumerate(routes):
            route.model_features = {
                "total_duration_min": route.total_duration_min,
                "shade_ratio": route.shade.shade_ratio,
            }
            snapshot_hash = f"{index + 1:064x}"
            snapshots[route.id] = {
                "snapshot_schema_version": "route-feature-snapshot-v2",
                "snapshot_kind": "live_route_candidate",
                "captured_at": evaluated_at,
                "group_id": "enriched-group",
                "route_id": route.id,
                "sources": [*route.sources, "demo-buildings-v1"],
                "geometry_quality": route.geometry_quality,
                "features": route.model_features,
                "feature_snapshot_hash": snapshot_hash,
            }
            traits[route.id] = {
                "schema_version": "route-traits-v1",
                "group_id": "enriched-group",
                "route_id": route.id,
                "feature_snapshot_hash": snapshot_hash,
                "labels": [],
            }
        return EnrichedCandidateBundle(
            group_id="enriched-group",
            captured_at="2026-07-24T04:00:00+00:00",
            shade_evaluated_at=evaluated_at,
            snapshots=snapshots,
            traits=traits,
        )

    monkeypatch.setattr(app_main, "get_current_weather", fake_weather)
    monkeypatch.setattr(app_main, "get_ai_pipeline_candidates", fake_candidates)
    monkeypatch.setattr(app_main, "enrich_ai_pipeline_candidates", fake_enrich)
    body = {
        "origin": _place_payload("gu-office"),
        "destination": _place_payload("seomyeon-stn"),
        "profile": "general",
        "weatherScenario": "normal",
        "options": {
            "shadePriority": True,
            "departureAt": "2026-07-24T14:00:00+09:00",
        },
    }

    response = client.post(
        "/api/routes/labeling-candidates",
        json=body,
        headers={"X-Labeling-Token": settings.labeling_api_token},
    )

    assert response.status_code == 200
    result = response.json()
    assert result["group_id"] == "enriched-group"
    assert len(result["candidates"]) == 2
    assert all(
        row["feature_snapshot"]["group_id"] == "enriched-group"
        and row["feature_snapshot"]["features"]["shade_ratio"] is not None
        and row["trait_labels"]["feature_snapshot_hash"]
        == row["feature_snapshot"]["feature_snapshot_hash"]
        for row in result["candidates"]
    )


def test_labeling_candidates_rejects_missing_batch_token(monkeypatch):
    monkeypatch.setattr(settings, "route_mode", "ai")
    monkeypatch.setattr(settings, "ai_server_url", "http://ai.test")
    monkeypatch.setattr(
        settings,
        "labeling_api_token",
        "test-labeling-token-" + "x" * 32,
    )
    body = {
        "origin": _place_payload("gu-office"),
        "destination": _place_payload("seomyeon-stn"),
        "profile": "general",
        "weatherScenario": "normal",
    }

    response = client.post("/api/routes/labeling-candidates", json=body)

    assert response.status_code == 403
