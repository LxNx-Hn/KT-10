"""
OSMnx 직접 계산 보행 경로 수집기.

OD를 포함하는 동적 경계의 보행 그래프를 캐시하며, 실패를 직선 경로로 위장하지 않는다.
"""
from itertools import islice
from hashlib import sha256
from pathlib import Path
import asyncio
import logging
import math
from threading import BoundedSemaphore, Lock

import networkx as nx
import osmnx as ox

from collectors.base import BaseRouteCollector, CollectorError, RouteCandidate, Coordinate
from config import settings

GRAPH_CACHE_DIR = Path(__file__).resolve().parents[1] / "data" / "cache" / "osmnx"
_graphs: dict[str, object] = {}
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


def _graph_lock(key: str) -> Lock:
    with _graph_locks_guard:
        return _graph_locks.setdefault(key, Lock())


def _graph_key(origin: Coordinate, destination: Coordinate) -> str:
    bounds = tuple(round(value, 3) for value in (origin.lat, origin.lng, destination.lat, destination.lng))
    return sha256(repr(bounds).encode("ascii")).hexdigest()[:16]


def _graph_cache_path(key: str) -> Path:
    return GRAPH_CACHE_DIR / f"{key}.graphml"


def _load_cached_graph(origin: Coordinate, destination: Coordinate):
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


def _get_graph(origin: Coordinate, destination: Coordinate):
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
    o_node = ox.nearest_nodes(graph, X=origin.lng, Y=origin.lat)
    d_node = ox.nearest_nodes(graph, X=destination.lng, Y=destination.lat)

    # shortest_simple_paths는 MultiDiGraph를 지원하지 않으므로
    # 병렬 간선 중 최단 거리만 남긴 DiGraph로 변환한다.
    digraph = ox.convert.to_digraph(graph, weight="length")
    if o_node == d_node or not nx.has_path(digraph, o_node, d_node):
        # retain_all 그래프에서는 출입구·건물 통로처럼 가까운 고립 노드가
        # 좌표 스냅 대상으로 선택될 수 있다. 이때 직선으로 대체하지 않고
        # 가장 큰 왕복 가능 보행망 안에서 양 끝점을 다시 스냅한다.
        connected_nodes = max(
            nx.strongly_connected_components(digraph),
            key=len,
            default=set(),
        )
        if len(connected_nodes) < 2:
            raise nx.NetworkXNoPath(
                "연결된 OSM 보행 도로망을 찾을 수 없습니다."
            )

        def nearest_connected_node(coordinate: Coordinate):
            longitude_scale = math.cos(math.radians(coordinate.lat))
            return min(
                connected_nodes,
                key=lambda node: (
                    (
                        float(digraph.nodes[node]["x"]) - coordinate.lng
                    ) * longitude_scale
                ) ** 2 + (
                    float(digraph.nodes[node]["y"]) - coordinate.lat
                ) ** 2,
            )

        o_node = nearest_connected_node(origin)
        d_node = nearest_connected_node(destination)
        if o_node == d_node:
            destination_nodes = connected_nodes - {o_node}
            d_node = min(
                destination_nodes,
                key=lambda node: (
                    (
                        float(digraph.nodes[node]["x"]) - destination.lng
                    ) * math.cos(math.radians(destination.lat))
                ) ** 2 + (
                    float(digraph.nodes[node]["y"]) - destination.lat
                ) ** 2,
            )
    paths = list(islice(
        nx.shortest_simple_paths(
            digraph,
            o_node,
            d_node,
            weight="length",
        ),
        3,
    ))
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
            return _route_candidates_from_graph(graph, origin, destination)
        except Exception as exc:
            raise CollectorError(
                f"OSMnx 보행 경로 계산 실패: {type(exc).__name__}"
            ) from exc

    async def collect(self, origin: Coordinate, destination: Coordinate) -> list:
        """OD 동적 보행 그래프에서 최대 3개 실제 네트워크 선형을 반환한다.

        OSM 도로 그래프에는 보행 소요시간이 없다. 사용자별 보행속도 정책이
        확정되기 전까지 시간을 임의 환산하지 않고 ``None``으로 유지한다.
        이 수집기는 ODsay 보행 구간의 geometry 보완에만 사용한다.
        """
        try:
            G = await asyncio.wait_for(
                asyncio.to_thread(_get_graph, origin, destination),
                timeout=settings.OSMNX_WALK_GEOMETRY_TIMEOUT_SECONDS,
            )
            return _route_candidates_from_graph(G, origin, destination)
        except Exception as exc:
            raise CollectorError(f"OSMnx 보행 경로 계산 실패: {type(exc).__name__}") from exc
