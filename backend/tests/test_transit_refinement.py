"""후보 선택 대중교통 정밀화·topN 권위·route-set 동시성 회귀 테스트."""
import asyncio
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import app.main as app_main
import pytest
from app.data.places import find_place
from app.data.weather import WEATHER_SCENARIOS
from app.main import _effective_top_n, _shade_gate_reason, app
from app.models import (
    LatLng,
    RouteCandidate,
    RouteSegment,
    WeatherCondition,
)
from app.providers.ai_pipeline import (
    AIProviderError,
    apply_refined_transit_geometry,
    refine_candidate_transit,
)
from app.route_set_cache import (
    StaleRouteSetRevision,
    route_set_cache,
)
from app.settings import settings
from fastapi.testclient import TestClient

client = TestClient(app)
KST = ZoneInfo("Asia/Seoul")


@pytest.fixture(autouse=True)
def _isolated_demo_sources(monkeypatch):
    for field in (
        "ai_server_url", "odsay_api_key", "kakao_rest_api_key",
        "openweather_api_key", "bus_service_key", "vworld_api_key",
    ):
        monkeypatch.setattr(settings, field, "")
    monkeypatch.setattr(settings, "route_mode", "demo")
    monkeypatch.setattr(settings, "building_source", "demo")
    route_set_cache.clear()


def _walk_segment(identifier: str) -> RouteSegment:
    return RouteSegment(
        id=identifier,
        mode="walk",
        description="보행 이동",
        duration_min=4,
        distance_m=250,
        path=[
            LatLng(lat=35.1151, lng=129.0414),
            LatLng(lat=35.1162, lng=129.0425),
        ],
        geometry_quality="exact",
    )


def _bus_segment(identifier: str, *, quality: str) -> RouteSegment:
    return RouteSegment(
        id=identifier,
        mode="bus",
        description="100 · 부산역 → 서면역",
        duration_min=18,
        distance_m=4900,
        bus_route_name="100",
        path=[
            LatLng(lat=35.1162, lng=129.0425),
            LatLng(lat=35.1570, lng=129.0590),
        ],
        geometry_quality=quality,
    )


def _candidate(route_id: str, *, refined: bool) -> RouteCandidate:
    return RouteCandidate(
        id=route_id,
        summary="100번 버스 + 도보",
        origin="부산역",
        destination="서면역",
        segments=[
            _walk_segment(f"{route_id}-walk"),
            _bus_segment(
                f"{route_id}-bus",
                quality="exact" if refined else "estimated",
            ),
        ],
        total_duration_min=22,
        total_walk_m=250,
        transfer_count=0,
        path=[
            LatLng(lat=35.1151, lng=129.0414),
            LatLng(lat=35.1162, lng=129.0425),
            LatLng(lat=35.1570, lng=129.0590),
        ],
        sources=["odsay"],
        geometry_quality="exact" if refined else "mixed",
        transit_refinement=None if refined else {
            "provider": "odsay",
            "map_object": "100:1:1:2",
            "origin": {"lat": 35.1151, "lng": 129.0414},
            "destination": {"lat": 35.1972, "lng": 128.9902},
        },
        transit_refinement_state="exact" if refined else "not_loaded",
    )


def _weather() -> WeatherCondition:
    return WEATHER_SCENARIOS["normal"].model_copy(deep=True)


def _seed_route_set(candidates: list[RouteCandidate]) -> str:
    return route_set_cache.put(
        candidates,
        _weather(),
        metadata={
            "originalRequestedTopN": None,
            "effectiveTopN": len(candidates),
            "collectedCandidateCount": len(candidates),
        },
    )


def test_effective_top_n_uses_operator_default_only_when_absent(monkeypatch):
    monkeypatch.setattr(settings, "route_default_top_n", 7)
    assert _effective_top_n(None) == 7
    assert _effective_top_n(3) == 3


def test_recommend_without_top_n_uses_env_default(monkeypatch):
    monkeypatch.setattr(settings, "route_default_top_n", 2)
    body = {
        "origin": find_place("gu-office").model_dump(by_alias=True),
        "destination": find_place("seomyeon-stn").model_dump(by_alias=True),
        "profile": "general",
        "weatherScenario": "normal",
        "options": {"departureAt": "2026-07-24T14:00:00+09:00"},
    }
    response = client.post("/api/routes/recommend", json=body)
    assert response.status_code == 200
    assert len(response.json()) == 2


def test_recommend_rejects_top_n_above_absolute_limit():
    body = {
        "origin": find_place("gu-office").model_dump(by_alias=True),
        "destination": find_place("seomyeon-stn").model_dump(by_alias=True),
        "profile": "general",
        "weatherScenario": "normal",
        "options": {},
        "topN": 11,
    }
    assert client.post("/api/routes/recommend", json=body).status_code == 422


def test_refresh_top_n_larger_than_collected_requires_new_search():
    body = {
        "origin": find_place("gu-office").model_dump(by_alias=True),
        "destination": find_place("seomyeon-stn").model_dump(by_alias=True),
        "profile": "general",
        "weatherScenario": "normal",
        "options": {"departureAt": "2026-07-24T14:00:00+09:00"},
        "topN": 3,
    }
    initial = client.post("/api/routes/recommend", json=body)
    assert initial.status_code == 200
    token = initial.json()[0]["routeSetToken"]

    refreshed = client.post("/api/routes/refresh-shade", json={
        "routeSetToken": token,
        "profile": "general",
        "options": {"departureAt": "2026-07-24T15:00:00+09:00"},
        "topN": 10,
    })

    assert refreshed.status_code == 409
    assert "다시 검색" in refreshed.json()["detail"]


def test_refine_transit_unknown_token_is_409():
    response = client.post("/api/routes/refine-transit", json={
        "routeSetToken": "expired-token-1234567890",
        "routeId": "route-x",
    })
    assert response.status_code == 409


def test_refine_transit_unknown_route_id_is_422():
    token = _seed_route_set([_candidate("route-a", refined=True)])
    response = client.post("/api/routes/refine-transit", json={
        "routeSetToken": token,
        "routeId": "route-missing",
    })
    assert response.status_code == 422


def test_refine_transit_reuses_cached_exact_geometry_without_ai_call(
    monkeypatch,
):
    token = _seed_route_set([_candidate("route-a", refined=True)])

    async def fail_if_called(_route):
        raise AssertionError("이미 exact인 후보는 외부 정밀화를 호출하면 안 됩니다.")

    monkeypatch.setattr(app_main, "refine_candidate_transit", fail_if_called)
    response = client.post("/api/routes/refine-transit", json={
        "routeSetToken": token,
        "routeId": "route-a",
    })

    assert response.status_code == 200
    body = response.json()
    assert body["routeId"] == "route-a"
    assert body["geometryQuality"] == "exact"
    # score·rank·snapshot·feedback token은 응답에 포함되지 않는다.
    assert "score" not in body
    assert "rank" not in body
    assert "feedbackToken" not in body


def test_backend_sends_refinement_trace_identity_to_ai(monkeypatch):
    """Backend는 route ID와 공급자 후보 번호를 내부 AI 요청에 전달한다."""
    import app.providers.ai_pipeline as ai_pipeline

    route = _candidate("route-a", refined=False)
    route.transit_refinement["provider_candidate_index"] = 4
    captured = {}

    async def fake_post(path, payload):
        captured["path"] = path
        captured["payload"] = payload
        return {
            "geometry_quality": "exact",
            "refined_at": "2026-07-29T00:00:00+00:00",
            "lane_paths": [[
                {"lat": 35.1162, "lng": 129.0425},
                {"lat": 35.1570, "lng": 129.0590},
            ]],
        }

    monkeypatch.setattr(ai_pipeline, "_post_pipeline", fake_post)

    assert asyncio.run(refine_candidate_transit(route)) is True
    assert captured["path"] == "/routes/refine-transit"
    assert captured["payload"]["route_id"] == "route-a"
    assert captured["payload"]["provider_candidate_index"] == 4


def test_refine_transit_patches_only_selected_candidate(monkeypatch):
    first = _candidate("route-a", refined=False)
    second = _candidate("route-b", refined=False)
    token = _seed_route_set([first, second])
    refined_calls: list[str] = []

    async def fake_refine(route: RouteCandidate):
        refined_calls.append(route.id)
        apply_refined_transit_geometry(
            route,
            [[
                {"lat": 35.1162, "lng": 129.0425},
                {"lat": 35.1300, "lng": 129.0480},
                {"lat": 35.1570, "lng": 129.0590},
            ]],
            refined_at=datetime.now(UTC),
        )
        return True

    monkeypatch.setattr(app_main, "refine_candidate_transit", fake_refine)
    before = route_set_cache.get(token)
    response = client.post("/api/routes/refine-transit", json={
        "routeSetToken": token,
        "routeId": "route-b",
    })

    assert response.status_code == 200
    assert refined_calls == ["route-b"]
    body = response.json()
    assert body["routeId"] == "route-b"
    assert body["geometryQuality"] == "exact"
    assert len(body["path"]) >= 3

    after = route_set_cache.get(token)
    # 후보 순서·개수는 변하지 않고 선택 후보 geometry만 patch된다.
    assert [c.id for c in after.candidates] == ["route-a", "route-b"]
    assert after.candidates[0].geometry_quality == "mixed"
    assert after.candidates[0].transit_refinement_state == "not_loaded"
    assert after.candidates[1].geometry_quality == "exact"
    assert after.candidates[1].transit_refinement_state == "exact"
    assert after.revision == before.revision + 1

    # 같은 후보 재선택은 추가 외부 호출 없이 캐시를 반환한다.
    again = client.post("/api/routes/refine-transit", json={
        "routeSetToken": token,
        "routeId": "route-b",
    })
    assert again.status_code == 200
    assert refined_calls == ["route-b"]


def test_refine_transit_failure_stays_explicit_and_marks_state(monkeypatch):
    token = _seed_route_set([_candidate("route-a", refined=False)])

    async def fail_refine(_route):
        raise AIProviderError(502, "ODsay loadLane 실패: quota exceeded")

    monkeypatch.setattr(app_main, "refine_candidate_transit", fail_refine)
    response = client.post("/api/routes/refine-transit", json={
        "routeSetToken": token,
        "routeId": "route-a",
    })

    assert response.status_code == 502
    assert "quota" in response.json()["detail"]
    cached = route_set_cache.get(token)
    assert cached.candidates[0].transit_refinement_state == "failed"
    # 실패를 가짜 exact geometry로 바꾸지 않는다.
    assert cached.candidates[0].geometry_quality == "mixed"


def test_apply_refined_transit_geometry_keeps_model_identity():
    route = _candidate("route-a", refined=False)
    route.model_snapshot_hash = "a" * 64
    route.model_features = {"walk_distance_m": 250.0}
    apply_refined_transit_geometry(
        route,
        [[
            {"lat": 35.1162, "lng": 129.0425},
            {"lat": 35.1300, "lng": 129.0480},
            {"lat": 35.1570, "lng": 129.0590},
        ]],
        refined_at=datetime.now(UTC),
    )

    assert route.geometry_quality == "exact"
    assert route.transit_refinement_state == "exact"
    assert route.segments[1].geometry_quality == "exact"
    assert len(route.segments[1].path) == 3
    # ranking identity는 표시 geometry 정밀화로 변하지 않는다.
    assert route.model_snapshot_hash == "a" * 64
    assert route.model_features == {"walk_distance_m": 250.0}
    # 보행 구간은 그대로 유지된다.
    assert route.segments[0].geometry_quality == "exact"
    assert len(route.segments[0].path) == 2


def test_apply_refined_transit_geometry_rejects_lane_count_mismatch():
    route = _candidate("route-a", refined=False)
    with pytest.raises(AIProviderError):
        apply_refined_transit_geometry(
            route,
            [
                [
                    {"lat": 35.1162, "lng": 129.0425},
                    {"lat": 35.1570, "lng": 129.0590},
                ],
                [
                    {"lat": 35.1570, "lng": 129.0590},
                    {"lat": 35.1600, "lng": 129.0600},
                ],
            ],
            refined_at=datetime.now(UTC),
        )


def test_route_set_stale_revision_replace_is_rejected():
    token = _seed_route_set([_candidate("route-a", refined=False)])
    snapshot = route_set_cache.get(token)

    updated = route_set_cache.update_candidate(
        token,
        "route-a",
        lambda target: setattr(target, "transit_refinement_state", "loading"),
    )
    assert updated.revision == snapshot.revision + 1

    with pytest.raises(StaleRouteSetRevision):
        route_set_cache.replace(
            token,
            snapshot.candidates,
            snapshot.weather,
            expected_revision=snapshot.revision,
        )
    # 최신 revision 기준 교체는 성공한다.
    assert route_set_cache.replace(
        token,
        snapshot.candidates,
        snapshot.weather,
        expected_revision=updated.revision,
    ) is True


def test_concurrent_refinements_of_two_candidates_are_both_preserved(
    monkeypatch,
):
    first = _candidate("route-a", refined=False)
    second = _candidate("route-b", refined=False)
    token = _seed_route_set([first, second])

    active = 0
    peak = 0

    async def fake_refine(route: RouteCandidate):
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        await asyncio.sleep(0.01)
        active -= 1
        apply_refined_transit_geometry(
            route,
            [[
                {"lat": 35.1162, "lng": 129.0425},
                {"lat": 35.1570, "lng": 129.0590},
            ]],
            refined_at=datetime.now(UTC),
        )
        return True

    monkeypatch.setattr(app_main, "refine_candidate_transit", fake_refine)

    async def run():
        return await asyncio.gather(
            app_main.routes_refine_transit(
                app_main.TransitRefineRequest(
                    route_set_token=token,
                    route_id="route-a",
                ),
            ),
            app_main.routes_refine_transit(
                app_main.TransitRefineRequest(
                    route_set_token=token,
                    route_id="route-b",
                ),
            ),
        )

    results = asyncio.run(run())

    assert {result.route_id for result in results} == {"route-a", "route-b"}
    assert peak == 2, "서로 다른 후보 refinement가 route-set lock으로 직렬화됨"
    cached = route_set_cache.get(token)
    assert all(
        candidate.transit_refinement_state == "exact"
        for candidate in cached.candidates
    )


@pytest.mark.parametrize(
    ("hour", "feels_like", "has_weather"),
    [
        (2, 31.0, True),
        (9, 24.9, True),
        (14, 31.0, False),
        (18, 10.0, True),
    ],
)
def test_building_shade_is_not_blocked_by_time_temperature_or_weather(
    hour,
    feels_like,
    has_weather,
):
    observed = datetime(2026, 7, 27, 14, 10, tzinfo=KST)
    weather = WeatherCondition(
        label="실시간",
        temp_c=feels_like,
        feels_like_c=feels_like,
        precipitation_mm=0.0,
        wind_ms=1.0,
        pm10=20.0,
        sky="clear",
        air="good",
        observed_at=observed,
        air_quality_observed_at=observed,
    ) if has_weather else None

    assert _shade_gate_reason(
        weather,
        observed.replace(hour=hour),
    ) is None
