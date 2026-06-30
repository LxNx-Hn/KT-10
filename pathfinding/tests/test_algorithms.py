"""알고리즘 인터페이스 및 KSP·Tree 기본 동작 테스트.

실제 OSMnx 그래프를 사용하지 않고 소형 합성 그래프로 빠르게 검증한다.
ACO/GA 는 현재 미구현 상태이므로 빈 리스트 반환 여부만 확인한다.
"""
import math
import pytest
import networkx as nx

from pathfinding.algorithms.base import RawPathResult, BasePathfindingAlgorithm
from pathfinding.algorithms.ksp import KSPAlgorithm
from pathfinding.algorithms.aco import ACOAlgorithm
from pathfinding.algorithms.ga import GAAlgorithm
from pathfinding.algorithms.tree_search import TreeSearchAlgorithm


def _make_small_graph() -> nx.MultiDiGraph:
    """테스트용 소형 보행자 그래프 (노드 5개, 단순 격자 형태)."""
    G = nx.MultiDiGraph()
    # 노드: (id, lat, lng)
    nodes = [
        (1, 35.162, 129.053),
        (2, 35.161, 129.054),
        (3, 35.160, 129.055),
        (4, 35.159, 129.056),
        (5, 35.158, 129.057),
    ]
    for nid, lat, lng in nodes:
        G.add_node(nid, y=lat, x=lng)

    # 엣지: 양방향, length 속성 포함
    edges = [(1, 2, 140), (2, 3, 140), (3, 4, 140), (4, 5, 140), (2, 4, 200)]
    for u, v, length in edges:
        G.add_edge(u, v, length=length)
        G.add_edge(v, u, length=length)

    return G


@pytest.fixture
def small_graph():
    return _make_small_graph()


# ── BasePathfindingAlgorithm 추상 클래스 검증 ──

def test_base_is_abstract():
    """추상 클래스는 직접 인스턴스화 불가."""
    with pytest.raises(TypeError):
        BasePathfindingAlgorithm(_make_small_graph())  # type: ignore


# ── KSP 테스트 ──

class TestKSP:
    def test_finds_paths(self, small_graph):
        algo = KSPAlgorithm(small_graph)
        results = algo.find_paths(1, 5, k=2)
        assert len(results) >= 1

    def test_result_type(self, small_graph):
        algo = KSPAlgorithm(small_graph)
        results = algo.find_paths(1, 5, k=1)
        assert all(isinstance(r, RawPathResult) for r in results)

    def test_algorithm_name_in_result(self, small_graph):
        algo = KSPAlgorithm(small_graph)
        results = algo.find_paths(1, 5, k=1)
        assert results[0].algorithm == "ksp"

    def test_rank_starts_at_one(self, small_graph):
        algo = KSPAlgorithm(small_graph)
        results = algo.find_paths(1, 5, k=3)
        ranks = [r.rank for r in results]
        assert ranks[0] == 1

    def test_paths_are_ordered_by_distance(self, small_graph):
        algo = KSPAlgorithm(small_graph)
        results = algo.find_paths(1, 5, k=2)
        if len(results) >= 2:
            assert results[0].total_distance_m <= results[1].total_distance_m

    def test_node_path_connects_origin_to_destination(self, small_graph):
        algo = KSPAlgorithm(small_graph)
        results = algo.find_paths(1, 5, k=1)
        path = results[0].node_path
        assert path[0] == 1
        assert path[-1] == 5

    def test_returns_empty_when_no_path(self, small_graph):
        # 연결되지 않은 노드 추가
        small_graph.add_node(99, y=35.100, x=129.000)
        algo = KSPAlgorithm(small_graph)
        results = algo.find_paths(1, 99, k=3)
        assert results == []

    def test_positive_distance(self, small_graph):
        algo = KSPAlgorithm(small_graph)
        results = algo.find_paths(1, 5, k=1)
        assert results[0].total_distance_m > 0

    def test_computation_time_recorded(self, small_graph):
        algo = KSPAlgorithm(small_graph)
        results = algo.find_paths(1, 5, k=1)
        assert results[0].computation_time_ms >= 0


# ── ACO 테스트 (미구현 — 빈 리스트 반환 확인) ──

class TestACO:
    def test_returns_list(self, small_graph):
        algo = ACOAlgorithm(small_graph)
        results = algo.find_paths(1, 5, k=3)
        assert isinstance(results, list)

    def test_returns_empty_while_unimplemented(self, small_graph):
        algo = ACOAlgorithm(small_graph)
        results = algo.find_paths(1, 5, k=3)
        # 미구현 상태에서는 빈 리스트 반환 — API가 에러 없이 동작해야 한다
        assert results == []


# ── GA 테스트 (미구현 — 빈 리스트 반환 확인) ──

class TestGA:
    def test_returns_list(self, small_graph):
        algo = GAAlgorithm(small_graph)
        results = algo.find_paths(1, 5, k=3)
        assert isinstance(results, list)

    def test_returns_empty_while_unimplemented(self, small_graph):
        algo = GAAlgorithm(small_graph)
        results = algo.find_paths(1, 5, k=3)
        assert results == []


# ── Tree-based Search 테스트 ──

class TestTreeSearch:
    def test_finds_path(self, small_graph):
        algo = TreeSearchAlgorithm(small_graph)
        results = algo.find_paths(1, 5, k=3)
        assert len(results) >= 1

    def test_result_type(self, small_graph):
        algo = TreeSearchAlgorithm(small_graph)
        results = algo.find_paths(1, 5, k=1)
        assert all(isinstance(r, RawPathResult) for r in results)

    def test_algorithm_name(self, small_graph):
        algo = TreeSearchAlgorithm(small_graph)
        results = algo.find_paths(1, 5, k=1)
        assert results[0].algorithm == "tree"

    def test_returns_empty_when_no_path(self, small_graph):
        small_graph.add_node(99, y=35.100, x=129.000)
        algo = TreeSearchAlgorithm(small_graph)
        results = algo.find_paths(1, 99, k=1)
        assert results == []

    def test_positive_distance(self, small_graph):
        algo = TreeSearchAlgorithm(small_graph)
        results = algo.find_paths(1, 5, k=1)
        assert results[0].total_distance_m > 0
