"""
OSMnx 직접 계산 수집기 (fallback).

외부 API 상태와 무관하게 항상 최소 1개 경로를 보장한다.
부산진구 보행자 도로망 그래프를 ai/data/cache/ 에 캐싱하여 최초 1회만 다운로드.
"""
from itertools import islice
from pathlib import Path

import networkx as nx
import osmnx as ox

from collectors.base import BaseRouteCollector, RouteCandidate, Coordinate

GRAPH_CACHE = Path("ai/data/cache/busanjin_walk.graphml")
_graph = None


def _get_graph():
    global _graph
    if _graph is not None:
        return _graph
    if GRAPH_CACHE.exists():
        _graph = ox.load_graphml(GRAPH_CACHE)
    else:
        GRAPH_CACHE.parent.mkdir(parents=True, exist_ok=True)
        _graph = ox.graph_from_place("Busanjin-gu, Busan, South Korea", network_type="walk")
        ox.save_graphml(_graph, GRAPH_CACHE)
    return _graph


class OsmnxRouteCollector(BaseRouteCollector):
    source_name = "osmnx"

    async def collect(self, origin: Coordinate, destination: Coordinate) -> list:
        """항상 최소 1개 경로 반환. 그래프 실패 시 직선 경로 플레이스홀더."""
        try:
            G = _get_graph()
            o_node = ox.nearest_nodes(G, X=origin.lng,      Y=origin.lat)
            d_node = ox.nearest_nodes(G, X=destination.lng, Y=destination.lat)

            paths = list(islice(
                nx.shortest_simple_paths(G, o_node, d_node, weight="length"), 3
            ))
            candidates = []
            for path_nodes in paths:
                coords = [Coordinate(lat=G.nodes[n]["y"], lng=G.nodes[n]["x"]) for n in path_nodes]
                dist   = sum(G[path_nodes[i]][path_nodes[i + 1]][0].get("length", 0)
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
