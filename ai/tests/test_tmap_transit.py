import asyncio

import httpx
import pytest

from collectors.base import CollectorError, Coordinate, RouteCandidate
from collectors.odsay_collector import OdsayRouteCollector
from collectors.tmap_transit_collector import TmapTransitRouteCollector
from collectors.transit_provider import (
    TransitProviderCollector,
    provider_order,
)
from collectors.transit_walk import WalkGeometryResult
from config import settings


ORIGIN = Coordinate(lat=35.1796, lng=129.0756)
DESTINATION = Coordinate(lat=35.1579, lng=129.0591)


def _walk_leg(start, end, line):
    return {
        "mode": "WALK",
        "sectionTime": 120,
        "distance": 130,
        "start": {"name": start[0], "lon": start[1], "lat": start[2]},
        "end": {"name": end[0], "lon": end[1], "lat": end[2]},
        "steps": [{"linestring": line}],
    }


def _payload():
    return {
        "metaData": {
            "plan": {
                "itineraries": [{
                    "totalTime": 720,
                    "transferCount": 0,
                    "totalWalkDistance": 260,
                    "totalDistance": 3000,
                    "fare": {"regular": {"totalFare": 1600}},
                    "legs": [
                        _walk_leg(
                            ("출발지", 129.0756, 35.1796),
                            ("시청", 129.0760, 35.1793),
                            "129.0756,35.1796 129.0760,35.1793",
                        ),
                        {
                            "mode": "SUBWAY",
                            "sectionTime": 480,
                            "distance": 2740,
                            "route": "부산1호선",
                            "routeId": "260011002",
                            "service": 1,
                            "start": {
                                "name": "시청",
                                "lon": 129.0760,
                                "lat": 35.1793,
                            },
                            "end": {
                                "name": "서면",
                                "lon": 129.0594,
                                "lat": 35.1582,
                            },
                            "passStopList": {"stationList": [
                                {
                                    "stationID": "SUB-1",
                                    "stationName": "시청",
                                    "lon": "129.0760",
                                    "lat": "35.1793",
                                },
                                {
                                    "stationID": "SUB-2",
                                    "stationName": "서면",
                                    "lon": "129.0594",
                                    "lat": "35.1582",
                                },
                            ]},
                            "passShape": {
                                "linestring": (
                                    "129.0760,35.1793 129.0700,35.1700 "
                                    "129.0594,35.1582"
                                )
                            },
                        },
                        _walk_leg(
                            ("서면", 129.0594, 35.1582),
                            ("도착지", 129.0591, 35.1579),
                            "129.0594,35.1582 129.0591,35.1579",
                        ),
                    ],
                }]
            }
        }
    }


def test_tmap_transit_normalizes_exact_route_and_caches(
    monkeypatch,
    tmp_path,
):
    import collectors.tmap_transit_collector as module

    requests = 0
    walk_resolver_calls = 0

    class Response:
        status_code = 200

        def raise_for_status(self):
            return None

        def json(self):
            return _payload()

    class Client:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def post(self, *_args, **_kwargs):
            nonlocal requests
            requests += 1
            return Response()

    async def resolve(_self, start, end):
        nonlocal walk_resolver_calls
        walk_resolver_calls += 1
        return WalkGeometryResult([start, end], "exact", {})

    monkeypatch.setattr(settings, "TMAP_API_KEY", "test-key")
    monkeypatch.setattr(settings, "TMAP_TRANSIT_CACHE_DIR", str(tmp_path))
    monkeypatch.setattr(settings, "TMAP_TRANSIT_CACHE_TTL_SECONDS", 1800)
    monkeypatch.setattr(module.httpx, "AsyncClient", Client)
    monkeypatch.setattr(module.TransitWalkGeometryResolver, "resolve", resolve)

    first = asyncio.run(
        TmapTransitRouteCollector().collect(
            ORIGIN,
            DESTINATION,
            max_candidates=1,
        )
    )
    second = asyncio.run(
        TmapTransitRouteCollector().collect(
            ORIGIN,
            DESTINATION,
            max_candidates=1,
        )
    )

    assert requests == 1
    assert walk_resolver_calls == 0
    assert first[0].source == "tmap_transit"
    assert first[0].duration_min == 12
    assert first[0].geometry_quality == "exact"
    assert [item["mode"] for item in first[0].segments] == [
        "walk", "subway", "walk"
    ]
    assert first[0].segments[1]["raw"]["startID"] == "SUB-1"
    assert first[0].segments[1]["raw"]["endID"] == "SUB-2"
    assert first[0].segments[1]["raw"]["lane"] == [{
        "name": "부산1호선",
        "subwayCode": 71,
    }]
    assert second[0].path == first[0].path
    cache_text = next(tmp_path.glob("*.json")).read_text(encoding="utf-8")
    assert "test-key" not in cache_text


def test_tmap_transit_retries_one_transient_non_json_response(
    monkeypatch,
    tmp_path,
):
    import collectors.tmap_transit_collector as module

    requests = 0
    delays: list[float] = []

    class Response:
        status_code = 200

        def __init__(self, valid: bool):
            self.valid = valid

        def raise_for_status(self):
            return None

        def json(self):
            if not self.valid:
                raise ValueError("temporary non-JSON response")
            return _payload()

    class Client:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def post(self, *_args, **_kwargs):
            nonlocal requests
            requests += 1
            return Response(valid=requests == 2)

    async def record_delay(seconds: float):
        delays.append(seconds)

    monkeypatch.setattr(settings, "TMAP_API_KEY", "test-key")
    monkeypatch.setattr(settings, "TMAP_TRANSIT_CACHE_DIR", str(tmp_path))
    monkeypatch.setattr(module.httpx, "AsyncClient", Client)
    monkeypatch.setattr(module.asyncio, "sleep", record_delay)

    result = asyncio.run(
        TmapTransitRouteCollector().collect(
            ORIGIN,
            DESTINATION,
            max_candidates=1,
        )
    )

    assert len(result) == 1
    assert requests == 2
    assert delays == [module.RETRY_DELAY_SECONDS]


def test_tmap_transit_accepts_unescaped_control_character_in_text():
    import collectors.tmap_transit_collector as module

    response = httpx.Response(
        200,
        content=b'{"metaData":{"description":"first\x00second"}}',
    )

    assert module._response_json(response) == {
        "metaData": {"description": "first\x00second"},
    }


def test_tmap_transit_resolves_only_missing_walk_geometry(monkeypatch):
    import collectors.tmap_transit_collector as module

    payload = _payload()
    legs = payload["metaData"]["plan"]["itineraries"][0]["legs"]
    legs[0].pop("steps")
    legs[2].pop("steps")
    resolved: list[tuple[Coordinate, Coordinate]] = []

    async def resolve(_self, start, end):
        resolved.append((start, end))
        return WalkGeometryResult([start, end], "exact", {})

    monkeypatch.setattr(module.TransitWalkGeometryResolver, "resolve", resolve)
    candidates = asyncio.run(
        TmapTransitRouteCollector()._from_payload(
            payload,
            max_candidates=1,
        )
    )

    assert len(resolved) == 2
    assert candidates[0].geometry_quality == "exact"


def test_transit_provider_uses_tmap_when_odsay_is_not_configured(monkeypatch):
    route = RouteCandidate(
        source="tmap_transit",
        path=[ORIGIN, DESTINATION],
        duration_min=12,
        distance_m=3000,
    )
    tmap_calls = 0

    async def tmap_collect(_self, *_args, **_kwargs):
        nonlocal tmap_calls
        tmap_calls += 1
        return [route]

    monkeypatch.setattr(settings, "TRANSIT_PROVIDER_ORDER", "odsay,tmap")
    monkeypatch.setattr(settings, "ODSAY_API_KEY", "")
    monkeypatch.setattr(settings, "TMAP_API_KEY", "test-key")
    monkeypatch.setattr(TmapTransitRouteCollector, "collect", tmap_collect)

    collector = TransitProviderCollector()
    result = asyncio.run(
        collector.collect(ORIGIN, DESTINATION, max_candidates=5)
    )

    assert result == [route]
    assert tmap_calls == 1
    assert collector.attempted_sources == ["odsay", "tmap_transit"]
    assert collector.selected_source == "tmap_transit"
    assert "odsay" in collector.source_errors


def test_transit_provider_falls_back_after_odsay_failure(monkeypatch):
    route = RouteCandidate(
        source="tmap_transit",
        path=[ORIGIN, DESTINATION],
        duration_min=12,
        distance_m=3000,
    )

    async def odsay_collect(_self, *_args, **_kwargs):
        raise CollectorError("ODsay 한도 초과", code="quota_exceeded")

    async def tmap_collect(_self, *_args, **_kwargs):
        return [route]

    monkeypatch.setattr(settings, "TRANSIT_PROVIDER_ORDER", "odsay,tmap")
    monkeypatch.setattr(OdsayRouteCollector, "collect", odsay_collect)
    monkeypatch.setattr(TmapTransitRouteCollector, "collect", tmap_collect)

    collector = TransitProviderCollector()
    result = asyncio.run(
        collector.collect(ORIGIN, DESTINATION, max_candidates=5)
    )

    assert result == [route]
    assert collector.selected_source == "tmap_transit"
    assert collector.source_errors == {
        "odsay": "CollectorError: ODsay 한도 초과"
    }


def test_transit_provider_hedges_slow_odsay_with_tmap(monkeypatch):
    route = RouteCandidate(
        source="tmap_transit",
        path=[ORIGIN, DESTINATION],
        duration_min=12,
        distance_m=3000,
    )
    odsay_started = asyncio.Event()
    odsay_cancelled = asyncio.Event()

    async def odsay_collect(_self, *_args, **_kwargs):
        odsay_started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            odsay_cancelled.set()
            raise

    async def tmap_collect(_self, *_args, **_kwargs):
        assert odsay_started.is_set()
        return [route]

    monkeypatch.setattr(settings, "TRANSIT_PROVIDER_ORDER", "odsay,tmap")
    monkeypatch.setattr(settings, "TRANSIT_PROVIDER_HEDGE_SECONDS", 0.01)
    monkeypatch.setattr(
        settings,
        "TRANSIT_PROVIDER_TOTAL_TIMEOUT_SECONDS",
        1.0,
    )
    monkeypatch.setattr(OdsayRouteCollector, "collect", odsay_collect)
    monkeypatch.setattr(TmapTransitRouteCollector, "collect", tmap_collect)

    collector = TransitProviderCollector()
    result = asyncio.run(
        collector.collect(ORIGIN, DESTINATION, max_candidates=5)
    )

    assert result == [route]
    assert odsay_cancelled.is_set()
    assert collector.attempted_sources == ["odsay", "tmap_transit"]
    assert collector.selected_source == "tmap_transit"


def test_transit_provider_keeps_odsay_when_it_finishes_inside_hedge(monkeypatch):
    route = RouteCandidate(
        source="odsay",
        path=[ORIGIN, DESTINATION],
        duration_min=11,
        distance_m=2900,
    )
    tmap_calls = 0

    async def odsay_collect(_self, *_args, **_kwargs):
        return [route]

    async def tmap_collect(_self, *_args, **_kwargs):
        nonlocal tmap_calls
        tmap_calls += 1
        return []

    monkeypatch.setattr(settings, "TRANSIT_PROVIDER_ORDER", "odsay,tmap")
    monkeypatch.setattr(settings, "TRANSIT_PROVIDER_HEDGE_SECONDS", 0.1)
    monkeypatch.setattr(OdsayRouteCollector, "collect", odsay_collect)
    monkeypatch.setattr(TmapTransitRouteCollector, "collect", tmap_collect)

    collector = TransitProviderCollector()
    result = asyncio.run(
        collector.collect(ORIGIN, DESTINATION, max_candidates=5)
    )

    assert result == [route]
    assert tmap_calls == 0
    assert collector.attempted_sources == ["odsay"]
    assert collector.selected_source == "odsay"


def test_transit_provider_bounds_both_slow_providers(monkeypatch):
    async def never_returns(_self, *_args, **_kwargs):
        await asyncio.Event().wait()

    monkeypatch.setattr(settings, "TRANSIT_PROVIDER_ORDER", "odsay,tmap")
    monkeypatch.setattr(settings, "TRANSIT_PROVIDER_HEDGE_SECONDS", 0.01)
    monkeypatch.setattr(
        settings,
        "TRANSIT_PROVIDER_TOTAL_TIMEOUT_SECONDS",
        0.05,
    )
    monkeypatch.setattr(OdsayRouteCollector, "collect", never_returns)
    monkeypatch.setattr(TmapTransitRouteCollector, "collect", never_returns)

    collector = TransitProviderCollector()
    with pytest.raises(CollectorError) as captured:
        asyncio.run(
            collector.collect(ORIGIN, DESTINATION, max_candidates=5)
        )

    assert captured.value.code == "timeout"
    assert collector.attempted_sources == ["odsay", "tmap_transit"]
    assert "전체 수집 제한시간" in str(captured.value)


@pytest.mark.parametrize("value", ["", "odsay,odsay", "unknown"])
def test_transit_provider_order_rejects_invalid_configuration(value):
    with pytest.raises(ValueError):
        provider_order(value)
