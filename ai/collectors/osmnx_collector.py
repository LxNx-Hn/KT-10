"""
OSMnx 직접 계산 보행 경로 수집기.

OD를 포함하는 동적 경계의 보행 그래프를 캐시하며, 실패를 직선 경로로 위장하지 않는다.
"""
import asyncio
import logging
from hashlib import sha256
from pathlib import Path
from threading import BoundedSemaphore, Lock
from typing import NamedTuple
from weakref import WeakKeyDictionary

import networkx as nx
import numpy as np
import osmnx as ox
from config import settings
from scipy.sparse import csr_matrix
from scipy.sparse.csgraph import dijkstra
from sklearn.neighbors import BallTree

from collectors.base import (
    BaseRouteCollector,
    CollectorError,
    Coordinate,
    RouteCandidate,
)

GRAPH_CACHE_DIR = Path(__file__).resolve().parents[1] / "data" / "cache" / "osmnx"
_graphs: dict[str, object] = {}
_digraphs: WeakKeyDictionary = WeakKeyDictionary()
_routing_indexes: WeakKeyDictionary = WeakKeyDictionary()
_graph_locks: dict[str, Lock] = {}
_graph_locks_guard = Lock()
_overpass_slots = BoundedSemaphore(2)
_warm_tasks: set[asyncio.Task] = set()
_warming_keys: set[str] = set()
_warming_keys_guard = Lock()
log = logging.getLogger("collectors.osmnx")

# Overpass 기본 status endpoint가 일부 실행 환경에서 406을 반환하면 OSMnx가
# 매 요청마다 안전 대기값 60초를 적용한다. 이 서비스는 보행 구간을 순차
# 조회하며 자체 시간 제한을 두므로 자동 slot 조회를 끄고, 식별 가능한
# User-Agent와 앱 사용자가 쓸 수 있는 캐시 경로를 명시한다.
ox.settings.overpass_rate_limit = False
ox.settings.overpass_url = str(settings.OSMNX_OVERPASS_URL).rstrip("/")
ox.settings.requests_timeout = settings.OSMNX_REQUEST_TIMEOUT_SECONDS
ox.settings.http_user_agent = "KT-10-accessible-routing/1.0"
ox.settings.cache_folder = GRAPH_CACHE_DIR / "http"


class RoutingIndex(NamedTuple):
    node_ids: np.ndarray
    nearest_tree: BallTree
    node_positions: dict[object, int]
    adjacency: csr_matrix


def _graph_lock(key: str) -> Lock:
    with _graph_locks_guard:
        return _graph_locks.setdefault(key, Lock())


def _graph_key(origin: Coordinate, destination: Coordinate) -> str:
    bounds = tuple(round(value, 3) for value in (origin.lat, origin.lng, destination.lat, destination.lng))
    return sha256(repr(bounds).encode("ascii")).hexdigest()[:16]


def _graph_cache_path(key: str) -> Path:
    return GRAPH_CACHE_DIR / f"{key}.graphml"


def _regional_graph_path() -> Path:
    return GRAPH_CACHE_DIR / "busan-walk.graphml"


def _load_cached_graph(origin: Coordinate, destination: Coordinate):
    if _regional_graph_path().exists():
        return _load_regional_graph()
    key = _graph_key(origin, destination)
    with _graph_lock(key):
        if key in _graphs:
            return _graphs[key]
        graph_cache = _graph_cache_path(key)
        if not graph_cache.exists():
            raise FileNotFoundError(key)
        graph = ox.load_graphml(graph_cache)
        _graphs[key] = graph
        return graph


def _load_regional_graph():
    key = "busan-regional-walk"
    with _graph_lock(key):
        if key not in _graphs:
            graph = nx.read_graphml(
                _regional_graph_path(),
                node_type=int,
                force_multigraph=False,
            )
            if not graph.is_directed() or graph.is_multigraph():
                raise ValueError("부산 보행 GraphML이 단일 방향 그래프가 아닙니다.")
            for node_id, data in graph.nodes(data=True):
                try:
                    data["x"] = float(data["x"])
                    data["y"] = float(data["y"])
                except (KeyError, TypeError, ValueError) as exc:
                    raise ValueError(
                        f"부산 보행 GraphML 노드 {node_id} 좌표가 올바르지 않습니다."
                    ) from exc
            for start, end, data in graph.edges(data=True):
                try:
                    data["length"] = float(data["length"])
                except (KeyError, TypeError, ValueError) as exc:
                    raise ValueError(
                        "부산 보행 GraphML 간선 "
                        f"{start}->{end} 길이가 올바르지 않습니다."
                    ) from exc
            graph.graph["crs"] = "EPSG:4326"
            _graphs[key] = graph
        return _graphs[key]


def _routing_index(digraph):
    """양방향 도달 가능한 보행망과 최근접 노드 인덱스를 한 번만 만든다."""
    graph_identity = id(digraph)
    with _graph_lock(f"routing-index-{graph_identity}"):
        cached = _routing_indexes.get(digraph)
        if cached is not None:
            return cached
        connected_nodes = max(
            nx.strongly_connected_components(digraph),
            key=len,
            default=set(),
        )
        if len(connected_nodes) < 2:
            raise nx.NetworkXNoPath(
                "연결된 OSM 보행 도로망을 찾을 수 없습니다."
            )
        node_ids = np.asarray(tuple(connected_nodes), dtype=object)
        radians = np.radians(np.asarray([
            (
                float(digraph.nodes[node]["y"]),
                float(digraph.nodes[node]["x"]),
            )
            for node in node_ids
        ]))
        node_positions = {
            node: position
            for position, node in enumerate(node_ids)
        }
        connected_graph = digraph.subgraph(connected_nodes)
        edge_count = connected_graph.number_of_edges()
        rows = np.fromiter(
            (
                node_positions[start]
                for start, _, _ in connected_graph.edges(data=True)
            ),
            dtype=np.int32,
            count=edge_count,
        )
        columns = np.fromiter(
            (
                node_positions[end]
                for _, end, _ in connected_graph.edges(data=True)
            ),
            dtype=np.int32,
            count=edge_count,
        )
        lengths = np.fromiter(
            (
                float(data["length"])
                for _, _, data in connected_graph.edges(data=True)
            ),
            dtype=np.float64,
            count=edge_count,
        )
        if np.any(~np.isfinite(lengths)) or np.any(lengths <= 0):
            raise ValueError("OSM 보행 그래프 간선 길이가 올바르지 않습니다.")
        adjacency = csr_matrix(
            (lengths, (rows, columns)),
            shape=(len(node_ids), len(node_ids)),
        )
        adjacency.sum_duplicates()
        adjacency.sort_indices()
        index = RoutingIndex(
            node_ids=node_ids,
            nearest_tree=BallTree(radians, metric="haversine"),
            node_positions=node_positions,
            adjacency=adjacency,
        )
        _routing_indexes[digraph] = index
        return index


def _nearest_connected_nodes(
    digraph,
    origin: Coordinate,
    destination: Coordinate,
) -> tuple[object, object]:
    index = _routing_index(digraph)
    query = np.radians(np.asarray([
        (origin.lat, origin.lng),
        (destination.lat, destination.lng),
    ]))
    neighbor_count = min(2, len(index.node_ids))
    _, indexes = index.nearest_tree.query(query, k=neighbor_count)
    origin_node = index.node_ids[indexes[0][0]]
    destination_node = index.node_ids[indexes[1][0]]
    if origin_node == destination_node:
        destination_node = index.node_ids[indexes[1][1]]
    return origin_node, destination_node


def _shortest_path(
    index: RoutingIndex,
    origin_node: object,
    destination_node: object,
) -> list[object]:
    origin_position = index.node_positions[origin_node]
    destination_position = index.node_positions[destination_node]
    distances, predecessors = dijkstra(
        index.adjacency,
        directed=True,
        indices=origin_position,
        return_predecessors=True,
    )
    if not np.isfinite(distances[destination_position]):
        raise nx.NetworkXNoPath(
            "연결된 OSM 보행 경로를 찾을 수 없습니다."
        )
    path_positions = [destination_position]
    current = destination_position
    while current != origin_position:
        current = int(predecessors[current])
        if current < 0 or len(path_positions) > len(index.node_ids):
            raise nx.NetworkXNoPath(
                "OSM 보행 경로 선행 노드를 복원할 수 없습니다."
            )
        path_positions.append(current)
    path_positions.reverse()
    return [index.node_ids[position] for position in path_positions]


def prepare_regional_graph() -> dict[str, int] | None:
    """지역 GraphML이 있으면 요청 전에 메모리에 적재해 첫 호출 지연을 없앤다."""
    if not _regional_graph_path().exists():
        return None
    graph = _load_regional_graph()
    index = _routing_index(graph)
    return {
        "nodes": graph.number_of_nodes(),
        "edges": graph.number_of_edges(),
        "routable_nodes": len(index.node_ids),
    }


def _get_graph(origin: Coordinate, destination: Coordinate):
    if _regional_graph_path().exists():
        return _load_regional_graph()
    key = _graph_key(origin, destination)
    with _graph_lock(key):
        if key in _graphs:
            return _graphs[key]
        graph_cache = _graph_cache_path(key)
        if graph_cache.exists():
            graph = ox.load_graphml(graph_cache)
        else:
            # 요청 경로는 이 함수를 기다리지 않는다. 백그라운드 사전계산
            # 작업은 slot이 빌 때까지 대기해 뒤쪽 구간이 누락되지 않게 한다.
            _overpass_slots.acquire()
            try:
                GRAPH_CACHE_DIR.mkdir(parents=True, exist_ok=True)
                margin = 0.0045  # 약 500m
                north = max(origin.lat, destination.lat) + margin
                south = min(origin.lat, destination.lat) - margin
                east = max(origin.lng, destination.lng) + margin
                west = min(origin.lng, destination.lng) - margin
                graph = ox.graph.graph_from_bbox(
                    (west, south, east, north),
                    network_type="walk",
                    retain_all=True,
                )
                temporary_cache = GRAPH_CACHE_DIR / f"{key}.tmp.graphml"
                ox.save_graphml(graph, temporary_cache)
                temporary_cache.replace(graph_cache)
            finally:
                _overpass_slots.release()
        _graphs[key] = graph
        return graph


async def _warm_graph(
    key: str,
    origin: Coordinate,
    destination: Coordinate,
) -> None:
    try:
        await asyncio.to_thread(_get_graph, origin, destination)
    except Exception as exc:
        log.warning("OSMnx 보행 그래프 백그라운드 준비 실패 (%s)", type(exc).__name__)
    finally:
        with _warming_keys_guard:
            _warming_keys.discard(key)


def _schedule_graph_warm(
    origin: Coordinate,
    destination: Coordinate,
) -> None:
    key = _graph_key(origin, destination)
    with _warming_keys_guard:
        if key in _warming_keys or _graph_cache_path(key).exists():
            return
        _warming_keys.add(key)
    task = asyncio.create_task(_warm_graph(key, origin, destination))
    _warm_tasks.add(task)
    task.add_done_callback(_warm_tasks.discard)


def _route_candidates_from_graph(
    graph,
    origin: Coordinate,
    destination: Coordinate,
) -> list[RouteCandidate]:
    # 병렬 간선 중 최단 거리만 남긴 DiGraph로 변환한다.
    if graph.is_directed() and not graph.is_multigraph():
        digraph = graph
    else:
        graph_identity = id(graph)
        with _graph_lock(f"digraph-{graph_identity}"):
            digraph = _digraphs.get(graph)
            if digraph is None:
                digraph = ox.convert.to_digraph(graph, weight="length")
                _digraphs[graph] = digraph
    o_node, d_node = _nearest_connected_nodes(
        digraph,
        origin,
        destination,
    )
    paths = [_shortest_path(
        _routing_index(digraph),
        o_node,
        d_node,
    )]
    candidates = []
    for path_nodes in paths:
        coords = [
            Coordinate(lat=graph.nodes[node]["y"], lng=graph.nodes[node]["x"])
            for node in path_nodes
        ]
        edge_lengths = [
            digraph[path_nodes[index]][path_nodes[index + 1]].get("length")
            for index in range(len(path_nodes) - 1)
        ]
        if not edge_lengths or any(length is None for length in edge_lengths):
            raise CollectorError("OSM 보행 그래프 간선에 거리 정보가 없습니다.")
        distance_m = sum(float(length) for length in edge_lengths)
        if distance_m <= 0:
            raise CollectorError("OSM 보행 경로 거리가 유효하지 않습니다.")
        candidates.append(RouteCandidate(
            source="osmnx",
            path=coords,
            duration_min=None,
            distance_m=distance_m,
        ))
    return candidates


class OsmnxRouteCollector(BaseRouteCollector):
    source_name = "osmnx"

    async def collect_cached_or_schedule(
        self,
        origin: Coordinate,
        destination: Coordinate,
    ) -> list[RouteCandidate]:
        """요청 경로에서는 디스크 캐시만 사용하고 누락 그래프는 백그라운드 준비한다."""
        try:
            graph = await asyncio.to_thread(
                _load_cached_graph,
                origin,
                destination,
            )
        except FileNotFoundError as exc:
            _schedule_graph_warm(origin, destination)
            raise CollectorError("OSMnx 보행 그래프를 백그라운드에서 준비 중입니다.") from exc
        try:
            return await asyncio.to_thread(
                _route_candidates_from_graph,
                graph,
                origin,
                destination,
            )
        except Exception as exc:
            raise CollectorError(
                f"OSMnx 보행 경로 계산 실패: {type(exc).__name__}"
            ) from exc

    async def collect(self, origin: Coordinate, destination: Coordinate) -> list:
        """OD 보행 그래프에서 최단 실제 네트워크 선형을 반환한다.

        OSM 도로 그래프에는 보행 소요시간이 없다. 사용자별 보행속도 정책이
        확정되기 전까지 시간을 임의 환산하지 않고 ``None``으로 유지한다.
        이 수집기는 ODsay 보행 구간의 geometry 보완에만 사용한다.
        """
        try:
            G = await asyncio.wait_for(
                asyncio.to_thread(_get_graph, origin, destination),
                timeout=settings.OSMNX_WALK_GEOMETRY_TIMEOUT_SECONDS,
            )
            return await asyncio.to_thread(
                _route_candidates_from_graph,
                G,
                origin,
                destination,
            )
        except Exception as exc:
            raise CollectorError(f"OSMnx 보행 경로 계산 실패: {type(exc).__name__}") from exc
