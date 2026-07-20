"""
경로 수집기 테스트. 키 누락·공급자 실패가 가짜 경로로 위장되지 않는지 검증한다.

ai/.env 에 실제 키가 설정돼 있어도 결과가 흔들리지 않도록,
settings의 키 값은 monkeypatch로 강제 고정한다 (환경 비의존).
"""
import asyncio

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


def test_odsay_collect_uses_search_and_load_lane_contract(monkeypatch):
    import collectors.odsay_collector as module

    search_payload = {"result": {"path": [{
        "info": {"totalTime": 20, "totalDistance": 5000, "totalWalk": 100, "mapObj": "126:35@100:1:1:2"},
        "subPath": [{
            "trafficType": 2, "sectionTime": 18, "distance": 4900,
            "startName": "부산역", "endName": "서면역", "lane": [{"busNo": "100"}],
        }],
    }]}}
    lane_payload = {"result": {"lane": [{"section": [{"graphPos": [
        {"x": 3.04, "y": 0.115}, {"x": 3.059, "y": 0.157},
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
