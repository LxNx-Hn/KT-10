"""경로 수집기 테스트. API 키 미설정 시 플레이스홀더 반환, OSMnx 실패 시 fallback을 검증한다."""
import asyncio

from collectors.base import Coordinate
from collectors.odsay_collector import OdsayRouteCollector
from collectors.osmnx_collector import OsmnxRouteCollector
from collectors.tmap_collector import TmapRouteCollector

ORIGIN = Coordinate(lat=35.1626, lng=129.0530)
DEST = Coordinate(lat=35.1578, lng=129.0594)


def test_odsay_placeholder_without_api_key():
    """ODSAY_API_KEY 미설정 시 플레이스홀더 후보 1개를 반환해야 한다."""
    result = asyncio.run(OdsayRouteCollector().collect(ORIGIN, DEST))
    assert len(result) == 1
    assert result[0].source == "odsay"
    assert result[0].path == [ORIGIN, DEST]


def test_tmap_placeholder_without_api_key():
    """TMAP_API_KEY 미설정 시 플레이스홀더 후보 1개를 반환해야 한다."""
    result = asyncio.run(TmapRouteCollector().collect(ORIGIN, DEST))
    assert len(result) == 1
    assert result[0].source == "tmap"
    assert result[0].path == [ORIGIN, DEST]


def test_osmnx_fallback_when_graph_unavailable(monkeypatch):
    """그래프 로딩/계산 실패 시에도 최소 1개의 직선 경로 플레이스홀더를 반환해야 한다."""
    import collectors.osmnx_collector as osmnx_collector

    def _raise(*args, **kwargs):
        raise RuntimeError("network unavailable in test environment")

    monkeypatch.setattr(osmnx_collector, "_get_graph", _raise)

    result = asyncio.run(OsmnxRouteCollector().collect(ORIGIN, DEST))
    assert len(result) == 1
    assert result[0].source == "osmnx"
    assert result[0].path == [ORIGIN, DEST]
