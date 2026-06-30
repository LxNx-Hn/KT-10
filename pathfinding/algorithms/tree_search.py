"""Tree-based Search — A* 알고리즘 기반 트리 탐색.

휴리스틱(직선거리 = haversine distance)을 활용하여 KSP보다 빠르게 단일 최적 경로를
찾고, 빔서치(beam search) 방식으로 분기를 일부 유지해 서로 다른 경로 k개를 확보한다.

TODO: 빔 너비(beam width) 등 하이퍼파라미터는 실제 그래프 규모 확인 후 조정.
"""
import math
import time
import logging
from typing import List

import networkx as nx

from .base import BasePathfindingAlgorithm, RawPathResult

log = logging.getLogger(__name__)


class TreeSearchAlgorithm(BasePathfindingAlgorithm):
    algorithm_name = "tree"

    def __init__(self, graph: nx.MultiDiGraph, beam_width: int = 3):
        super().__init__(graph)
        self.beam_width = beam_width

    def find_paths(
        self, origin_node: int, destination_node: int, k: int = 3
    ) -> List[RawPathResult]:
        start = time.time()
        results: List[RawPathResult] = []

        try:
            # 1순위: NetworkX의 A* 구현 활용 (휴리스틱: haversine 직선거리)
            node_path = nx.astar_path(
                self.graph,
                origin_node,
                destination_node,
                heuristic=self._haversine_heuristic,
                weight="length",
            )
            distance = sum(
                self.graph[node_path[i]][node_path[i + 1]][0].get("length", 0)
                for i in range(len(node_path) - 1)
            )
            results.append(
                RawPathResult(
                    algorithm=self.algorithm_name,
                    rank=1,
                    node_path=node_path,
                    total_distance_m=distance,
                    computation_time_ms=(time.time() - start) * 1000,
                )
            )

            # TODO: beam_width 기반 빔서치로 2·3순위 경로 추가 확보.
            # 현재는 A* 1개만 반환. 빔서치 구현 시 서로 다른 경로(노드 겹침 최소화)를
            # beam_width개 병렬 탐색하여 k개를 채운다.

        except nx.NetworkXNoPath:
            return []
        except nx.NodeNotFound:
            return []

        return results

    def _haversine_heuristic(self, node_a: int, node_b: int) -> float:
        """A* 휴리스틱 — 두 노드 간 haversine 직선거리(m).

        OSMnx 그래프 노드는 'y'(위도), 'x'(경도) 속성을 가진다.
        """
        data_a = self.graph.nodes[node_a]
        data_b = self.graph.nodes[node_b]
        return _haversine_m(
            lat1=data_a["y"], lng1=data_a["x"],
            lat2=data_b["y"], lng2=data_b["x"],
        )


def _haversine_m(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """두 좌표 간 haversine 거리(미터)."""
    R = 6_371_000.0
    d_lat = math.radians(lat2 - lat1)
    d_lng = math.radians(lng2 - lng1)
    a = (
        math.sin(d_lat / 2) ** 2
        + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(d_lng / 2) ** 2
    )
    return 2 * R * math.asin(math.sqrt(a))
