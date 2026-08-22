"""PR #18 코드 검토에서 확인된 Backend 측 문제의 재현 테스트.

각 테스트는 수정 전 실패하고 수정 후 통과해야 한다.
production 구현은 이 파일에서 바꾸지 않는다.
"""
import asyncio
from datetime import timedelta
from zoneinfo import ZoneInfo

import pytest
from app.main import _replace_cached_route_set, app
from app.models import (
    LatLng,
    RouteCandidate,
    RouteScore,
    RouteSegment,
    ScoreComponents,
    ScoreDisplay,
    ScoredRoute,
    ShadeSummary,
    WeatherCondition,
)
from datetime import datetime
from app.data.places import find_place
from app.data.weather import WEATHER_SCENARIOS
from app.route_set_cache import route_set_cache
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


def _candidate(route_id: str = "route-a") -> RouteCandidate:
    return RouteCandidate(
        id=route_id,
        summary="100번 버스 + 도보",
        origin="부산역",
        destination="서면역",
        segments=[
            RouteSegment(
                id=f"{route_id}-walk",
                mode="walk",
                description="보행 이동",
                duration_min=4,
                distance_m=250,
                path=[
                    LatLng(lat=35.1151, lng=129.0414),
                    LatLng(lat=35.1162, lng=129.0425),
                ],
                geometry_quality="exact",
            ),
        ],
        total_duration_min=22,
        total_walk_m=250,
        transfer_count=0,
        path=[
            LatLng(lat=35.1151, lng=129.0414),
            LatLng(lat=35.1162, lng=129.0425),
        ],
        sources=["odsay"],
        geometry_quality="exact",
    )


def _scored(candidate: RouteCandidate) -> ScoredRoute:
    return ScoredRoute(
        route=candidate,
        score=RouteScore(
            route_id=candidate.id,
            components=ScoreComponents(),
            display=ScoreDisplay(),
            final_score=80.0,
            low_floor_status="none",
            reasons=[],
            cautions=[],
            voice_summary="안내",
        ),
    )


def _weather() -> WeatherCondition:
    return WEATHER_SCENARIOS["normal"].model_copy(deep=True)


# ── 이슈 8: 존재하지 않는 token이 lock map을 증가시킴 ──

def test_invalid_route_set_tokens_do_not_leak_locks():
    """임의 token 요청이 서버 메모리의 lock map을 증가시키면 안 된다."""
    before = len(route_set_cache._token_locks)

    for index in range(10_000):
        response = client.post(
            "/api/routes/refine-transit",
            json={
                "routeSetToken": f"nonexistent-token-{index:040d}"[:64],
                "routeId": "route-a",
            },
        )
        assert response.status_code == 409

    after = len(route_set_cache._token_locks)
    assert after == before, (
        f"존재하지 않는 token 10,000건이 lock map을 {after - before}개 증가시킴"
    )


# ── 이슈 11: replace 실패 시 새 token 발급 ──

def test_replace_failure_does_not_mint_a_new_route_set_token():
    """만료된 route-set 갱신 실패가 새 token 발급으로 위장되면 안 된다."""
    from fastapi import HTTPException

    candidate = _candidate()
    scored = [_scored(candidate)]
    missing_token = "expired-token-" + "0" * 30

    before = len(route_set_cache._entries)
    with pytest.raises(HTTPException) as exc_info:
        _replace_cached_route_set(
            scored,
            [candidate],
            _weather(),
            token=missing_token,
        )

    assert exc_info.value.status_code == 409
    assert len(route_set_cache._entries) == before, (
        "replace 실패인데 새 route-set entry가 생성됨"
    )
    assert scored[0].route_set_token is None, (
        f"replace 실패인데 token이 발급됨: {scored[0].route_set_token}"
    )


def test_stale_revision_replace_returns_409_without_new_token():
    """앞선 갱신이 있으면 409이고 최신 entry가 유지된다."""
    from fastapi import HTTPException

    candidate = _candidate()
    token = route_set_cache.put([candidate], _weather())
    stale_revision = route_set_cache.get(token).revision
    route_set_cache.update_candidate(
        token,
        candidate.id,
        lambda target: setattr(target, "transit_refinement_state", "exact"),
    )

    scored = [_scored(_candidate())]
    before = len(route_set_cache._entries)
    with pytest.raises(HTTPException) as exc_info:
        _replace_cached_route_set(
            scored,
            [_candidate()],
            _weather(),
            token=token,
            expected_revision=stale_revision,
        )

    assert exc_info.value.status_code == 409
    assert len(route_set_cache._entries) == before
    assert (
        route_set_cache.get(token).candidates[0].transit_refinement_state
        == "exact"
    )


# ── 이슈 12: 미계산 shade의 상태·사유를 공개 응답에 보존 ──

def test_unavailable_shade_reason_is_serialized_in_public_response():
    """계산하지 못한 그늘은 0%가 아니라 상태와 사유로 직렬화된다."""
    from app.main import _normalize_shade_for_response

    candidate = _candidate()
    candidate.shade = ShadeSummary(
        status="unavailable",
        evaluated_at="2026-07-27T14:00:00+09:00",
        source="VWorld LT_C_BLDGINFO WFS",
        data_quality="public",
        calculation_note="건물 데이터가 준비되지 않아 계산하지 않았습니다.",
    )

    _normalize_shade_for_response([candidate])
    payload = candidate.model_dump(
        mode="json",
        by_alias=True,
        exclude_none=True,
    )

    assert candidate.shade is not None
    assert payload["shade"]["status"] == "unavailable"
    assert payload["shade"]["calculationNote"] == (
        "건물 데이터가 준비되지 않아 계산하지 않았습니다."
    )
    assert "shadeRatio" not in payload["shade"]


def test_displayable_shade_survives_normalization():
    """정상 계산된 그늘은 정규화로 사라지지 않는다."""
    from app.main import _normalize_shade_for_response

    candidate = _candidate()
    candidate.shade = ShadeSummary(
        status="estimated_public",
        evaluated_at="2026-07-27T14:00:00+09:00",
        shade_ratio=0.42,
        source="VWorld LT_C_BLDGINFO WFS",
        data_quality="public",
        calculation_note="",
    )

    _normalize_shade_for_response([candidate])

    assert candidate.shade is not None
    assert candidate.shade.shade_ratio == 0.42


def test_recommend_response_exposes_nighttime_shade_state(monkeypatch):
    """추천 응답은 야간을 그늘 미확인과 구분해야 한다."""
    monkeypatch.setattr(settings, "building_source", "vworld")
    monkeypatch.setattr(settings, "vworld_api_key", "configured")

    origin = find_place("gu-office")
    destination = find_place("seomyeon-stn")
    assert origin is not None and destination is not None

    body = {
        "origin": origin.model_dump(by_alias=True),
        "destination": destination.model_dump(by_alias=True),
        "profile": "general",
        "weatherScenario": "normal",
        # 태양 고도 0도 이하 → VWorld 조회 없이 야간 상태
        "options": {"departureAt": "2026-07-27T02:00:00+09:00"},
        "topN": 3,
    }
    response = client.post("/api/routes/recommend", json=body)
    assert response.status_code == 200

    for item in response.json():
        shade = item["route"]["shade"]
        assert shade["status"] == "not_daylight"
        assert "태양 고도" in shade["calculationNote"]
        assert "shadeRatio" not in shade, (
            f"미계산 그늘이 0% 또는 계산값으로 직렬화됨: {shade}"
        )


# ── §4 route-set lock 구조 추가 검증 ──

def test_lock_existing_yields_none_for_unknown_token():
    async def scenario():
        async with route_set_cache.lock_existing("no-such-token") as cached:
            return cached

    assert asyncio.run(scenario()) is None
    assert route_set_cache._token_locks == {}
    assert route_set_cache._token_lock_waiters == {}


def test_lock_is_released_and_discarded_after_use():
    token = route_set_cache.put([_candidate()], _weather())

    async def scenario():
        async with route_set_cache.lock_existing(token) as cached:
            assert cached is not None
            # 사용 중에는 잠금이 유지된다.
            assert token in route_set_cache._token_locks

    asyncio.run(scenario())
    route_set_cache.clear()
    assert route_set_cache._token_locks == {}
    assert route_set_cache._token_lock_waiters == {}


def test_lock_existing_reports_expiry_that_happens_while_waiting():
    """잠금 대기 중 route-set이 만료되면 None으로 알려야 한다."""
    token = route_set_cache.put([_candidate()], _weather())
    holder_entered = asyncio.Event()
    release = asyncio.Event()

    async def holder():
        async with route_set_cache.lock_existing(token) as cached:
            assert cached is not None
            holder_entered.set()
            await release.wait()
            # 대기자가 잠금을 얻기 직전에 만료시킨다.
            route_set_cache._entries.pop(token, None)

    async def waiter():
        await holder_entered.wait()
        release.set()
        async with route_set_cache.lock_existing(token) as cached:
            return cached

    async def scenario():
        holder_task = asyncio.create_task(holder())
        waiter_task = asyncio.create_task(waiter())
        results = await asyncio.gather(holder_task, waiter_task)
        return results[1]

    assert asyncio.run(scenario()) is None


def test_deleted_entry_discards_token_lock_after_last_user():
    token = route_set_cache.put([_candidate()], _weather())

    async def scenario():
        async with route_set_cache.lock_existing(token) as cached:
            assert cached is not None
            route_set_cache._entries.pop(token, None)

    asyncio.run(scenario())
    assert token not in route_set_cache._token_locks
    assert token not in route_set_cache._token_lock_waiters


def test_concurrent_lock_get_and_candidate_update_has_no_deadlock():
    token = route_set_cache.put([_candidate()], _weather())

    async def worker():
        for _ in range(20):
            async with route_set_cache.lock_existing(token) as cached:
                assert cached is not None
                route_set_cache.update_candidate(
                    token,
                    "route-a",
                    lambda target: setattr(
                        target,
                        "transit_refinement_state",
                        "not_loaded",
                    ),
                )
            assert route_set_cache.get(token) is not None
            await asyncio.sleep(0)

    async def scenario():
        await asyncio.wait_for(
            asyncio.gather(*(worker() for _ in range(8))),
            timeout=3,
        )

    asyncio.run(scenario())


def test_update_candidate_increments_revision_and_keeps_order():
    first = _candidate("route-a")
    second = _candidate("route-b")
    token = route_set_cache.put([first, second], _weather())
    before = route_set_cache.get(token)
    assert before is not None

    updated = route_set_cache.update_candidate(
        token,
        "route-b",
        lambda target: setattr(target, "transit_refinement_state", "exact"),
    )

    assert updated is not None
    assert updated.revision == before.revision + 1
    assert [item.id for item in updated.candidates] == ["route-a", "route-b"]


def test_stale_revision_replace_is_rejected():
    from app.route_set_cache import StaleRouteSetRevision

    candidate = _candidate()
    token = route_set_cache.put([candidate], _weather())
    stale_revision = route_set_cache.get(token).revision

    route_set_cache.update_candidate(
        token,
        candidate.id,
        lambda target: setattr(target, "transit_refinement_state", "exact"),
    )

    with pytest.raises(StaleRouteSetRevision):
        route_set_cache.replace(
            token,
            [_candidate()],
            _weather(),
            expected_revision=stale_revision,
        )

    latest = route_set_cache.get(token)
    assert latest.candidates[0].transit_refinement_state == "exact"


# ── §6 route-set 기반 rescore 계약 ──

def _seeded_route_set() -> tuple[str, list[RouteCandidate]]:
    from app.data.routes import demo_candidates

    candidates = demo_candidates()[:3]
    token = route_set_cache.put(
        candidates,
        _weather(),
        metadata={
            "originalRequestedTopN": 3,
            "effectiveTopN": 3,
            "collectedCandidateCount": len(candidates),
        },
    )
    return token, candidates


def test_rescore_reuses_route_set_without_provider_calls(monkeypatch):
    """프로필 변경 재순위화는 경로 공급자를 다시 호출하지 않는다."""
    import app.main as app_main

    def fail_if_collected(*_args, **_kwargs):
        raise AssertionError("rescore가 경로 후보를 다시 수집했습니다.")

    async def fail_if_pipeline(*_args, **_kwargs):
        raise AssertionError("rescore가 AI 후보 수집을 호출했습니다.")

    monkeypatch.setattr(app_main, "get_route_candidates", fail_if_collected)
    monkeypatch.setattr(
        app_main,
        "get_ai_pipeline_candidates",
        fail_if_pipeline,
    )
    add_shade = app_main._add_configured_shade

    async def assert_cache_only(candidates, departure_at=None, **kwargs):
        assert kwargs.get("wait_for_buildings") is False
        assert kwargs.get("cache_only_buildings") is True
        return await add_shade(candidates, departure_at, **kwargs)

    monkeypatch.setattr(
        app_main,
        "_add_configured_shade",
        assert_cache_only,
    )

    token, candidates = _seeded_route_set()
    before_ids = [candidate.id for candidate in candidates]

    response = client.post(
        "/api/routes/rescore",
        json={
            "routeSetToken": token,
            "profile": "elderly",
            "options": {"avoidStairs": True},
            "topN": 3,
        },
    )

    assert response.status_code == 200
    results = response.json()
    assert {item["routeSetToken"] for item in results} == {token}
    assert set(item["route"]["id"] for item in results) <= set(before_ids)


def test_rescore_accepts_smaller_top_n_without_collecting_candidates(
    monkeypatch,
):
    import app.main as app_main

    async def fail_if_pipeline(*_args, **_kwargs):
        raise AssertionError("rescore가 후보 수집을 호출했습니다.")

    monkeypatch.setattr(
        app_main,
        "get_ai_pipeline_candidates",
        fail_if_pipeline,
    )
    token, _ = _seeded_route_set()

    response = client.post(
        "/api/routes/rescore",
        json={
            "routeSetToken": token,
            "profile": "general",
            "weatherScenario": "normal",
            "options": {},
            "topN": 2,
        },
    )

    assert response.status_code == 200
    assert len(response.json()) == 2


def test_rescore_uses_requested_mock_weather_without_weather_network(
    monkeypatch,
):
    import app.main as app_main

    async def fail_if_weather_called(*_args, **_kwargs):
        raise AssertionError("rescore가 weather 공급자를 호출했습니다.")

    monkeypatch.setattr(app_main, "get_current_weather", fail_if_weather_called)
    token, _ = _seeded_route_set()

    response = client.post(
        "/api/routes/rescore",
        json={
            "routeSetToken": token,
            "profile": "general",
            "weatherScenario": "rain",
            "options": {"weatherAvoid": True},
            "topN": 3,
        },
    )

    assert response.status_code == 200
    cached = route_set_cache.get(token)
    assert cached is not None
    assert cached.weather.label == WEATHER_SCENARIOS["rain"].label
    assert (
        cached.weather.precipitation_mm
        == WEATHER_SCENARIOS["rain"].precipitation_mm
    )


@pytest.mark.parametrize(
    ("options", "expected"),
    [
        ({"avoid_stairs": True}, {"stair_avoidance_burden": 3}),
        (
            {"carry_luggage": True},
            {
                "luggage_walk_burden": 800.0,
                "luggage_stair_burden": 3,
            },
        ),
        (
            {"stroller": True},
            {
                "stroller_walk_burden": 800.0,
                "stroller_stair_burden": 3,
                "stroller_elevator_gap": 0.75,
            },
        ),
        (
            {"low_floor_priority": True},
            {"low_floor_priority_mismatch": 1.0},
        ),
        (
            {"minimize_transfers": True},
            {"minimize_transfers_burden": 2},
        ),
        (
            {"shade_priority": True},
            {"shade_priority_unshaded_walk_m": 480.0},
        ),
        (
            {"weather_avoid": True},
            {"weather_priority_walk_burden": 800.0},
        ),
    ],
)
def test_rescore_rebuilds_all_context_dependent_features(options, expected):
    from app.models import ScoringOptions
    from app.providers.ai_pipeline import _shade_enriched_features

    candidate = _candidate()
    candidate.total_walk_m = 800
    candidate.model_features = {
        "stair_count": 3,
        "walk_distance_m": 800.0,
        "elevator_ratio": 0.25,
        "is_low_floor_bus": False,
        "transfer_count": 2,
        # 이전 요청에서 활성화됐던 값을 의도적으로 넣어 새 요청이
        # 반드시 덮어쓰는지 검증한다.
        "stair_avoidance_burden": 999.0,
        "luggage_walk_burden": 999.0,
        "luggage_stair_burden": 999.0,
        "low_floor_priority_mismatch": 999.0,
        "wheelchair_stair_burden": 999.0,
        "wheelchair_elevator_gap": 999.0,
        "walking_aid_walk_burden": 999.0,
        "max_walk_excess_m": 999.0,
        "weather_priority_walk_burden": 999.0,
        "stroller_walk_burden": 999.0,
        "stroller_stair_burden": 999.0,
        "stroller_elevator_gap": 999.0,
        "shade_priority_unshaded_walk_m": 999.0,
        "minimize_transfers_burden": 999.0,
    }
    candidate.shade = ShadeSummary(
        status="estimated_public",
        evaluated_at="2026-07-27T14:00:00+09:00",
        shade_ratio=0.4,
        shaded_walk_m=320,
        total_walk_m=800,
        source="VWorld LT_C_BLDGINFO WFS",
        data_quality="public",
        calculation_note="",
    )

    features = _shade_enriched_features(
        candidate,
        ScoringOptions(**options),
    )

    for key, value in expected.items():
        assert features[key] == value
    for key in {
        "stair_avoidance_burden",
        "luggage_walk_burden",
        "luggage_stair_burden",
        "low_floor_priority_mismatch",
        "weather_priority_walk_burden",
        "stroller_walk_burden",
        "stroller_stair_burden",
        "stroller_elevator_gap",
        "shade_priority_unshaded_walk_m",
        "minimize_transfers_burden",
    } - set(expected):
        assert features[key] == 0.0


def test_rescore_context_features_keep_unknown_observations_unknown():
    from app.models import ScoringOptions
    from app.providers.ai_pipeline import _shade_enriched_features

    candidate = _candidate()
    candidate.model_features = {
        "stair_count": None,
        "walk_distance_m": None,
        "elevator_ratio": None,
        "is_low_floor_bus": None,
        "transfer_count": None,
    }
    features = _shade_enriched_features(
        candidate,
        ScoringOptions(
            avoid_stairs=True,
            carry_luggage=True,
            stroller=True,
            low_floor_priority=True,
            minimize_transfers=True,
            shade_priority=True,
        ),
    )

    assert features["stair_avoidance_burden"] is None
    assert features["luggage_walk_burden"] is None
    assert features["luggage_stair_burden"] is None
    assert features["stroller_elevator_gap"] is None
    assert features["low_floor_priority_mismatch"] is None
    assert features["minimize_transfers_burden"] is None
    assert features["shade_priority_unshaded_walk_m"] is None


def test_rescore_preserves_already_refined_transit_geometry():
    """이미 정밀화된 대중교통 선형은 재순위화로 사라지지 않는다."""
    token, candidates = _seeded_route_set()
    target = candidates[0].id
    route_set_cache.update_candidate(
        token,
        target,
        lambda item: setattr(item, "transit_refinement_state", "exact"),
    )

    response = client.post(
        "/api/routes/rescore",
        json={
            "routeSetToken": token,
            "profile": "general",
            "options": {},
            "topN": 3,
        },
    )

    assert response.status_code == 200
    stored = route_set_cache.get(token)
    refined = next(item for item in stored.candidates if item.id == target)
    assert refined.transit_refinement_state == "exact"


def test_rescore_rejects_top_n_larger_than_collected_candidates():
    token, candidates = _seeded_route_set()

    response = client.post(
        "/api/routes/rescore",
        json={
            "routeSetToken": token,
            "profile": "general",
            "options": {},
            "topN": len(candidates) + 1,
        },
    )

    assert response.status_code == 409


def test_rescore_with_expired_token_returns_409_without_new_token():
    before = len(route_set_cache._entries)
    response = client.post(
        "/api/routes/rescore",
        json={
            "routeSetToken": "expired-token-" + "0" * 30,
            "profile": "general",
            "options": {},
        },
    )

    assert response.status_code == 409
    assert len(route_set_cache._entries) == before


# ── §10 refinement 실패 cooldown·오류 분류 ──

def _refinable_route_set() -> tuple[str, str]:
    candidate = _candidate("route-refine")
    candidate.segments.append(
        RouteSegment(
            id="route-refine-bus",
            mode="bus",
            description="100 · 부산역 → 서면역",
            duration_min=18,
            distance_m=4900,
            bus_route_name="100",
            path=[
                LatLng(lat=35.1162, lng=129.0425),
                LatLng(lat=35.1570, lng=129.0590),
            ],
            geometry_quality="estimated",
        )
    )
    candidate.geometry_quality = "mixed"
    candidate.transit_refinement_state = "not_loaded"
    candidate.transit_refinement = {
        "provider": "odsay",
        "map_object": "100:1:1:2",
        "origin": {"lat": 35.1151, "lng": 129.0414},
        "destination": {"lat": 35.1972, "lng": 128.9902},
    }
    token = route_set_cache.put([candidate], _weather())
    return token, candidate.id


def _refine(token: str, route_id: str):
    return client.post(
        "/api/routes/refine-transit",
        json={"routeSetToken": token, "routeId": route_id},
    )


@pytest.mark.parametrize(
    ("code", "expected_second_status"),
    [
        ("timeout", 429),
        ("network_error", 429),
        ("upstream_5xx", 429),
        ("auth_failed", 409),
        ("quota_exceeded", 409),
        ("invalid_response", 409),
        ("empty_geometry", 409),
    ],
)
def test_failed_refinement_blocks_immediate_retry(
    monkeypatch,
    code,
    expected_second_status,
):
    """실패 직후 재선택은 공급자를 다시 호출하지 않는다."""
    import app.main as app_main
    from app.providers.ai_pipeline import AIProviderError

    calls = []

    async def failing_refine(route):
        calls.append(route.id)
        raise AIProviderError(
            502,
            "provider failed",
            code=code,
            retryable=code not in {
                "auth_failed", "quota_exceeded", "invalid_response",
            },
        )

    monkeypatch.setattr(app_main, "refine_candidate_transit", failing_refine)
    token, route_id = _refinable_route_set()

    first = _refine(token, route_id)
    assert first.status_code == 502
    assert len(calls) == 1

    second = _refine(token, route_id)
    assert second.status_code == expected_second_status
    assert len(calls) == 1, "cooldown 중인데 공급자를 다시 호출함"
    if expected_second_status == 429:
        assert second.headers.get("Retry-After") is not None


def test_cooldown_expiry_allows_one_more_attempt(monkeypatch):
    """cooldown이 지나면 정확히 한 번 다시 시도할 수 있다."""
    import app.main as app_main
    from app.providers.ai_pipeline import AIProviderError

    calls = []

    async def failing_refine(route):
        calls.append(route.id)
        raise AIProviderError(502, "timeout", code="timeout")

    monkeypatch.setattr(app_main, "refine_candidate_transit", failing_refine)
    token, route_id = _refinable_route_set()

    assert _refine(token, route_id).status_code == 502
    assert _refine(token, route_id).status_code == 429

    # cooldown 만료를 시뮬레이션한다.
    route_set_cache.update_candidate(
        token,
        route_id,
        lambda target: setattr(
            target,
            "transit_refinement_retry_after",
            datetime.now(KST) - timedelta(seconds=1),
        ),
    )

    assert _refine(token, route_id).status_code == 502
    assert len(calls) == 2


def test_concurrent_failed_refinements_are_single_flight(monkeypatch):
    import app.main as app_main
    import httpx
    from app.providers.ai_pipeline import AIProviderError

    calls = []

    async def failing_refine(route):
        calls.append(route.id)
        await asyncio.sleep(0.05)
        raise AIProviderError(502, "timeout", code="timeout")

    monkeypatch.setattr(app_main, "refine_candidate_transit", failing_refine)
    token, route_id = _refinable_route_set()

    async def scenario():
        transport = httpx.ASGITransport(app=app_main.app)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://testserver",
        ) as async_client:
            return await asyncio.gather(*(
                async_client.post(
                    "/api/routes/refine-transit",
                    json={"routeSetToken": token, "routeId": route_id},
                )
                for _ in range(10)
            ))

    responses = asyncio.run(scenario())
    assert all(response.status_code == 502 for response in responses)
    assert len(calls) == 1
    stored = route_set_cache.get(token).candidates[0]
    assert stored.transit_refinement_state == "failed"
    assert stored.transit_refinement_failure_count == 1
    assert stored.transit_refinement_state != "exact"


def test_successful_refinement_clears_failure_metadata(monkeypatch):
    """성공하면 이전 실패 metadata가 제거된다."""
    import app.main as app_main
    from app.providers.ai_pipeline import AIProviderError

    state = {"fail": True}

    async def flaky_refine(route):
        if state["fail"]:
            raise AIProviderError(502, "timeout", code="timeout")
        route.transit_refinement_state = "exact"
        route.transit_refined_at = datetime.now(KST)
        for segment in route.segments:
            if segment.mode in ("bus", "subway"):
                segment.geometry_quality = "exact"
        route.geometry_quality = "exact"
        return True

    monkeypatch.setattr(app_main, "refine_candidate_transit", flaky_refine)
    token, route_id = _refinable_route_set()

    assert _refine(token, route_id).status_code == 502
    stored = route_set_cache.get(token).candidates[0]
    assert stored.transit_refinement_failure_code == "timeout"

    state["fail"] = False
    route_set_cache.update_candidate(
        token,
        route_id,
        lambda target: setattr(
            target, "transit_refinement_retry_after", None
        ),
    )
    route_set_cache.update_candidate(
        token,
        route_id,
        lambda target: setattr(
            target, "transit_refinement_state", "not_loaded"
        ),
    )

    assert _refine(token, route_id).status_code == 200
    refreshed = route_set_cache.get(token).candidates[0]
    assert refreshed.transit_refinement_failure_code is None
    assert refreshed.transit_refinement_failure_count == 0


# ── §14 후보별 single-flight·lock 범위 ──

def test_concurrent_requests_for_same_candidate_call_provider_once(
    monkeypatch,
):
    """같은 후보 동시 10요청은 AI 정밀화를 한 번만 호출한다."""
    import app.main as app_main
    import httpx

    calls = []

    async def slow_refine(route):
        calls.append(route.id)
        await asyncio.sleep(0.05)
        route.transit_refinement_state = "exact"
        route.transit_refined_at = datetime.now(KST)
        for segment in route.segments:
            if segment.mode in ("bus", "subway"):
                segment.geometry_quality = "exact"
        route.geometry_quality = "exact"
        return True

    monkeypatch.setattr(app_main, "refine_candidate_transit", slow_refine)
    token, route_id = _refinable_route_set()

    async def scenario():
        transport = httpx.ASGITransport(app=app_main.app)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://testserver",
        ) as async_client:
            return await asyncio.gather(*(
                async_client.post(
                    "/api/routes/refine-transit",
                    json={"routeSetToken": token, "routeId": route_id},
                )
                for _ in range(10)
            ))

    responses = asyncio.run(scenario())

    assert all(response.status_code == 200 for response in responses)
    assert len(calls) == 1, f"동일 후보에 {len(calls)}번 호출됨"


def test_refinement_and_shade_refresh_both_survive(monkeypatch):
    """외부 정밀화가 진행 중이어도 rescore와 exact geometry가 모두 보존된다."""
    import app.main as app_main
    import httpx

    started = None
    release = None

    async def refine(route):
        started.set()
        await release.wait()
        route.transit_refinement_state = "exact"
        route.transit_refined_at = datetime.now(KST)
        for segment in route.segments:
            if segment.mode in ("bus", "subway"):
                segment.geometry_quality = "exact"
        route.geometry_quality = "exact"
        return True

    monkeypatch.setattr(app_main, "refine_candidate_transit", refine)
    token, route_id = _refinable_route_set()

    async def scenario():
        nonlocal started, release
        started = asyncio.Event()
        release = asyncio.Event()
        transport = httpx.ASGITransport(app=app_main.app)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://testserver",
        ) as async_client:
            refinement = asyncio.create_task(
                async_client.post(
                    "/api/routes/refine-transit",
                    json={"routeSetToken": token, "routeId": route_id},
                )
            )
            await asyncio.wait_for(started.wait(), timeout=1)
            rescored = await async_client.post(
                "/api/routes/rescore",
                json={
                    "routeSetToken": token,
                    "profile": "general",
                    "weatherScenario": "rain",
                    "options": {
                        "departureAt": "2026-07-27T14:00:00+09:00",
                    },
                    "topN": 1,
                },
            )
            release.set()
            return rescored, await refinement

    rescored, refined = asyncio.run(scenario())
    assert rescored.status_code == 200
    assert refined.status_code == 200

    stored = route_set_cache.get(token).candidates[0]
    cached = route_set_cache.get(token)
    assert stored.transit_refinement_state == "exact", (
        "rescore가 정밀화된 geometry를 덮어씀"
    )
    assert stored.geometry_quality == "exact"
    assert cached.weather.label == WEATHER_SCENARIOS["rain"].label


def test_route_set_expiry_during_refinement_discards_network_result(
    monkeypatch,
):
    import app.main as app_main

    started = asyncio.Event()
    release = asyncio.Event()

    async def slow_refine(route):
        started.set()
        await release.wait()
        route.transit_refinement_state = "exact"
        route.geometry_quality = "exact"
        return True

    monkeypatch.setattr(app_main, "refine_candidate_transit", slow_refine)
    token, route_id = _refinable_route_set()

    async def scenario():
        task = asyncio.create_task(
            app_main.routes_refine_transit(
                app_main.TransitRefineRequest(
                    route_set_token=token,
                    route_id=route_id,
                ),
            )
        )
        await started.wait()
        route_set_cache._entries.pop(token, None)
        release.set()
        with pytest.raises(Exception) as exc_info:
            await task
        return exc_info.value

    error = asyncio.run(scenario())
    assert getattr(error, "status_code", None) == 409
    assert route_set_cache.get(token) is None
