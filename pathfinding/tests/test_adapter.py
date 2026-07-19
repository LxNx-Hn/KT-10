"""route_candidate_adapter 변환 결과의 스키마 정합성 테스트.

docs/DATA.md 의 RouteCandidate 스키마와 필드명·타입이 일치하는지 확인한다.
tristate 원칙(미확인 속성의 키 생략)이 지켜지는지도 검증한다.
"""
import pytest
import networkx as nx

from pathfinding.algorithms.base import RawPathResult
from pathfinding.adapters.route_candidate_adapter import (
    to_route_candidate,
    batch_convert,
    _algorithm_label,
)


def _make_graph_with_nodes() -> nx.MultiDiGraph:
    G = nx.MultiDiGraph()
    G.add_node(1, y=35.1626, x=129.053)
    G.add_node(2, y=35.160, x=129.056)
    G.add_node(3, y=35.1578, x=129.0594)
    G.add_edge(1, 2, length=280)
    G.add_edge(2, 3, length=300)
    return G


def _make_raw_result(algorithm: str = "ksp", rank: int = 1) -> RawPathResult:
    return RawPathResult(
        algorithm=algorithm,
        rank=rank,
        node_path=[1, 2, 3],
        total_distance_m=580.0,
        computation_time_ms=12.5,
    )


@pytest.fixture
def graph():
    return _make_graph_with_nodes()


# ── RouteCandidate 필드 존재 확인 ──

class TestRouteCandidateSchema:
    def test_has_id(self, graph):
        result = to_route_candidate(_make_raw_result(), graph, "부산진구청", "서면역")
        assert "id" in result

    def test_id_format(self, graph):
        result = to_route_candidate(_make_raw_result("ksp", 2), graph, "A", "B")
        assert result["id"] == "r-ksp-2"

    def test_has_summary(self, graph):
        result = to_route_candidate(_make_raw_result(), graph, "A", "B")
        assert "summary" in result
        assert isinstance(result["summary"], str)

    def test_has_origin_destination(self, graph):
        result = to_route_candidate(_make_raw_result(), graph, "부산진구청", "서면역")
        assert result["origin"] == "부산진구청"
        assert result["destination"] == "서면역"

    def test_has_segments(self, graph):
        result = to_route_candidate(_make_raw_result(), graph, "A", "B")
        assert "segments" in result
        assert len(result["segments"]) >= 1

    def test_segment_required_fields(self, graph):
        result = to_route_candidate(_make_raw_result(), graph, "A", "B")
        seg = result["segments"][0]
        assert "id" in seg
        assert "mode" in seg
        assert "description" in seg
        assert "durationMin" in seg
        assert "waitMin" in seg

    def test_segment_mode_is_walk(self, graph):
        result = to_route_candidate(_make_raw_result(), graph, "A", "B")
        assert result["segments"][0]["mode"] == "walk"

    def test_has_total_duration_min(self, graph):
        result = to_route_candidate(_make_raw_result(), graph, "A", "B")
        assert "totalDurationMin" in result
        assert result["totalDurationMin"] > 0

    def test_has_total_walk_m(self, graph):
        result = to_route_candidate(_make_raw_result(), graph, "A", "B")
        assert "totalWalkM" in result
        assert result["totalWalkM"] == 580.0

    def test_has_transfer_count(self, graph):
        result = to_route_candidate(_make_raw_result(), graph, "A", "B")
        assert result["transferCount"] == 0

    def test_has_path(self, graph):
        result = to_route_candidate(_make_raw_result(), graph, "A", "B")
        assert "path" in result
        assert len(result["path"]) == 3  # 노드 3개

    def test_path_has_lat_lng(self, graph):
        result = to_route_candidate(_make_raw_result(), graph, "A", "B")
        for coord in result["path"]:
            assert "lat" in coord
            assert "lng" in coord

    def test_path_coordinates_match_graph(self, graph):
        result = to_route_candidate(_make_raw_result(), graph, "A", "B")
        first_coord = result["path"][0]
        assert abs(first_coord["lat"] - 35.1626) < 1e-4
        assert abs(first_coord["lng"] - 129.053) < 1e-4


# ── tristate 원칙 — 미확인 접근성 속성 키 생략 ──

class TestTristateOmission:
    def test_no_has_elevator_in_segment(self, graph):
        """그래프에 계단/승강기 속성이 없으면 해당 키를 생략해야 한다."""
        result = to_route_candidate(_make_raw_result(), graph, "A", "B")
        seg = result["segments"][0]
        assert "hasElevator" not in seg
        assert "needsVerticalMove" not in seg
        assert "hasStairs" not in seg
        assert "hasSlope" not in seg

    def test_no_false_for_unknown_accessibility(self, graph):
        """미확인 접근성 속성을 False 로 채우면 안 된다 (점수화 엔진 오작동 방지)."""
        result = to_route_candidate(_make_raw_result(), graph, "A", "B")
        seg = result["segments"][0]
        # 명시적 False 값이 있는 키가 없어야 한다
        false_accessibility_keys = {
            k for k, v in seg.items()
            if k in ("hasElevator", "needsVerticalMove", "hasStairs", "hasSlope", "isLowFloorBus")
            and v is False
        }
        assert len(false_accessibility_keys) == 0


# ── _meta 필드 ──

class TestMetaField:
    def test_meta_has_algorithm(self, graph):
        result = to_route_candidate(_make_raw_result("tree", 1), graph, "A", "B")
        assert result["_meta"]["algorithm"] == "tree"

    def test_meta_has_computation_time(self, graph):
        result = to_route_candidate(_make_raw_result(), graph, "A", "B")
        assert result["_meta"]["computation_time_ms"] == 12.5


# ── 알고리즘 레이블 ──

class TestAlgorithmLabel:
    @pytest.mark.parametrize("algo,expected", [
        ("ksp", "최단경로"),
        ("aco", "개미군집"),
        ("ga", "유전알고리즘"),
        ("tree", "트리탐색"),
        ("unknown", "unknown"),
    ])
    def test_label_mapping(self, algo, expected):
        assert _algorithm_label(algo) == expected


# ── batch_convert ──

class TestBatchConvert:
    def test_batch_returns_list(self, graph):
        raws = [_make_raw_result("ksp", 1), _make_raw_result("ksp", 2)]
        results = batch_convert(raws, graph, "A", "B")
        assert len(results) == 2

    def test_batch_empty_input(self, graph):
        results = batch_convert([], graph, "A", "B")
        assert results == []
