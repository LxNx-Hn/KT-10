"""
OSMnx 직접 계산 보행 경로 수집기.

OD를 포함하는 동적 경계의 보행 그래프를 캐시하며, 실패를 직선 경로로 위장하지 않는다.
"""
from itertools import islice
from hashlib import sha256
from pathlib import Path
import asyncio

import networkx as nx
import osmnx as ox

from collectors.base import BaseRouteCollector, CollectorError, RouteCandidate, Coordinate

GRAPH_CACHE_DIR = Path("ai/data/cache/osmnx")
_graphs: dict[str, object] = {}


def _graph_key(origin: Coordinate, destination: Coordinate) -> str:
    bounds = tuple(round(value, 3) for value in (origin.lat, origin.lng, destination.lat, destination.lng))
    return sha256(repr(bounds).encode("ascii")).hexdigest()[:16]


def _get_graph(origin: Coordinate, destination: Coordinate):
    key = _graph_key(origin, destination)
    if key in _graphs:
        return _graphs[key]
    graph_cache = GRAPH_CACHE_DIR / f"{key}.graphml"
    if graph_cache.exists():
        graph = ox.load_graphml(graph_cache)
    else:
        GRAPH_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        margin = 0.0045  # 약 500m
        north = max(origin.lat, destination.lat) + margin
        south = min(origin.lat, destination.lat) - margin
        east = max(origin.lng, destination.lng) + margin
        west = min(origin.lng, destination.lng) - margin
        graph = ox.graph.graph_from_bbox(
            (west, south, east, north), network_type="walk", retain_all=True
        )
        ox.save_graphml(graph, graph_cache)
    _graphs[key] = graph
    return graph


class OsmnxRouteCollector(BaseRouteCollector):
    source_name = "osmnx"

    async def collect(self, origin: Coordinate, destination: Coordinate) -> list:
        """OD 동적 보행 그래프에서 최대 3개 실제 네트워크 선형을 반환한다.

        OSM 도로 그래프에는 보행 소요시간이 없다. 사용자별 보행속도 정책이
        확정되기 전까지 시간을 임의 환산하지 않고 ``None``으로 유지한다.
        이 수집기는 ODsay 보행 구간의 geometry 보완에만 사용한다.
        """
        try:
            G = await asyncio.to_thread(_get_graph, origin, destination)
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
                edge_lengths = [DG[path_nodes[i]][path_nodes[i + 1]].get("length")
                                for i in range(len(path_nodes) - 1)]
                if not edge_lengths or any(length is None for length in edge_lengths):
                    raise CollectorError("OSM 보행 그래프 간선에 거리 정보가 없습니다.")
                dist = sum(float(length) for length in edge_lengths)
                if dist <= 0:
                    raise CollectorError("OSM 보행 경로 거리가 유효하지 않습니다.")
                candidates.append(RouteCandidate(
                    source=self.source_name, path=coords,
                    duration_min=None, distance_m=dist,
                ))
            return candidates
        except Exception as exc:
            raise CollectorError(f"OSMnx 보행 경로 계산 실패: {type(exc).__name__}") from exc
