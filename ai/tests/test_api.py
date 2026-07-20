"""AI API의 모델 준비 상태와 부산 범위 계약 테스트."""
from fastapi.testclient import TestClient

import api.router as api_router
from main import app
from scoring.train import ModelNotReady


client = TestClient(app)


def test_model_status_reports_not_ready_without_fabricated_model(monkeypatch):
    monkeypatch.setattr(api_router, "_rankers", None)
    monkeypatch.setattr(api_router, "load_rankers", lambda: (_ for _ in ()).throw(ModelNotReady("라벨 필요")))
    response = client.get("/model/status")
    assert response.status_code == 200
    assert response.json() == {"ready": False, "profiles": [], "detail": "라벨 필요"}


def test_recommend_refuses_when_human_model_is_missing(monkeypatch):
    monkeypatch.setattr(api_router, "_rankers", None)
    monkeypatch.setattr(api_router, "load_rankers", lambda: (_ for _ in ()).throw(ModelNotReady("라벨 필요")))
    response = client.post("/recommend", json={
        "origin_lat": 35.115, "origin_lng": 129.04, "origin_name": "부산역",
        "dest_lat": 35.157, "dest_lng": 129.059, "dest_name": "서면역",
        "profile": "general",
    })
    assert response.status_code == 503
    assert response.json()["detail"] == "라벨 필요"


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
