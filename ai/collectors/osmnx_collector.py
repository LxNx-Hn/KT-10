"""
OSMnx 직접 계산 수집기 (fallback).

외부 API 상태와 무관하게 항상 최소 1개 경로를 보장한다.
출발지·도착지를 포함하는 권역의 보행자 도로망 그래프를 ai/data/cache/ 에
경계값 기준으로 캐싱하여 같은 권역 재요청 시 다운로드를 생략한다.
"""
from itertools import islice
from pathlib import Path

import networkx as nx
import osmnx as ox

from collectors.base import BaseRouteCollector, RouteCandidate, Coordinate

GRAPH_CACHE_DIR = Path("ai/data/cache")


def _get_graph_for_route(origin: Coordinate, dest: Coordinate):
    """
    출발지·도착지를 포함하는 범위의 보행자 도로망 그래프를 반환한다.

    bounding box(north/south/east/west)로 범위를 동적으로 결정.
    PAD=0.01도(~1km) 여유를 줘서 경계 근처 노드 누락 방지.
    캐시 키는 경계값 소수점 2자리 반올림 — 같은 권역이면 캐시 재사용.

    MultiDiGraph → DiGraph 변환은 여기서 하지 않는다: ox.save_graphml()은
    MultiDiGraph만 저장 가능하고 ox.load_graphml()도 항상 MultiDiGraph를
    반환하므로, 변환은 collect()에서 매번 일괄 처리한다.
    """
    PAD = 0.01

    north = max(origin.lat, dest.lat) + PAD
    south = min(origin.lat, dest.lat) - PAD
    east  = max(origin.lng, dest.lng) + PAD
    west  = min(origin.lng, dest.lng) - PAD

    cache_key  = f"{round(north,2)}_{round(south,2)}_{round(east,2)}_{round(west,2)}"
    cache_path = GRAPH_CACHE_DIR / f"walk_{cache_key}.graphml"

    if cache_path.exists():
        return ox.load_graphml(cache_path)

    G = ox.graph_from_bbox(
        bbox=(north, south, east, west),
        network_type="walk",
    )

    cache_path.parent.mkdir(parents=True, exist_ok=True)
    ox.save_graphml(G, cache_path)
    return G


class OsmnxRouteCollector(BaseRouteCollector):
    source_name = "osmnx"

    async def collect(self, origin: Coordinate, destination: Coordinate) -> list:
        """항상 최소 1개 경로 반환. 그래프 실패 시 직선 경로 플레이스홀더."""
        try:
            G = _get_graph_for_route(origin, destination)
            o_node = ox.nearest_nodes(G, X=origin.lng,      Y=origin.lat)
            d_node = ox.nearest_nodes(G, X=destination.lng, Y=destination.lat)

            # shortest_simple_paths는 MultiDiGraph를 지원하지 않으므로
            # 병렬 간선 중 최단 거리만 남긴 DiGraph로 변환한다.
            DG = ox.convert.to_digraph(G, weight="length")
            paths = list(islice(
                nx.shortest_simple_paths(DG, o_node, d_node, weight="length"), 3
            ))
            candidates = []
            for path_nodes in paths:
                coords = [Coordinate(lat=G.nodes[n]["y"], lng=G.nodes[n]["x"]) for n in path_nodes]
                dist   = sum(DG[path_nodes[i]][path_nodes[i + 1]].get("length", 0)
                             for i in range(len(path_nodes) - 1))
                candidates.append(RouteCandidate(
                    source=self.source_name, path=coords,
                    duration_min=dist / 67, distance_m=dist,
                ))
            return candidates
        except Exception:
            return [RouteCandidate(
                source=self.source_name,
                path=[origin, destination],
                duration_min=0, distance_m=0,
                raw_response={"note": "OSMnx fallback — placeholder"},
            )]
