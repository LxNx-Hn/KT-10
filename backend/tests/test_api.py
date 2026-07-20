"""REST API 스모크 테스트 (FastAPI TestClient). camelCase JSON 호환성 포함."""
import pytest
from fastapi.testclient import TestClient

from app.data.places import find_place
from app.main import app
from app.settings import settings

client = TestClient(app)


@pytest.fixture(autouse=True)
def _isolated_demo_sources(monkeypatch):
    """개발자 로컬 .env 유무와 무관하게 고정 데모 계약만 검증한다."""
    for field in (
        "ai_server_url", "odsay_api_key", "kakao_rest_api_key",
        "openweather_api_key", "bus_service_key",
    ):
        monkeypatch.setattr(settings, field, "")


def _place_payload(place_id: str) -> dict:
    p = find_place(place_id)
    assert p is not None
    return p.model_dump(by_alias=True)


def test_health():
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


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


def test_routes_recommend_disabled():
    body = {
        "origin": _place_payload("gu-office"),
        "destination": _place_payload("seomyeon-stn"),
        "profile": "disabled",
        "weatherScenario": "normal",
        "options": {"lowFloorPriority": False},
        "topN": 3,
    }
    r = client.post("/api/routes/recommend", json=body)
    assert r.status_code == 200
    results = r.json()
    assert len(results) == 3
    # 장애인: 계단 육교 경로는 상위 3개에서 제외
    assert "r1-overpass" not in [x["route"]["id"] for x in results]
    # camelCase 점수 필드
    assert "finalScore" in results[0]["score"]
    assert "lowFloorStatus" in results[0]["score"]
