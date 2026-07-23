"""REST API 스모크 테스트 (FastAPI TestClient). camelCase JSON 호환성 포함."""
import asyncio

import pytest
from fastapi.testclient import TestClient

from app.data.places import find_place
from app.data.routes import demo_candidates
from app.main import _add_configured_shade, app
from app.settings import settings

client = TestClient(app)


@pytest.fixture(autouse=True)
def _isolated_demo_sources(monkeypatch):
    """개발자 로컬 .env 유무와 무관하게 고정 데모 계약만 검증한다."""
    for field in (
        "ai_server_url", "odsay_api_key", "kakao_rest_api_key",
        "openweather_api_key", "bus_service_key", "vworld_api_key",
    ):
        monkeypatch.setattr(settings, field, "")
    monkeypatch.setattr(settings, "route_mode", "demo")
    monkeypatch.setattr(settings, "building_source", "demo")


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


def test_places_search():
    r = client.get("/api/places/search", params={"q": "서면"})
    assert r.status_code == 200
    names = [p["name"] for p in r.json()]
    assert "서면역" in names


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


def test_synthetic_buildings_are_not_applied_to_live_routes(monkeypatch):
    monkeypatch.setattr(settings, "route_mode", "live")
    monkeypatch.setattr(settings, "building_source", "demo")
    routes = asyncio.run(_add_configured_shade(demo_candidates()))
    assert all(route.shade is None for route in routes)
    assert settings.active_sources()["buildings"] == "synthetic-demo(inactive-outside-demo)"


def test_routes_recommend_returns_rule_characteristics_and_shade():
    body = {
        "origin": _place_payload("gu-office"),
        "destination": _place_payload("seomyeon-stn"),
        "profile": "disabled",
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
    characteristics = {
        characteristic
        for result in results
        for characteristic in result["route"]["characteristics"]
    }
    assert characteristics == {"fastest", "lowest_slope", "most_shade"}
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
    assert "lowFloorStatus" in results[0]["score"]
