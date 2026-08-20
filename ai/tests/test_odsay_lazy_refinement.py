"""ODsay 지연 정밀화·single-flight·동시성 상한·일일 counter 회귀 테스트."""
import asyncio
import json
from concurrent.futures import ThreadPoolExecutor

import collectors.odsay_instrumentation as instrumentation
import pytest
from collectors.base import CollectorError, Coordinate
from collectors.odsay_collector import OdsayRouteCollector
from config import settings

ORIGIN = Coordinate(lat=35.1151, lng=129.0414)
DEST = Coordinate(lat=35.1972, lng=128.9902)


def _search_payload(candidates: int = 1) -> dict:
    return {"result": {"path": [
        {
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
        for index in range(candidates)
    ]}}


def _lane_payload() -> dict:
    return {"result": {"lane": [{"section": [{"graphPos": [
        {"x": 129.04, "y": 35.115},
        {"x": 129.059, "y": 35.157},
    ]}]}]}}


class _CountingClient:
    """동시성·호출 수 계측용 mock httpx client."""

    search_calls = 0
    lane_calls = 0
    active = 0
    max_active = 0
    delay_seconds = 0.0

    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return None

    async def get(self, url, **kwargs):
        cls = type(self)
        cls.active += 1
        cls.max_active = max(cls.max_active, cls.active)
        try:
            if cls.delay_seconds:
                await asyncio.sleep(cls.delay_seconds)
            if url.endswith("loadLane"):
                cls.lane_calls += 1
                payload = _lane_payload()
            else:
                cls.search_calls += 1
                payload = _search_payload()
        finally:
            cls.active -= 1

        class Response:
            status_code = 200

            def raise_for_status(self):
                return None

            def json(self):
                return payload

        return Response()


@pytest.fixture(autouse=True)
def _reset_counters(monkeypatch):
    monkeypatch.setattr(settings, "ODSAY_API_KEY", "test-key")
    monkeypatch.setattr(settings, "ODSAY_CACHE_DIR", "")
    _CountingClient.search_calls = 0
    _CountingClient.lane_calls = 0
    _CountingClient.active = 0
    _CountingClient.max_active = 0
    _CountingClient.delay_seconds = 0.0
    instrumentation.counters.reset()


def test_initial_collect_makes_search_only(monkeypatch):
    import collectors.odsay_collector as module

    monkeypatch.setattr(module.httpx, "AsyncClient", _CountingClient)

    result = asyncio.run(OdsayRouteCollector().collect(ORIGIN, DEST))

    assert len(result) == 1
    assert _CountingClient.search_calls == 1
    assert _CountingClient.lane_calls == 0
    snapshot = instrumentation.counters.snapshot()
    assert snapshot["network_calls"].get("searchPubTransPathT") == 1
    assert snapshot["network_calls"].get("loadLane") is None


def test_concurrent_same_od_search_single_flight(monkeypatch):
    import collectors.odsay_collector as module

    monkeypatch.setattr(module.httpx, "AsyncClient", _CountingClient)
    _CountingClient.delay_seconds = 0.02

    async def run():
        collector = OdsayRouteCollector()
        results = await asyncio.gather(*(
            collector.collect(ORIGIN, DEST) for _ in range(10)
        ))
        return results

    results = asyncio.run(run())

    assert all(len(result) == 1 for result in results)
    # 동일 OD 동시 10요청은 leader 1회의 network 호출로 합쳐진다.
    assert _CountingClient.search_calls == 1
    snapshot = instrumentation.counters.snapshot()
    assert snapshot["single_flight_followers"].get("searchPubTransPathT") == 9


def test_concurrent_same_candidate_refine_single_flight(monkeypatch):
    import collectors.odsay_collector as module

    monkeypatch.setattr(module.httpx, "AsyncClient", _CountingClient)
    _CountingClient.delay_seconds = 0.02

    async def run():
        collector = OdsayRouteCollector()
        return await asyncio.gather(*(
            collector.refine_transit("100:1:1:2", ORIGIN, DEST)
            for _ in range(10)
        ))

    results = asyncio.run(run())

    assert all(len(paths) == 1 for paths in results)
    assert _CountingClient.lane_calls == 1


def test_global_concurrency_semaphore_limits_odsay_http(monkeypatch):
    import collectors.odsay_collector as module

    monkeypatch.setattr(module.httpx, "AsyncClient", _CountingClient)
    monkeypatch.setattr(settings, "ODSAY_MAX_CONCURRENT_REQUESTS", 2)
    _CountingClient.delay_seconds = 0.02

    async def run():
        collector = OdsayRouteCollector()
        # 서로 다른 mapObj 10건을 동시에 정밀화해도 HTTP 동시성은 상한 이하다.
        await asyncio.gather(*(
            collector.refine_transit(f"1{index:02d}:1:1:2", ORIGIN, DEST)
            for index in range(10)
        ))

    asyncio.run(run())

    assert _CountingClient.lane_calls == 10
    assert _CountingClient.max_active <= 2


def test_over_limit_candidate_request_is_explicit_error(monkeypatch):
    monkeypatch.setattr(settings, "ODSAY_MAX_CANDIDATES", 5)

    with pytest.raises(CollectorError, match="상한"):
        asyncio.run(
            OdsayRouteCollector().collect(ORIGIN, DEST, max_candidates=7)
        )


def test_leader_error_propagates_and_clears_inflight(monkeypatch):
    import collectors.odsay_collector as module

    class FailingClient(_CountingClient):
        async def get(self, url, **kwargs):
            type(self).search_calls += 1
            raise module.httpx.ConnectError("boom")

    monkeypatch.setattr(module.httpx, "AsyncClient", FailingClient)
    FailingClient.search_calls = 0

    async def run():
        collector = OdsayRouteCollector()
        results = await asyncio.gather(
            *(collector.collect(ORIGIN, DEST) for _ in range(3)),
            return_exceptions=True,
        )
        return results

    results = asyncio.run(run())

    # leader 오류는 모든 대기자에게 전달된다.
    assert all(isinstance(result, CollectorError) for result in results)
    # in-flight가 제거되므로 다음 요청은 다시 시도할 수 있다.
    followup = asyncio.run(
        asyncio.wait_for(_expect_error(OdsayRouteCollector()), timeout=5)
    )
    assert isinstance(followup, CollectorError)


async def _expect_error(collector):
    try:
        await collector.collect(ORIGIN, DEST)
    except CollectorError as exc:
        return exc
    return None


def test_daily_counter_persists_and_enforces_hard_cap(
    tmp_path,
    monkeypatch,
    caplog,
):
    monkeypatch.setattr(settings, "ODSAY_CACHE_DIR", str(tmp_path))
    monkeypatch.setattr(settings, "ODSAY_DAILY_BUDGET", 10)
    instrumentation._warned_ratios.clear()

    for _ in range(7):
        assert instrumentation.record_network_call("searchPubTransPathT")

    counter = instrumentation.read_daily_counter()
    assert counter is not None
    assert counter["warning_only"] is False
    assert counter["hard_limit"] is True
    assert counter["observed_total_today"] == 7
    assert counter["estimated_remaining_service_budget"] == 3
    assert (
        counter["observed_service_calls_today"]["searchPubTransPathT"] == 7
    )

    with caplog.at_level("WARNING"):
        for _ in range(3):
            assert instrumentation.record_network_call("loadLane")
    counter = instrumentation.read_daily_counter()
    assert counter["observed_total_today"] == 10
    assert counter["estimated_remaining_service_budget"] == 0
    assert counter["network_calls_blocked"] is True
    assert counter["blocked_reason"] == "daily_budget"
    assert any("100%" in message for message in caplog.messages)

    # hard cap 이후의 신규 호출은 예약되지 않고 관측 호출 수도 늘지 않는다.
    assert instrumentation.record_network_call("loadLane") is False
    counter = instrumentation.read_daily_counter()
    assert counter["observed_total_today"] == 10
    assert counter["estimated_remaining_service_budget"] == 0

    # counter 파일에는 키·좌표·mapObj가 포함되지 않는다.
    raw = json.dumps(counter, ensure_ascii=False)
    assert "test-key" not in raw
    assert "mapObject" not in raw


def test_daily_hard_cap_reservation_is_atomic(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "ODSAY_CACHE_DIR", str(tmp_path))
    monkeypatch.setattr(settings, "ODSAY_DAILY_BUDGET", 29)

    with ThreadPoolExecutor(max_workers=16) as executor:
        results = list(executor.map(
            lambda _: instrumentation.record_network_call(
                "searchPubTransPathT"
            ),
            range(80),
        ))

    assert results.count(True) == 29
    assert results.count(False) == 51
    counter = instrumentation.read_daily_counter()
    assert counter is not None
    assert counter["observed_total_today"] == 29
    assert counter["network_calls_blocked"] is True


def test_provider_quota_response_blocks_remaining_network_slots(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setattr(settings, "ODSAY_CACHE_DIR", str(tmp_path))
    monkeypatch.setattr(settings, "ODSAY_DAILY_BUDGET", 29)

    assert instrumentation.record_network_call("searchPubTransPathT")
    instrumentation.block_network_calls_for_provider_quota()

    assert instrumentation.record_network_call("loadLane") is False
    counter = instrumentation.read_daily_counter()
    assert counter is not None
    assert counter["observed_total_today"] == 1
    assert counter["provider_quota_blocked"] is True
    assert counter["blocked_reason"] == "provider_quota"


def test_cached_search_remains_available_after_daily_cap(
    tmp_path,
    monkeypatch,
):
    import collectors.odsay_collector as module

    monkeypatch.setattr(module.httpx, "AsyncClient", _CountingClient)
    monkeypatch.setattr(settings, "ODSAY_CACHE_DIR", str(tmp_path))
    monkeypatch.setattr(settings, "ODSAY_DAILY_BUDGET", 1)

    collector = OdsayRouteCollector()
    first = asyncio.run(collector.collect(ORIGIN, DEST))
    second = asyncio.run(collector.collect(ORIGIN, DEST))

    assert len(first) == 1
    assert len(second) == 1
    assert _CountingClient.search_calls == 1
    counter = instrumentation.read_daily_counter()
    assert counter is not None
    assert counter["observed_total_today"] == 1
    assert counter["network_calls_blocked"] is True


def test_daily_cap_prevents_http_transport(tmp_path, monkeypatch):
    import collectors.odsay_collector as module

    monkeypatch.setattr(module.httpx, "AsyncClient", _CountingClient)
    monkeypatch.setattr(settings, "ODSAY_CACHE_DIR", str(tmp_path))
    monkeypatch.setattr(settings, "ODSAY_DAILY_BUDGET", 1)
    assert instrumentation.record_network_call("searchPubTransPathT")

    with pytest.raises(CollectorError) as captured:
        asyncio.run(OdsayRouteCollector().collect(ORIGIN, DEST))

    assert captured.value.code == "quota_exceeded"
    assert _CountingClient.search_calls == 0


def test_http_429_arms_provider_quota_breaker(tmp_path, monkeypatch):
    import collectors.odsay_collector as module

    class QuotaClient(_CountingClient):
        async def get(self, url, **kwargs):
            type(self).search_calls += 1
            return module.httpx.Response(
                429,
                request=module.httpx.Request("GET", url),
            )

    monkeypatch.setattr(module.httpx, "AsyncClient", QuotaClient)
    monkeypatch.setattr(settings, "ODSAY_CACHE_DIR", str(tmp_path))
    monkeypatch.setattr(settings, "ODSAY_DAILY_BUDGET", 29)
    QuotaClient.search_calls = 0

    with pytest.raises(CollectorError) as captured:
        asyncio.run(OdsayRouteCollector().collect(ORIGIN, DEST))
    assert captured.value.code == "quota_exceeded"

    counter = instrumentation.read_daily_counter()
    assert counter is not None
    assert counter["observed_total_today"] == 1
    assert counter["blocked_reason"] == "provider_quota"

    with pytest.raises(CollectorError) as blocked:
        asyncio.run(OdsayRouteCollector().collect(ORIGIN, DEST))
    assert blocked.value.code == "quota_exceeded"
    assert QuotaClient.search_calls == 1


# ── cache commit handoff race ──
#
# single-flight는 leader task가 끝나는 즉시 in-flight 항목을 지운다. persistent
# cache 쓰기가 leader 밖에 있으면 "flight 없음 + cache 없음" 상태가 잠깐
# 생기고, 그 창에 들어온 요청이 새 leader가 되어 network 호출이 한 번 더
# 나간다. sleep 타이밍에 기대지 않고 Event로 그 창을 강제로 연다.


class _BlockingStore:
    """_store_payload를 특정 kind에서 붙잡아 race window를 여는 도구."""

    def __init__(self, module, kind: str):
        self._original = module._store_payload
        self._module = module
        self._kind = kind
        self.entered = asyncio.Event()
        self.release = asyncio.Event()

    async def __call__(self, kind, identity, payload):
        if kind != self._kind:
            await self._original(kind, identity, payload)
            return
        self.entered.set()
        await self.release.wait()
        await self._original(kind, identity, payload)


def test_search_cache_commit_keeps_single_flight_ownership(
    tmp_path,
    monkeypatch,
):
    """cache commit 전에 도착한 동일 OD 요청이 network를 다시 호출하지 않는다."""
    import collectors.odsay_collector as module

    monkeypatch.setattr(module.httpx, "AsyncClient", _CountingClient)
    monkeypatch.setattr(settings, "ODSAY_CACHE_DIR", str(tmp_path))
    blocking = _BlockingStore(module, "search")
    monkeypatch.setattr(module, "_store_payload", blocking)

    async def run():
        collector = OdsayRouteCollector()
        first = asyncio.create_task(collector.collect(ORIGIN, DEST))
        # network 응답은 끝났고 cache commit 직전에 멈춘 상태를 기다린다.
        await asyncio.wait_for(blocking.entered.wait(), timeout=5)

        second = asyncio.create_task(collector.collect(ORIGIN, DEST))
        # 두 번째 요청이 leader/cache 판정을 마칠 때까지 진행시킨다.
        for _ in range(50):
            await asyncio.sleep(0)

        blocking.release.set()
        return await asyncio.gather(first, second)

    results = asyncio.run(run())

    assert all(len(result) == 1 for result in results)
    # cache에 관측 가능해지기 전에 in-flight가 사라지면 여기서 2가 된다.
    assert _CountingClient.search_calls == 1


def test_load_lane_cache_commit_keeps_single_flight_ownership(
    tmp_path,
    monkeypatch,
):
    """loadLane도 cache commit까지 leader가 소유권을 유지한다."""
    import collectors.odsay_collector as module

    monkeypatch.setattr(module.httpx, "AsyncClient", _CountingClient)
    monkeypatch.setattr(settings, "ODSAY_CACHE_DIR", str(tmp_path))
    blocking = _BlockingStore(module, "lane")
    monkeypatch.setattr(module, "_store_payload", blocking)

    async def run():
        collector = OdsayRouteCollector()
        first = asyncio.create_task(
            collector.refine_transit("100:1:1:2", ORIGIN, DEST)
        )
        await asyncio.wait_for(blocking.entered.wait(), timeout=5)

        second = asyncio.create_task(
            collector.refine_transit("100:1:1:2", ORIGIN, DEST)
        )
        for _ in range(50):
            await asyncio.sleep(0)

        blocking.release.set()
        return await asyncio.gather(first, second)

    results = asyncio.run(run())

    assert all(len(paths) == 1 for paths in results)
    assert _CountingClient.lane_calls == 1


def test_sequential_request_after_leader_reuses_cache(tmp_path, monkeypatch):
    """leader 완료 후 같은 요청은 network 없이 cache를 읽는다."""
    import collectors.odsay_collector as module

    monkeypatch.setattr(module.httpx, "AsyncClient", _CountingClient)
    monkeypatch.setattr(settings, "ODSAY_CACHE_DIR", str(tmp_path))

    async def run():
        collector = OdsayRouteCollector()
        await collector.collect(ORIGIN, DEST)
        await collector.collect(ORIGIN, DEST)

    asyncio.run(run())

    assert _CountingClient.search_calls == 1
    snapshot = instrumentation.counters.snapshot()
    assert snapshot["cache_hits"].get("searchPubTransPathT") == 1
    assert snapshot["network_calls"].get("searchPubTransPathT") == 1
