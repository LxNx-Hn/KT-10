"""PR #18 코드 검토에서 확인된 AI 측 문제의 재현 테스트.

각 테스트는 수정 전 실패하고 수정 후 통과해야 한다.
production 구현은 이 파일에서 바꾸지 않는다.
"""
import asyncio
import json

import collectors.odsay_instrumentation as instrumentation
import pytest
from collectors.base import Coordinate
from collectors.odsay_collector import OdsayRouteCollector
from config import settings

ORIGIN = Coordinate(lat=35.1151, lng=129.0414)
DEST = Coordinate(lat=35.1972, lng=128.9902)


def _raw_path(index: int) -> dict:
    return {
        "info": {
            "totalTime": 20 + index,
            "totalDistance": 5000,
            "totalWalk": 100,
            "mapObj": f"10{index}:1:1:2",
        },
        "subPath": [{
            "trafficType": 2,
            "sectionTime": 18,
            "distance": 4900,
            "startX": 129.04,
            "startY": 35.115,
            "endX": 129.059,
            "endY": 35.157,
            "lane": [{"busNo": f"10{index}"}],
        }],
    }


def _search_payload(candidates: int) -> dict:
    return {"result": {"path": [_raw_path(i) for i in range(candidates)]}}


class _Response:
    def __init__(self, payload: dict, status_code: int = 200):
        self._payload = payload
        self.status_code = status_code

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


def _client_returning(payload: dict, on_get=None):
    class Client:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def get(self, *args, **kwargs):
            if on_get is not None:
                await on_get()
            return _Response(payload)

    return Client


# ── 이슈 1: 고정 3개 batch overfetch ──

@pytest.mark.parametrize("requested", [3, 5, 7, 10])
def test_build_candidate_is_not_called_more_than_requested(
    monkeypatch,
    requested,
):
    """유효 후보만 있을 때 요청 수를 넘는 후보 조립이 없어야 한다.

    현재 구현은 고정 3개 batch라 후보 5개 요청에서 6번째 후보의
    TMAP 보행 geometry·검증·파싱까지 실행한 뒤 결과를 버린다.
    """
    import collectors.odsay_collector as module

    monkeypatch.setattr(settings, "ODSAY_API_KEY", "test-key")
    monkeypatch.setattr(settings, "ODSAY_CACHE_DIR", "")
    monkeypatch.setattr(
        module.httpx,
        "AsyncClient",
        _client_returning(_search_payload(12)),
    )

    built: list[int] = []
    original = OdsayRouteCollector._build_candidate

    async def counting_build(self, path, origin, destination):
        built.append(1)
        return await original(self, path, origin, destination)

    monkeypatch.setattr(
        OdsayRouteCollector,
        "_build_candidate",
        counting_build,
    )

    result = asyncio.run(
        OdsayRouteCollector().collect(
            ORIGIN,
            DEST,
            max_candidates=requested,
        )
    )

    assert len(result) == requested
    assert len(built) == requested, (
        f"후보 {requested}개 요청에 _build_candidate가 {len(built)}번 실행됨"
    )


def test_build_candidate_stops_after_recovering_from_failures(monkeypatch):
    """실패 후보가 있으면 필요한 수만큼만 추가로 조립한다."""
    import collectors.odsay_collector as module

    monkeypatch.setattr(settings, "ODSAY_API_KEY", "test-key")
    monkeypatch.setattr(settings, "ODSAY_CACHE_DIR", "")
    monkeypatch.setattr(
        module.httpx,
        "AsyncClient",
        _client_returning(_search_payload(12)),
    )

    built: list[int] = []
    original = OdsayRouteCollector._build_candidate

    async def failing_build(self, path, origin, destination):
        index = len(built)
        built.append(index)
        if index in (1, 3):
            raise module.CollectorError("검증 실패 후보")
        return await original(self, path, origin, destination)

    monkeypatch.setattr(
        OdsayRouteCollector,
        "_build_candidate",
        failing_build,
    )

    result = asyncio.run(
        OdsayRouteCollector().collect(ORIGIN, DEST, max_candidates=5)
    )

    assert len(result) == 5
    # 성공 5개를 만들기 위해 실패 2개를 포함해 최대 7번까지만 허용한다.
    assert len(built) <= 7, f"_build_candidate가 {len(built)}번 실행됨"


# ── 이슈 10: semaphore 대기 중 취소가 network counter를 올림 ──

def test_cancelled_while_waiting_for_semaphore_is_not_counted_as_network(
    monkeypatch,
    tmp_path,
):
    """semaphore 대기 중 취소된 요청은 실제 network 호출이 아니다.

    현재 구현은 record_network_call()을 with_concurrency_limit() 앞에서
    호출하므로 HTTP가 시작되지 않아도 일일 counter가 증가한다.
    """
    import collectors.odsay_collector as module

    monkeypatch.setattr(settings, "ODSAY_API_KEY", "test-key")
    monkeypatch.setattr(settings, "ODSAY_CACHE_DIR", str(tmp_path))
    monkeypatch.setattr(settings, "ODSAY_MAX_CONCURRENT_REQUESTS", 1)
    instrumentation._loop_semaphores.clear()

    release = asyncio.Event()
    started = asyncio.Event()
    http_calls: list[int] = []

    async def blocking_get():
        http_calls.append(1)
        started.set()
        await release.wait()

    monkeypatch.setattr(
        module.httpx,
        "AsyncClient",
        _client_returning(_search_payload(1), on_get=blocking_get),
    )

    async def scenario():
        collector = OdsayRouteCollector()
        holder = asyncio.create_task(
            collector.collect(ORIGIN, DEST, max_candidates=1)
        )
        await started.wait()

        waiter = asyncio.create_task(
            collector.collect(
                Coordinate(lat=35.2, lng=129.1),
                DEST,
                max_candidates=1,
            )
        )
        await asyncio.sleep(0.05)
        waiter.cancel()
        with pytest.raises(asyncio.CancelledError):
            await waiter

        release.set()
        await holder

    asyncio.run(scenario())

    counter = instrumentation.read_daily_counter() or {}
    observed = counter.get("observed_service_calls_today", {})
    search_calls = int(observed.get("searchPubTransPathT", 0) or 0)

    assert len(http_calls) == 1, "실제 HTTP는 1회만 시작되어야 한다"
    assert search_calls == 1, (
        f"semaphore 대기 중 취소가 network counter에 포함됨 (counter={search_calls})"
    )


def test_corrupt_daily_counter_file_does_not_break_route_collection(
    monkeypatch,
    tmp_path,
):
    """counter 파일이 손상돼도 경로 수집은 정상 동작해야 한다."""
    import collectors.odsay_collector as module
    from datetime import datetime

    monkeypatch.setattr(settings, "ODSAY_API_KEY", "test-key")
    monkeypatch.setattr(settings, "ODSAY_CACHE_DIR", str(tmp_path))
    monkeypatch.setattr(
        module.httpx,
        "AsyncClient",
        _client_returning(_search_payload(1)),
    )

    today = datetime.now(instrumentation.KST).strftime("%Y%m%d")
    corrupt = tmp_path / f"odsay-daily-counter-{today}.json"
    corrupt.write_text(
        json.dumps({"observed_service_calls_today": "not-a-dict"}),
        encoding="utf-8",
    )

    result = asyncio.run(
        OdsayRouteCollector().collect(ORIGIN, DEST, max_candidates=1)
    )

    assert len(result) == 1


# ── 이슈 13: route ID fingerprint 충돌 ──

def _feature_with_lane(
    lane_id: str,
    start_id: str,
    end_id: str,
    *,
    map_object: str = "100:1:1:2",
) -> dict:
    """표시 정보는 같지만 실제 노선 식별자가 다른 후보 피처."""
    return {
        "_sources": ["odsay"],
        "_path": [
            {"lat": 35.115, "lng": 129.04},
            {"lat": 35.157, "lng": 129.059},
        ],
        "_segments": [
            {
                "mode": "walk",
                "bus_route_name": None,
                "station_name": None,
                "description": "보행 이동",
                "distance_m": 100,
                "path": [
                    {"lat": 35.115, "lng": 129.04},
                    {"lat": 35.116, "lng": 129.041},
                ],
                "raw": {},
            },
            {
                "mode": "bus",
                "bus_route_name": "100",
                "station_name": None,
                "description": "100 · 부산역 → 서면역",
                "distance_m": 4900,
                "path": [
                    {"lat": 35.116, "lng": 129.041},
                    {"lat": 35.157, "lng": 129.059},
                ],
                "raw": {
                    "lane": [{"busID": lane_id, "busNo": "100"}],
                    "startID": start_id,
                    "endID": end_id,
                    "startName": "부산역",
                    "endName": "서면역",
                    "wayCode": "1",
                },
            },
        ],
        "_transit_refinement": {"map_object": map_object},
    }


def test_route_id_distinguishes_different_lane_sequences():
    """표시 문자열이 같아도 실제 노선·정류장이 다르면 route ID가 달라야 한다."""
    from api.router import _route_id

    left_feature = _feature_with_lane("BUS-A", "STOP-1", "STOP-9")
    right_feature = _feature_with_lane("BUS-B", "STOP-2", "STOP-8")
    right_raw = right_feature["_segments"][1]["raw"]
    right_raw["lane"][0]["busNo"] = "200"
    right_raw["startName"] = "부전역"
    right_raw["endName"] = "양정역"
    left = _route_id(left_feature)
    right = _route_id(right_feature)

    assert left != right, (
        "서로 다른 노선·승하차 정류장 후보가 같은 route ID로 충돌함"
    )


def test_route_id_is_stable_for_same_semantic_candidate():
    """같은 후보는 반복 호출에서 동일한 route ID를 유지한다."""
    from api.router import _route_id

    feature = _feature_with_lane("BUS-A", "STOP-1", "STOP-9")
    assert _route_id(feature) == _route_id(
        _feature_with_lane("BUS-A", "STOP-1", "STOP-9")
    )


def test_route_id_ignores_provider_specific_ids_and_map_objects():
    """같은 의미의 경로는 공급자 내부 ID나 ODsay mapObj와 무관해야 한다."""
    from api.router import _route_id

    left = _feature_with_lane(
        "BUS-A",
        "STOP-1",
        "STOP-9",
        map_object="100:1:1:2",
    )
    right = _feature_with_lane(
        "BUS-A",
        "STOP-1",
        "STOP-9",
        map_object="100:1:1:3",
    )

    right["_segments"][1]["raw"]["lane"][0]["busID"] = "BUS-B"
    right["_segments"][1]["raw"]["startID"] = "OTHER-START"
    right["_segments"][1]["raw"]["endID"] = "OTHER-END"
    assert _route_id(left) == _route_id(right)
    # 축약형과 loadLane 정규형은 같은 semantic mapObj다.
    normalized = _feature_with_lane(
        "BUS-A",
        "STOP-1",
        "STOP-9",
        map_object="0:0@100:1:1:2",
    )
    assert _route_id(left) == _route_id(normalized)


def test_route_id_is_independent_of_provider_array_order():
    from api.router import _route_id

    first = _feature_with_lane("BUS-A", "STOP-1", "STOP-9")
    second = _feature_with_lane(
        "BUS-B",
        "STOP-2",
        "STOP-8",
        map_object="200:1:1:2",
    )

    forward = {_route_id(item) for item in [first, second]}
    reverse = {_route_id(item) for item in [second, first]}
    assert forward == reverse


# ── 이슈 9: AI private endpoint가 인증 없이 호출 가능 ──

def test_ai_transit_refine_endpoint_requires_internal_token(monkeypatch):
    """Backend 전용 AI endpoint가 인증 없이 ODsay quota를 쓰면 안 된다."""
    from fastapi.testclient import TestClient
    from main import app

    monkeypatch.setattr(settings, "ODSAY_API_KEY", "test-key")
    monkeypatch.setattr(
        settings,
        "AI_INTERNAL_SERVICE_TOKEN",
        "internal-service-token-for-tests-0123456789",
    )
    client = TestClient(app)

    response = client.post(
        "/routes/refine-transit",
        json={
            "origin_lat": ORIGIN.lat,
            "origin_lng": ORIGIN.lng,
            "dest_lat": DEST.lat,
            "dest_lng": DEST.lng,
            "map_object": "100:1:1:2",
        },
    )

    assert response.status_code == 403, (
        f"인증 없는 내부 endpoint 호출이 {response.status_code}로 통과됨"
    )


def test_ai_health_endpoints_stay_public():
    """health·readiness는 기존 계약대로 인증 없이 접근 가능해야 한다."""
    from fastapi.testclient import TestClient
    from main import app

    client = TestClient(app)
    assert client.get("/health").status_code == 200


def test_ai_internal_endpoints_accept_the_configured_token(monkeypatch):
    """올바른 내부 토큰은 인증을 통과한다(공급자 오류는 별개)."""
    from fastapi.testclient import TestClient
    from main import app

    token = "internal-service-token-for-tests-0123456789"
    monkeypatch.setattr(settings, "ODSAY_API_KEY", "test-key")
    monkeypatch.setattr(settings, "AI_INTERNAL_SERVICE_TOKEN", token)
    client = TestClient(app)

    response = client.post(
        "/routes/refine-transit",
        headers={"X-KT10-Internal-Token": token},
        json={
            "origin_lat": ORIGIN.lat,
            "origin_lng": ORIGIN.lng,
            "dest_lat": DEST.lat,
            "dest_lng": DEST.lng,
            "map_object": "100:1:1:2",
        },
    )

    assert response.status_code != 403


def test_wrong_internal_token_is_rejected_without_leaking_the_value(
    monkeypatch,
):
    from fastapi.testclient import TestClient
    from main import app

    token = "internal-service-token-for-tests-0123456789"
    monkeypatch.setattr(settings, "AI_INTERNAL_SERVICE_TOKEN", token)
    client = TestClient(app)

    response = client.post(
        "/routes/refine-transit",
        headers={"X-KT10-Internal-Token": "wrong-token"},
        json={
            "origin_lat": ORIGIN.lat,
            "origin_lng": ORIGIN.lng,
            "dest_lat": DEST.lat,
            "dest_lng": DEST.lng,
            "map_object": "100:1:1:2",
        },
    )

    assert response.status_code == 403
    assert token not in response.text


# ── §12 correlation ID 전파 ──

def test_ai_adopts_backend_correlation_id(monkeypatch):
    """Backend가 준 correlation ID를 AI 계측이 그대로 이어받는다."""
    from fastapi.testclient import TestClient
    from main import app

    monkeypatch.setattr(settings, "ODSAY_API_KEY", "test-key")
    observed: list[str] = []

    async def capture(self, map_object, origin, destination):
        observed.append(instrumentation.correlation_id.get())
        return [[
            Coordinate(lat=35.115, lng=129.04),
            Coordinate(lat=35.157, lng=129.059),
        ]]

    monkeypatch.setattr(OdsayRouteCollector, "refine_transit", capture)
    client = TestClient(app)

    client.post(
        "/routes/refine-transit",
        headers={"X-Correlation-ID": "backend-trace-0001"},
        json={
            "origin_lat": ORIGIN.lat,
            "origin_lng": ORIGIN.lng,
            "dest_lat": DEST.lat,
            "dest_lng": DEST.lng,
            "map_object": "100:1:1:2",
        },
    )

    assert observed == ["backend-trace-0001"]


def test_malformed_correlation_id_is_replaced_not_echoed(monkeypatch):
    """형식이 맞지 않는 ID는 그대로 쓰지 않고 새로 만든다."""
    from fastapi.testclient import TestClient
    from main import app

    monkeypatch.setattr(settings, "ODSAY_API_KEY", "test-key")
    observed: list[str] = []

    async def capture(self, map_object, origin, destination):
        observed.append(instrumentation.correlation_id.get())
        return [[
            Coordinate(lat=35.115, lng=129.04),
            Coordinate(lat=35.157, lng=129.059),
        ]]

    monkeypatch.setattr(OdsayRouteCollector, "refine_transit", capture)
    client = TestClient(app)

    client.post(
        "/routes/refine-transit",
        headers={"X-Correlation-ID": "bad id with spaces; drop table"},
        json={
            "origin_lat": ORIGIN.lat,
            "origin_lng": ORIGIN.lng,
            "dest_lat": DEST.lat,
            "dest_lng": DEST.lng,
            "map_object": "100:1:1:2",
        },
    )

    assert observed and observed[0] != "bad id with spaces; drop table"
    assert observed[0]


def test_odsay_structured_log_has_required_fields_without_raw_values(caplog):
    """운영 로그는 추적 필드를 갖되 route ID·mapObj 원문을 남기지 않는다."""
    raw_route_id = "route-sensitive-value"
    raw_map_object = "100:1:1:2"
    corr_token = instrumentation.correlation_id.set("backend-trace-0002")
    route_token = instrumentation.route_id_hash.set(
        instrumentation.anonymized_hash(raw_route_id)
    )
    index_token = instrumentation.provider_candidate_index.set(3)
    try:
        with caplog.at_level(
            "INFO",
            logger="collectors.odsay.metrics",
        ):
            instrumentation.log_call(
                "loadLane",
                identity_hash=instrumentation.anonymized_hash(raw_map_object),
                cache_hit=False,
                network=True,
                follower=False,
                duration_ms=12.3,
                outcome="network",
                call_site="refine_transit",
                http_status=200,
                semaphore_wait=0.004,
            )
            instrumentation.log_rank(raw_route_id, 2)
    finally:
        instrumentation.provider_candidate_index.reset(index_token)
        instrumentation.route_id_hash.reset(route_token)
        instrumentation.correlation_id.reset(corr_token)

    text = caplog.text
    for field in (
        "corr=backend-trace-0002",
        "endpoint=loadLane",
        "site=refine_transit",
        "route_id_hash=",
        "candidate_index=3",
        "map_bounds_hash=",
        "cache=miss",
        "single_flight=leader",
        "semaphore_wait_ms=4.0",
        "network_started=yes",
        "status=200",
        "duration_ms=12.3",
        "outcome=network",
        "final_rank=2",
    ):
        assert field in text
    assert raw_route_id not in text
    assert raw_map_object not in text


def test_network_attempt_and_completion_counters_match_transport(
    monkeypatch,
    tmp_path,
):
    """attempted/completed/failed가 실제 transport 수와 일치한다."""
    import collectors.odsay_collector as module

    monkeypatch.setattr(settings, "ODSAY_API_KEY", "test-key")
    monkeypatch.setattr(settings, "ODSAY_CACHE_DIR", str(tmp_path))
    instrumentation.counters.reset()
    monkeypatch.setattr(
        module.httpx,
        "AsyncClient",
        _client_returning(_search_payload(1)),
    )

    asyncio.run(
        OdsayRouteCollector().collect(ORIGIN, DEST, max_candidates=1)
    )

    snapshot = instrumentation.counters.snapshot()
    assert snapshot["network_attempted"].get("searchPubTransPathT") == 1
    assert snapshot["network_completed"].get("searchPubTransPathT") == 1
    assert snapshot["network_failed"].get("searchPubTransPathT") is None


def test_connect_error_counts_attempted_and_failed(monkeypatch, tmp_path):
    import collectors.odsay_collector as module
    import httpx

    monkeypatch.setattr(settings, "ODSAY_API_KEY", "test-key")
    monkeypatch.setattr(settings, "ODSAY_CACHE_DIR", str(tmp_path))
    instrumentation.counters.reset()

    class Client:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def get(self, *args, **kwargs):
            raise httpx.ConnectError("connection failed")

    monkeypatch.setattr(module.httpx, "AsyncClient", Client)

    with pytest.raises(module.CollectorError):
        asyncio.run(
            OdsayRouteCollector().collect(
                ORIGIN,
                DEST,
                max_candidates=1,
            )
        )

    snapshot = instrumentation.counters.snapshot()
    assert snapshot["network_attempted"]["searchPubTransPathT"] == 1
    assert snapshot["network_failed"]["searchPubTransPathT"] == 1
    assert snapshot["network_completed"].get("searchPubTransPathT") is None


def test_client_setup_failure_is_not_counted_as_network_attempt(
    monkeypatch,
    tmp_path,
):
    import collectors.odsay_collector as module

    monkeypatch.setattr(settings, "ODSAY_API_KEY", "test-key")
    monkeypatch.setattr(settings, "ODSAY_CACHE_DIR", str(tmp_path))
    instrumentation.counters.reset()

    class Client:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            raise OSError("client setup failed")

        async def __aexit__(self, *args):
            return None

    monkeypatch.setattr(module.httpx, "AsyncClient", Client)

    with pytest.raises(OSError):
        asyncio.run(
            OdsayRouteCollector().collect(
                ORIGIN,
                DEST,
                max_candidates=1,
            )
        )

    assert instrumentation.counters.snapshot()["network_attempted"] == {}


def test_outer_timeout_while_waiting_for_semaphore_is_not_network(
    monkeypatch,
    tmp_path,
):
    import collectors.odsay_collector as module

    monkeypatch.setattr(settings, "ODSAY_API_KEY", "test-key")
    monkeypatch.setattr(settings, "ODSAY_CACHE_DIR", str(tmp_path))
    monkeypatch.setattr(settings, "ODSAY_MAX_CONCURRENT_REQUESTS", 1)
    instrumentation._loop_semaphores.clear()
    instrumentation.counters.reset()

    release = asyncio.Event()
    started = asyncio.Event()
    http_calls: list[int] = []

    async def blocking_get():
        http_calls.append(1)
        started.set()
        await release.wait()

    monkeypatch.setattr(
        module.httpx,
        "AsyncClient",
        _client_returning(_search_payload(1), on_get=blocking_get),
    )

    async def scenario():
        holder = asyncio.create_task(
            OdsayRouteCollector().collect(ORIGIN, DEST, max_candidates=1)
        )
        await started.wait()
        with pytest.raises(TimeoutError):
            await asyncio.wait_for(
                OdsayRouteCollector().collect(
                    Coordinate(lat=35.2, lng=129.1),
                    DEST,
                    max_candidates=1,
                ),
                timeout=0.05,
            )
        release.set()
        await holder

    asyncio.run(scenario())

    assert len(http_calls) == 1
    snapshot = instrumentation.counters.snapshot()
    assert snapshot["network_attempted"]["searchPubTransPathT"] == 1
def test_cache_hit_is_not_counted_as_network_attempt(monkeypatch, tmp_path):
    """캐시 적중은 실제 network 시도로 집계되지 않는다."""
    import collectors.odsay_collector as module

    monkeypatch.setattr(settings, "ODSAY_API_KEY", "test-key")
    monkeypatch.setattr(settings, "ODSAY_CACHE_DIR", str(tmp_path))
    monkeypatch.setattr(
        module.httpx,
        "AsyncClient",
        _client_returning(_search_payload(1)),
    )

    asyncio.run(OdsayRouteCollector().collect(ORIGIN, DEST, max_candidates=1))
    instrumentation.counters.reset()
    asyncio.run(OdsayRouteCollector().collect(ORIGIN, DEST, max_candidates=1))

    snapshot = instrumentation.counters.snapshot()
    assert snapshot["network_attempted"] == {}
    assert snapshot["cache_hits"].get("searchPubTransPathT") == 1


def test_counter_file_with_string_numbers_does_not_break_collection(
    monkeypatch,
    tmp_path,
):
    """숫자 필드가 문자열인 counter 파일도 경로 요청을 깨뜨리지 않는다."""
    import collectors.odsay_collector as module
    from datetime import datetime

    monkeypatch.setattr(settings, "ODSAY_API_KEY", "test-key")
    monkeypatch.setattr(settings, "ODSAY_CACHE_DIR", str(tmp_path))
    monkeypatch.setattr(
        module.httpx,
        "AsyncClient",
        _client_returning(_search_payload(1)),
    )

    today = datetime.now(instrumentation.KST).strftime("%Y%m%d")
    (tmp_path / f"odsay-daily-counter-{today}.json").write_text(
        json.dumps({
            "observed_service_calls_today": {
                "searchPubTransPathT": "12",
                "loadLane": None,
            },
        }),
        encoding="utf-8",
    )

    result = asyncio.run(
        OdsayRouteCollector().collect(ORIGIN, DEST, max_candidates=1)
    )

    assert len(result) == 1
    counter = instrumentation.read_daily_counter() or {}
    assert counter["observed_service_calls_today"]["searchPubTransPathT"] == 1
