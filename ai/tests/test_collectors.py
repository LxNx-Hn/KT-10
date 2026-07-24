"""
경로 수집기 테스트. 키 누락·공급자 실패가 가짜 경로로 위장되지 않는지 검증한다.

ai/.env 에 실제 키가 설정돼 있어도 결과가 흔들리지 않도록,
settings의 키 값은 monkeypatch로 강제 고정한다 (환경 비의존).
"""
import asyncio
from types import SimpleNamespace

import pytest

from collectors.base import CollectorError, CollectorNotConfigured, Coordinate
from collectors.odsay_collector import OdsayRouteCollector
from collectors.osmnx_collector import OsmnxRouteCollector
from collectors.tmap_collector import TmapRouteCollector
from config import settings

ORIGIN = Coordinate(lat=35.1626, lng=129.0530)
DEST = Coordinate(lat=35.1578, lng=129.0594)


def test_odsay_fails_explicitly_without_api_key(monkeypatch):
    monkeypatch.setattr(settings, "ODSAY_API_KEY", "")
    with pytest.raises(CollectorNotConfigured):
        asyncio.run(OdsayRouteCollector().collect(ORIGIN, DEST))


def test_tmap_fails_explicitly_without_api_key(monkeypatch):
    monkeypatch.setattr(settings, "TMAP_API_KEY", "")
    with pytest.raises(CollectorNotConfigured):
        asyncio.run(TmapRouteCollector().collect(ORIGIN, DEST))


def test_odsay_walk_geometry_defaults_to_estimated_without_provider(monkeypatch):
    monkeypatch.setattr(settings, "TMAP_API_KEY", "")
    monkeypatch.setattr(settings, "OSMNX_WALK_GEOMETRY_ENABLED", False)

    path, quality = asyncio.run(OdsayRouteCollector._walk_geometry(ORIGIN, DEST))

    assert path == [ORIGIN, DEST]
    assert quality == "estimated"


def test_odsay_walk_geometry_prefers_tmap(monkeypatch):
    async def tmap_collect(_self, _start, _end):
        return [SimpleNamespace(path=[ORIGIN, DEST])]

    async def osmnx_collect(_self, _start, _end):
        raise AssertionError("TMAP 성공 후 OSMnx를 호출하면 안 됩니다.")

    monkeypatch.setattr(settings, "TMAP_API_KEY", "test-key")
    monkeypatch.setattr(settings, "OSMNX_WALK_GEOMETRY_ENABLED", True)
    monkeypatch.setattr(TmapRouteCollector, "collect", tmap_collect)
    monkeypatch.setattr(OsmnxRouteCollector, "collect", osmnx_collect)

    path, quality = asyncio.run(OdsayRouteCollector._walk_geometry(ORIGIN, DEST))

    assert path == [ORIGIN, DEST]
    assert quality == "exact"


def test_odsay_walk_geometry_uses_osmnx_only_when_enabled(monkeypatch):
    async def osmnx_collect(_self, _start, _end):
        return [SimpleNamespace(path=[ORIGIN, DEST])]

    monkeypatch.setattr(settings, "TMAP_API_KEY", "")
    monkeypatch.setattr(settings, "OSMNX_WALK_GEOMETRY_ENABLED", True)
    monkeypatch.setattr(OsmnxRouteCollector, "collect", osmnx_collect)

    path, quality = asyncio.run(OdsayRouteCollector._walk_geometry(ORIGIN, DEST))

    assert path == [ORIGIN, DEST]
    assert quality == "exact"


def test_odsay_walk_geometry_falls_back_when_enabled_providers_fail(monkeypatch):
    async def fail_collect(_self, _start, _end):
        raise CollectorError("provider unavailable")

    monkeypatch.setattr(settings, "TMAP_API_KEY", "test-key")
    monkeypatch.setattr(settings, "OSMNX_WALK_GEOMETRY_ENABLED", True)
    monkeypatch.setattr(TmapRouteCollector, "collect", fail_collect)
    monkeypatch.setattr(OsmnxRouteCollector, "collect", fail_collect)

    path, quality = asyncio.run(OdsayRouteCollector._walk_geometry(ORIGIN, DEST))

    assert path == [ORIGIN, DEST]
    assert quality == "estimated"


def test_osmnx_fails_explicitly_when_graph_unavailable(monkeypatch):
    import collectors.osmnx_collector as osmnx_collector

    def _raise(*args, **kwargs):
        raise RuntimeError("network unavailable in test environment")

    monkeypatch.setattr(osmnx_collector, "_get_graph", _raise)

    with pytest.raises(CollectorError):
        asyncio.run(OsmnxRouteCollector().collect(ORIGIN, DEST))


def test_osmnx_handles_multidigraph_parallel_edges(monkeypatch):
    """
    OSMnx 그래프는 MultiDiGraph이며 병렬 간선을 가질 수 있다.
    nx.shortest_simple_paths는 MultiDiGraph를 지원하지 않으므로
    DiGraph로 변환하는 처리가 누락되면 NetworkXNotImplemented가 발생한다.
    """
    import networkx as nx
    import collectors.osmnx_collector as osmnx_collector

    G = nx.MultiDiGraph()
    G.add_node(1, x=ORIGIN.lng, y=ORIGIN.lat)
    G.add_node(2, x=129.0560, y=35.1600)
    G.add_node(3, x=DEST.lng, y=DEST.lat)
    G.add_edge(1, 2, length=100.0)
    G.add_edge(1, 2, length=90.0)  # 병렬 간선
    G.add_edge(2, 3, length=150.0)
    G.graph["crs"] = "EPSG:4326"

    monkeypatch.setattr(osmnx_collector, "_get_graph", lambda *_: G)

    result = asyncio.run(OsmnxRouteCollector().collect(ORIGIN, DEST))
    assert len(result) == 1
    assert result[0].source == "osmnx"
    assert result[0].raw_response is None
    assert result[0].distance_m == 240.0  # 90(최단 병렬 간선) + 150
    assert result[0].duration_min is None


def test_odsay_load_lane_restores_map_base():
    """공식 loadLane 응답의 상대 graphPos에 mapObject 기준점을 복원한다."""
    data = {
        "result": {
            "lane": [{
                "section": [{"graphPos": [
                    {"x": 3.0500, "y": 0.1150},
                    {"x": 3.0510, "y": 0.1160},
                ]}]
            }]
        }
    }
    coords = OdsayRouteCollector._lane_coordinates(data, "126:35@71:2:1:2")
    assert coords == [
        Coordinate(lat=35.1150, lng=129.0500),
        Coordinate(lat=35.1160, lng=129.0510),
    ]


def test_odsay_load_lane_keeps_absolute_coordinates():
    data = {"result": {"lane": [{"section": [{"graphPos": [
        {"x": 129.0500, "y": 35.1150}, {"x": 129.0510, "y": 35.1160},
    ]}]}]}}
    coords = OdsayRouteCollector._lane_coordinates(data, "126:35@71:2:1:2")
    assert coords[0] == Coordinate(lat=35.1150, lng=129.0500)


def test_odsay_normalizes_abbreviated_search_map_object():
    assert OdsayRouteCollector._load_lane_map_object("71216:1:17:20") == "0:0@71216:1:17:20"
    assert (
        OdsayRouteCollector._load_lane_map_object(
            "70002:2:70231:70219@70001:2:70119:70113"
        )
        == "0:0@70002:2:70231:70219@70001:2:70119:70113"
    )
    assert (
        OdsayRouteCollector._load_lane_map_object("126:35@100:1:1:2")
        == "126:35@100:1:1:2"
    )


def test_odsay_collect_uses_search_and_load_lane_contract(monkeypatch):
    import collectors.odsay_collector as module

    search_payload = {"result": {"path": [{
        "info": {"totalTime": 20, "totalDistance": 5000, "totalWalk": 100, "mapObj": "100:1:1:2"},
        "subPath": [{
            "trafficType": 2, "sectionTime": 18, "distance": 4900,
            "startName": "부산역", "endName": "서면역", "lane": [{"busNo": "100"}],
        }],
    }]}}
    lane_payload = {"result": {"lane": [{"section": [{"graphPos": [
        {"x": 129.04, "y": 35.115}, {"x": 129.059, "y": 35.157},
    ]}]}]}}

    class Response:
        def __init__(self, payload): self.payload = payload
        def raise_for_status(self): return None
        def json(self): return self.payload

    class Client:
        def __init__(self, *args, **kwargs): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *args): return None
        async def get(self, url, **kwargs):
            if url.endswith("loadLane"):
                assert kwargs["params"]["mapObject"] == "0:0@100:1:1:2"
            return Response(lane_payload if url.endswith("loadLane") else search_payload)

    monkeypatch.setattr(settings, "ODSAY_API_KEY", "test-key")
    monkeypatch.setattr(module.httpx, "AsyncClient", Client)
    result = asyncio.run(OdsayRouteCollector().collect(ORIGIN, DEST))
    assert len(result) == 1
    assert result[0].duration_min == 20
    assert result[0].distance_m == 5000
    assert result[0].geometry_quality == "exact"
    assert result[0].segments[0]["mode"] == "bus"
    assert len(result[0].segments[0]["path"]) == 2


def test_odsay_rejects_malformed_map_object_tokens():
    with pytest.raises(CollectorError, match="노선 토큰"):
        OdsayRouteCollector._load_lane_map_object("malformed")
    with pytest.raises(CollectorError, match="노선 토큰"):
        OdsayRouteCollector._load_lane_map_object("126:35@too:few")


def test_odsay_lane_paths_preserve_empty_lane_position():
    payload = {"result": {"lane": [
        {"section": [{"graphPos": [{"x": "bad", "y": 35.1}]}]},
        {"section": [{"graphPos": [
            {"x": 129.05, "y": 35.11},
            {"x": 129.06, "y": 35.12},
        ]}]},
    ]}}

    paths = OdsayRouteCollector._lane_paths(
        payload,
        "126:35@100:1:1:2@101:1:1:2",
    )

    assert paths[0] == []
    assert paths[1][0] == Coordinate(lat=35.11, lng=129.05)


@pytest.mark.parametrize("invalid_info", [None, [], "malformed"])
def test_odsay_skips_invalid_candidate_and_keeps_next_valid_one(
    monkeypatch,
    invalid_info,
):
    import collectors.odsay_collector as module

    invalid = {
        "info": invalid_info,
        "subPath": [{
            "trafficType": 2,
            "sectionTime": 18,
            "distance": 4900,
        }],
    }
    valid = {
        "info": {
            "totalTime": 20,
            "totalDistance": 5000,
            "mapObj": "101:1:1:2",
        },
        "subPath": [{
            "trafficType": 2,
            "sectionTime": 18,
            "distance": 4900,
        }],
    }
    search_payload = {"result": {"path": [invalid, valid]}}
    lane_payload = {"result": {"lane": [{"section": [{"graphPos": [
        {"x": 129.04, "y": 35.115},
        {"x": 129.059, "y": 35.157},
    ]}]}]}}

    class Response:
        def __init__(self, payload):
            self.payload = payload

        def raise_for_status(self):
            return None

        def json(self):
            return self.payload

    class Client:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def get(self, url, **kwargs):
            return Response(
                lane_payload if url.endswith("loadLane") else search_payload
            )

    monkeypatch.setattr(settings, "ODSAY_API_KEY", "test-key")
    monkeypatch.setattr(module.httpx, "AsyncClient", Client)

    result = asyncio.run(OdsayRouteCollector().collect(ORIGIN, DEST))

    assert len(result) == 1
    assert result[0].duration_min == 20


@pytest.mark.parametrize("malformed_result", [None, [], "malformed"])
def test_odsay_rejects_non_object_result(monkeypatch, malformed_result):
    import collectors.odsay_collector as module

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"result": malformed_result}

    class Client:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def get(self, *_args, **_kwargs):
            return Response()

    monkeypatch.setattr(settings, "ODSAY_API_KEY", "test-key")
    monkeypatch.setattr(module.httpx, "AsyncClient", Client)

    with pytest.raises(CollectorError, match="result가 객체"):
        asyncio.run(OdsayRouteCollector().collect(ORIGIN, DEST))


@pytest.mark.parametrize(
    ("field", "malformed_value"),
    [
        ("geometry", None),
        ("geometry", []),
        ("geometry", "malformed"),
        ("properties", None),
        ("properties", []),
        ("properties", "malformed"),
    ],
)
def test_tmap_rejects_non_object_nested_fields(
    monkeypatch,
    field,
    malformed_value,
):
    import collectors.tmap_collector as module

    feature = {
        "geometry": {
            "type": "LineString",
            "coordinates": [
                [ORIGIN.lng, ORIGIN.lat],
                [DEST.lng, DEST.lat],
            ],
        },
        "properties": {
            "totalTime": 600,
            "totalDistance": 1000,
        },
    }
    feature[field] = malformed_value

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"features": [feature]}

    class Client:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def post(self, *_args, **_kwargs):
            return Response()

    monkeypatch.setattr(settings, "TMAP_API_KEY", "test-key")
    monkeypatch.setattr(module.httpx, "AsyncClient", Client)

    with pytest.raises(CollectorError, match=field):
        asyncio.run(TmapRouteCollector().collect(ORIGIN, DEST))


def test_odsay_rejects_missing_transit_lane_instead_of_shifting_next_lane():
    collector = OdsayRouteCollector()
    path = {
        "info": {
            "totalTime": 20,
            "totalDistance": 5000,
            "mapObj": "100:1:1:2@101:1:1:2",
        },
        "subPath": [
            {"trafficType": 2, "sectionTime": 8, "distance": 2000},
            {"trafficType": 1, "sectionTime": 10, "distance": 2900},
        ],
    }

    async def run():
        async def fake_load_lane(*_args):
            return [
                [],
                [
                    Coordinate(lat=35.12, lng=129.05),
                    Coordinate(lat=35.13, lng=129.06),
                ],
            ]

        collector._load_lane = fake_load_lane
        with pytest.raises(CollectorError, match="bus 구간"):
            await collector._build_candidate(
                object(),
                path,
                ORIGIN,
                DEST,
            )

    asyncio.run(run())
