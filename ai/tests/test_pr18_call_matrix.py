"""PR #18 §18 호출 계약 matrix.

실제 network 대신 mock transport로 endpoint별 호출 수를 직접 센다.
retry는 정상 호출 수와 분리해 집계한다.
"""
import asyncio

import collectors.odsay_instrumentation as instrumentation
import pytest
from collectors.base import Coordinate
from collectors.odsay_collector import OdsayRouteCollector
from config import settings

ORIGIN_LAT, ORIGIN_LNG = 35.1151, 129.0414
DEST_LAT, DEST_LNG = 35.1972, 128.9902


def _raw_path(index: int) -> dict:
    """보행 1구간 + 대중교통 1구간을 가진 후보 원본."""
    return {
        "info": {
            "totalTime": 20 + index,
            "totalDistance": 5000,
            "totalWalk": 300,
            "mapObj": f"10{index}:1:1:2",
        },
        "subPath": [
            {
                "trafficType": 3,
                "sectionTime": 4,
                "distance": 300,
            },
            {
                "trafficType": 2,
                "sectionTime": 18,
                "distance": 4700,
                "startX": 129.04,
                "startY": 35.115,
                "endX": 129.059,
                "endY": 35.157,
                "lane": [{"busNo": f"10{index}"}],
            },
        ],
    }


def _search_payload(count: int) -> dict:
    return {"result": {"path": [_raw_path(i) for i in range(count)]}}


def _lane_payload() -> dict:
    return {"result": {"lane": [{"section": [{"graphPos": [
        {"x": 129.04, "y": 35.115},
        {"x": 129.059, "y": 35.157},
    ]}]}]}}


class _CountingTransport:
    """endpoint별 실제 요청 수를 세는 mock httpx.AsyncClient."""

    def __init__(self, counts: dict[str, int], candidates: int):
        self.counts = counts
        self.candidates = candidates

    def client(self):
        counts = self.counts
        candidates = self.candidates

        class _Response:
            def __init__(self, payload):
                self._payload = payload
                self.status_code = 200

            def raise_for_status(self):
                return None

            def json(self):
                return self._payload

        class Client:
            def __init__(self, *args, **kwargs):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                return None

            async def get(self, url, **kwargs):
                if url.endswith("loadLane"):
                    counts["loadLane"] = counts.get("loadLane", 0) + 1
                    return _Response(_lane_payload())
                counts["search"] = counts.get("search", 0) + 1
                return _Response(_search_payload(candidates))

        return Client


@pytest.fixture(autouse=True)
def _isolated_collector(monkeypatch, tmp_path):
    """캐시·semaphore·counter를 테스트마다 격리한다."""
    monkeypatch.setattr(settings, "ODSAY_API_KEY", "test-key")
    monkeypatch.setattr(settings, "ODSAY_CACHE_DIR", str(tmp_path))
    monkeypatch.setattr(settings, "TMAP_API_KEY", "")
    monkeypatch.setattr(settings, "OSMNX_WALK_GEOMETRY_ENABLED", False)
    instrumentation._loop_semaphores.clear()
    instrumentation.counters.reset()


def _counted(monkeypatch, candidates: int) -> dict[str, int]:
    import collectors.odsay_collector as module

    counts: dict[str, int] = {}
    monkeypatch.setattr(
        module.httpx,
        "AsyncClient",
        _CountingTransport(counts, candidates).client(),
    )
    return counts


@pytest.mark.parametrize("requested", [3, 5, 7, 10])
def test_initial_collection_uses_one_search_and_no_load_lane(
    monkeypatch,
    requested,
):
    """최초 후보 수집은 search 1회, loadLane 0회."""
    counts = _counted(monkeypatch, requested + 3)

    result = asyncio.run(
        OdsayRouteCollector().collect(
            Coordinate(lat=ORIGIN_LAT, lng=ORIGIN_LNG),
            Coordinate(lat=DEST_LAT, lng=DEST_LNG),
            max_candidates=requested,
        )
    )

    assert len(result) == requested
    assert counts.get("search") == 1
    assert counts.get("loadLane") is None


def test_first_refinement_uses_exactly_one_load_lane(monkeypatch):
    """선택 후보 정밀화는 loadLane 1회, search 0회."""
    counts = _counted(monkeypatch, 5)

    asyncio.run(
        OdsayRouteCollector().refine_transit(
            "100:1:1:2",
            Coordinate(lat=ORIGIN_LAT, lng=ORIGIN_LNG),
            Coordinate(lat=DEST_LAT, lng=DEST_LNG),
        )
    )

    assert counts.get("loadLane") == 1
    assert counts.get("search") is None


def test_reselecting_same_candidate_adds_no_load_lane(monkeypatch):
    """같은 후보 재선택은 캐시를 써서 추가 loadLane 0회."""
    counts = _counted(monkeypatch, 5)
    collector = OdsayRouteCollector()
    origin = Coordinate(lat=ORIGIN_LAT, lng=ORIGIN_LNG)
    destination = Coordinate(lat=DEST_LAT, lng=DEST_LNG)

    asyncio.run(collector.refine_transit("100:1:1:2", origin, destination))
    assert counts.get("loadLane") == 1

    asyncio.run(collector.refine_transit("100:1:1:2", origin, destination))
    assert counts.get("loadLane") == 1, "재선택이 추가 loadLane을 만들었다"


def test_same_origin_destination_search_is_single_flight(monkeypatch):
    """동일 OD 동시 10요청은 search 1회로 합쳐진다."""
    counts = _counted(monkeypatch, 5)

    async def scenario():
        collector = OdsayRouteCollector()
        return await asyncio.gather(*(
            collector.collect(
                Coordinate(lat=ORIGIN_LAT, lng=ORIGIN_LNG),
                Coordinate(lat=DEST_LAT, lng=DEST_LNG),
                max_candidates=3,
            )
            for _ in range(10)
        ))

    results = asyncio.run(scenario())

    assert all(len(item) == 3 for item in results)
    assert counts.get("search") == 1


def test_same_map_object_refinement_is_single_flight(monkeypatch):
    """동일 mapObj 동시 10요청은 loadLane 1회로 합쳐진다."""
    counts = _counted(monkeypatch, 5)

    async def scenario():
        collector = OdsayRouteCollector()
        origin = Coordinate(lat=ORIGIN_LAT, lng=ORIGIN_LNG)
        destination = Coordinate(lat=DEST_LAT, lng=DEST_LNG)
        return await asyncio.gather(*(
            collector.refine_transit("100:1:1:2", origin, destination)
            for _ in range(10)
        ))

    asyncio.run(scenario())

    assert counts.get("loadLane") == 1


def test_concurrency_limit_is_respected(monkeypatch):
    """ODSAY_MAX_CONCURRENT_REQUESTS 상한을 넘지 않는다."""
    import collectors.odsay_collector as module

    monkeypatch.setattr(settings, "ODSAY_MAX_CONCURRENT_REQUESTS", 2)
    instrumentation._loop_semaphores.clear()
    active = 0
    peak = 0

    class _Response:
        status_code = 200

        def raise_for_status(self):
            return None

        def json(self):
            return _lane_payload()

    class Client:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def get(self, url, **kwargs):
            nonlocal active, peak
            active += 1
            peak = max(peak, active)
            await asyncio.sleep(0.02)
            active -= 1
            return _Response()

    monkeypatch.setattr(module.httpx, "AsyncClient", Client)

    async def scenario():
        collector = OdsayRouteCollector()
        origin = Coordinate(lat=ORIGIN_LAT, lng=ORIGIN_LNG)
        destination = Coordinate(lat=DEST_LAT, lng=DEST_LNG)
        await asyncio.gather(*(
            collector.refine_transit(
                f"10{index}:1:1:2",
                origin,
                destination,
            )
            for index in range(6)
        ))

    asyncio.run(scenario())

    assert peak <= 2, f"동시 ODsay 요청이 {peak}건까지 올라갔다"
