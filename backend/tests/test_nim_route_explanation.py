"""NIM 경로 설명은 서버 캐시 경로 사실만 사용한다."""
import asyncio

from fastapi.testclient import TestClient

import app.main as main
from app.models import (
    RouteCandidate,
    RouteScore,
    RouteSegment,
    ScoreComponents,
    ScoreDisplay,
    ScoredRoute,
    WeatherCondition,
)
from app.providers.nim import (
    NimExplanationError,
    _route_facts,
    enrich_voice_summaries,
)
from app.route_set_cache import route_set_cache


def _candidate() -> RouteCandidate:
    return RouteCandidate(
        id="route-nim-1",
        summary="도보 이동",
        origin="출발지",
        destination="도착지",
        segments=[RouteSegment(id="walk-1", mode="walk", description="도보 이동", duration_min=8)],
        total_duration_min=20,
        total_walk_m=500,
        transfer_count=0,
        geometry_quality="exact",
    )


def _weather() -> WeatherCondition:
    return WeatherCondition(
        label="맑음", temp_c=20, feels_like_c=20, precipitation_mm=0,
        wind_ms=1, pm10=20, sky="clear", air="good",
    )


def test_explain_route_uses_cached_candidate_and_nim(monkeypatch):
    candidate = _candidate()
    token = route_set_cache.put([candidate], _weather())

    async def fake_explain(cached: RouteCandidate) -> str:
        assert cached.id == candidate.id
        return "출발지에서 도착지까지 20분, 도보 500미터 이동합니다."

    monkeypatch.setattr(main, "explain_route", fake_explain)
    with TestClient(main.app) as client:
        response = client.post("/api/routes/explain", json={"routeSetToken": token, "routeId": candidate.id})

    assert response.status_code == 200
    assert response.json() == {
        "routeId": candidate.id,
        "explanation": "출발지에서 도착지까지 20분, 도보 500미터 이동합니다.",
        "provider": "nvidia_nim",
    }


def test_explain_route_rejects_expired_or_unknown_candidate():
    with TestClient(main.app) as client:
        expired = client.post("/api/routes/explain", json={"routeSetToken": "x" * 24, "routeId": "route-x"})
    assert expired.status_code == 409

    token = route_set_cache.put([_candidate()], _weather())
    with TestClient(main.app) as client:
        unknown = client.post("/api/routes/explain", json={"routeSetToken": token, "routeId": "route-x"})
    assert unknown.status_code == 404


def _scored() -> ScoredRoute:
    candidate = _candidate()
    return ScoredRoute(
        route=candidate,
        score=RouteScore(
            route_id=candidate.id,
            components=ScoreComponents(),
            display=ScoreDisplay(),
            final_score=80,
            low_floor_status="unknown",
            reasons=[],
            cautions=[],
            voice_summary="규칙 기반 안내",
            score_kind="bootstrap_baseline",
        ),
    )


def test_voice_summary_uses_nim_when_available(monkeypatch):
    async def fake_explain(route: RouteCandidate) -> str:
        return f"{route.id} NIM 안내"

    monkeypatch.setattr("app.providers.nim.explain_route", fake_explain)
    monkeypatch.setattr(main.settings, "nvidia_api_key", "key")
    monkeypatch.setattr(main.settings, "nim_model", "model")

    result = asyncio.run(enrich_voice_summaries([_scored()]))

    assert result[0].score.voice_summary == "route-nim-1 NIM 안내"


def test_voice_summary_keeps_rule_summary_when_nim_fails(monkeypatch):
    async def failed_explain(_route: RouteCandidate) -> str:
        raise NimExplanationError("provider failure")

    monkeypatch.setattr("app.providers.nim.explain_route", failed_explain)
    monkeypatch.setattr(main.settings, "nvidia_api_key", "key")
    monkeypatch.setattr(main.settings, "nim_model", "model")

    result = asyncio.run(enrich_voice_summaries([_scored()]))

    assert result[0].score.voice_summary == "규칙 기반 안내"


def test_route_facts_keep_segment_distance_and_truthful_ramp_scope():
    candidate = _candidate().model_copy(update={
        "segments": [
            RouteSegment(
                id="walk-ramp",
                mode="walk",
                description="경사로가 확인된 보행 구간",
                duration_min=6,
                distance_m=180,
                has_slope=True,
                ramp_points=[{"lat": 35.1, "lng": 129.0}],
                ramp_replaces_stairs=True,
                ramp_evidence_source="TMAP pedestrian turnType 128/129",
            ),
            RouteSegment(
                id="station-inventory",
                mode="subway",
                description="도시철도 이동",
                duration_min=10,
                station_external_ramp_count=2,
                station_accessibility_evidence_source="부산교통공사",
                station_ramp_route_match=None,
            ),
        ],
    })

    facts = _route_facts(candidate)

    assert facts["segments"][0]["distanceM"] == 180
    assert facts["segments"][0]["physicalRampPointCount"] == 1
    assert facts["segments"][0]["physicalRampReplacesStairs"] is True
    assert facts["segments"][1]["stationExternalRampInventoryCount"] == 2
    assert facts["segments"][1]["stationRampMatchedToThisRoute"] is False
