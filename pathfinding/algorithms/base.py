"""4개 경로탐색 알고리즘(KSP/ACO/GA/Tree)이 공통으로 구현하는 인터페이스.

모든 알고리즘은 동일한 그래프와 출발/도착 노드를 받아, 동일한 형태의
RawPathResult 리스트를 반환한다. 이 결과는 이후 adapters/route_candidate_adapter.py 에서
RouteCandidate 스키마로 변환된다 — 알고리즘 코드는 RouteCandidate 스키마를 알 필요가 없다.
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import List

import networkx as nx


@dataclass
class RawPathResult:
    algorithm: str          # "ksp" | "aco" | "ga" | "tree"
    rank: int               # 같은 알고리즘 내 순위 (1부터)
    node_path: List[int]    # 그래프 노드 ID 시퀀스
    total_distance_m: float
    computation_time_ms: float


class BasePathfindingAlgorithm(ABC):
    """경로탐색 알고리즘 베이스 클래스."""

    algorithm_name: str = "base"

    def __init__(self, graph: nx.MultiDiGraph):
        self.graph = graph

    @abstractmethod
    def find_paths(
        self, origin_node: int, destination_node: int, k: int = 3
    ) -> List[RawPathResult]:
        """출발/도착 노드 사이의 경로 후보 k개를 찾아 반환한다.

        그래프 크기나 알고리즘 특성상 k개를 못 채우면 가능한 만큼만 반환하고,
        예외를 던지지 않는다 (상위 서비스 레이어에서 다른 알고리즘 결과로 보완).
        """
        ...
