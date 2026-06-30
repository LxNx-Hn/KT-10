"""K-Shortest Path — Yen's algorithm 기반.

NetworkX의 shortest_simple_paths를 사용하여 비용 오름차순으로 서로 다른 경로 k개를 찾는다.
4개 알고리즘 중 가장 결정론적이고 빠르며, 다른 3개 알고리즘(ACO/GA/Tree) 결과의
비교 기준선(baseline) 역할을 한다.

주의: shortest_simple_paths는 MultiDiGraph를 지원하지 않으므로, 각 노드 쌍 간
최소 length 엣지만 남긴 DiGraph로 변환 후 탐색한다.
"""
import time
from itertools import islice
from typing import List

import networkx as nx

from .base import BasePathfindingAlgorithm, RawPathResult


def _to_digraph(G: nx.MultiDiGraph) -> nx.DiGraph:
    """MultiDiGraph → DiGraph 변환. 병렬 엣지 중 length가 최소인 것만 남긴다."""
    D = nx.DiGraph()
    D.add_nodes_from(G.nodes(data=True))
    for u, v, data in G.edges(data=True):
        length = data.get("length", 0)
        if D.has_edge(u, v):
            if length < D[u][v].get("length", float("inf")):
                D[u][v]["length"] = length
        else:
            D.add_edge(u, v, length=length)
    return D


class KSPAlgorithm(BasePathfindingAlgorithm):
    algorithm_name = "ksp"

    def find_paths(
        self, origin_node: int, destination_node: int, k: int = 3
    ) -> List[RawPathResult]:
        start = time.time()
        results: List[RawPathResult] = []

        # shortest_simple_paths는 MultiDiGraph 미지원 — DiGraph 뷰 사용
        digraph = _to_digraph(self.graph)

        try:
            paths_gen = nx.shortest_simple_paths(
                digraph, origin_node, destination_node, weight="length"
            )
            for rank, node_path in enumerate(islice(paths_gen, k), start=1):
                distance = sum(
                    digraph[node_path[i]][node_path[i + 1]].get("length", 0)
                    for i in range(len(node_path) - 1)
                )
                results.append(
                    RawPathResult(
                        algorithm=self.algorithm_name,
                        rank=rank,
                        node_path=node_path,
                        total_distance_m=distance,
                        computation_time_ms=(time.time() - start) * 1000,
                    )
                )
        except nx.NetworkXNoPath:
            return []
        except nx.NodeNotFound:
            return []

        return results
