"""부산진구 보행자 도로망 그래프를 OSMnx로 구축하고 캐싱한다.

카카오맵 API는 도로망 그래프를 제공하지 않으므로, 경로 탐색 알고리즘이 동작할
그래프는 이 모듈이 OSMnx를 통해 OpenStreetMap에서 직접 가져와 구축한다.
카카오맵은 화면 렌더링과 좌표 제공(geocoding)에만 쓰이며, 이 그래프와는
독립적인 레이어이다 — 연결점은 "좌표값"뿐이다.

최초 1회 구축 후 GraphML 파일로 캐싱하여, 매 요청마다 OSM에서 재다운로드하지 않는다.
"""
import logging

import networkx as nx
import osmnx as ox
from pathlib import Path

log = logging.getLogger(__name__)

CACHE_DIR = Path(__file__).parent / "cache"
CACHE_PATH = CACHE_DIR / "busanjin_walk.graphml"

# 부산진구 행정구역 경계 기준으로 보행자 전용 그래프 구축
PLACE_NAME = "Busanjin-gu, Busan, South Korea"


def build_or_load_graph() -> nx.MultiDiGraph:
    """캐시가 있으면 로드하고, 없으면 OSMnx로 새로 구축 후 캐싱한다."""
    if CACHE_PATH.exists():
        log.info("캐시된 그래프 로드: %s", CACHE_PATH)
        return ox.load_graphml(CACHE_PATH)

    log.info("OSMnx로 부산진구 보행자 그래프 구축 중... (최초 1회, 수 분 소요)")
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    graph = ox.graph_from_place(PLACE_NAME, network_type="walk")

    # TODO: 경사도 부여 — DEM 데이터 연동 후 ox.elevation.add_node_elevations_raster() 적용
    # TODO: 계단/인도폭 속성 부여 — V-World 인도 SHP 등 연동 후 엣지 속성 추가

    ox.save_graphml(graph, CACHE_PATH)
    log.info("그래프 캐싱 완료: %s (노드 %d개)", CACHE_PATH, len(graph.nodes))
    return graph


def find_nearest_node(graph: nx.MultiDiGraph, lat: float, lng: float) -> int:
    """카카오맵에서 받은 좌표(lat, lng)를 그래프의 가장 가까운 노드로 스냅한다.

    이 함수가 카카오맵 좌표계와 OSMnx 그래프를 잇는 유일한 접점이다.
    OSMnx는 경도(X)·위도(Y) 순서로 받으므로 주의한다.
    """
    return ox.nearest_nodes(graph, X=lng, Y=lat)
