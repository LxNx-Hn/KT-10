"""
경로 수집기 테스트. API 키 미설정 시 플레이스홀더 반환, OSMnx 실패 시 fallback을 검증한다.

ai/.env 에 실제 키가 설정돼 있어도 결과가 흔들리지 않도록,
settings의 키 값은 monkeypatch로 강제 고정한다 (환경 비의존).
"""
import asyncio

from collectors.base import Coordinate
from collectors.odsay_collector import OdsayRouteCollector
from collectors.osmnx_collector import OsmnxRouteCollector
from collectors.tmap_collector import TmapRouteCollector
from config import settings

ORIGIN = Coordinate(lat=35.1626, lng=129.0530)
DEST = Coordinate(lat=35.1578, lng=129.0594)


def test_odsay_placeholder_without_api_key(monkeypatch):
    """ODSAY_API_KEY 미설정 시 플레이스홀더 후보 1개를 반환해야 한다."""
    monkeypatch.setattr(settings, "ODSAY_API_KEY", "")
    result = asyncio.run(OdsayRouteCollector().collect(ORIGIN, DEST))
    assert len(result) == 1
    assert result[0].source == "odsay"
    assert result[0].path == [ORIGIN, DEST]


def test_tmap_placeholder_without_api_key(monkeypatch):
    """TMAP_API_KEY 미설정 시 플레이스홀더 후보 1개를 반환해야 한다."""
    monkeypatch.setattr(settings, "TMAP_API_KEY", "")
    result = asyncio.run(TmapRouteCollector().collect(ORIGIN, DEST))
    assert len(result) == 1
    assert result[0].source == "tmap"
    assert result[0].path == [ORIGIN, DEST]


def test_osmnx_fallback_when_graph_unavailable(monkeypatch):
    """그래프 로딩/계산 실패 시에도 최소 1개의 직선 경로 플레이스홀더를 반환해야 한다."""
    import collectors.osmnx_collector as osmnx_collector

    def _raise(*args, **kwargs):
        raise RuntimeError("network unavailable in test environment")

    monkeypatch.setattr(osmnx_collector, "_get_graph_for_route", _raise)

    result = asyncio.run(OsmnxRouteCollector().collect(ORIGIN, DEST))
    assert len(result) == 1
    assert result[0].source == "osmnx"
    assert result[0].path == [ORIGIN, DEST]


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

    monkeypatch.setattr(osmnx_collector, "_get_graph_for_route", lambda *args, **kwargs: G)

    result = asyncio.run(OsmnxRouteCollector().collect(ORIGIN, DEST))
    assert len(result) == 1
    assert result[0].source == "osmnx"
    assert result[0].raw_response is None
    assert result[0].distance_m == 240.0  # 90(최단 병렬 간선) + 150
