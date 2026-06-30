"""4개 알고리즘의 RawPathResult를 docs/DATA.md 의 RouteCandidate 스키마로 변환한다.

알고리즘 코드(algorithms/*.py)는 RouteCandidate 스키마를 전혀 알 필요가 없도록
이 어댑터가 변환 책임을 전담한다. 기존 프로젝트의 점수화 엔진과의 데이터 계약은
오직 이 파일을 통해서만 맺어진다.

출력 스키마(docs/DATA.md 기준):
  {
    "id": "r-ksp-1",
    "summary": "최단경로 경로 (1순위)",
    "origin": "부산진구청",
    "destination": "서면역",
    "segments": [ { "id": "seg-ksp-1-1", "mode": "walk", "description": "...",
                    "durationMin": 12.3, "waitMin": 0 } ],
    "totalDurationMin": 12.3,
    "totalWalkM": 820.0,
    "transferCount": 0,
    "path": [ { "lat": 35.1626, "lng": 129.053 } ]
  }

tristate 원칙(docs/DATA.md):
  미확인 접근성 속성(hasElevator, needsVerticalMove 등)은 False로 채우지 않고
  키 자체를 생략한다. build_graph.py 의 TODO(계단/승강기 속성 부여)가 완료되기 전까지
  이 어댑터는 해당 키를 일절 출력하지 않는다.
"""
from typing import Dict, Any

import networkx as nx

from ..algorithms.base import RawPathResult

# 도보 속도 기준 (분속 67m — 추후 실제 속도 모델로 교체 가능)
_WALK_SPEED_M_PER_MIN = 67.0


def to_route_candidate(
    result: RawPathResult,
    graph: nx.MultiDiGraph,
    origin_name: str,
    destination_name: str,
) -> Dict[str, Any]:
    """RawPathResult 1개를 RouteCandidate 딕셔너리 1개로 변환한다."""

    path_coords = [
        {"lat": graph.nodes[nid]["y"], "lng": graph.nodes[nid]["x"]}
        for nid in result.node_path
    ]

    # 도보 시간 추정
    duration_min = round(result.total_distance_m / _WALK_SPEED_M_PER_MIN, 1)

    segment: Dict[str, Any] = {
        "id": f"seg-{result.algorithm}-{result.rank}-1",
        "mode": "walk",
        "description": f"{origin_name}에서 {destination_name}까지 도보",
        "durationMin": duration_min,
        "waitMin": 0,
        # NOTE: 계단/엘리베이터 등 접근성 속성은 그래프에 아직 부여되지 않았으므로
        # tristate 원칙에 따라 키 자체를 생략한다 (build_graph.py 의 TODO 완료 후 추가).
    }

    candidate: Dict[str, Any] = {
        "id": f"r-{result.algorithm}-{result.rank}",
        "summary": f"{_algorithm_label(result.algorithm)} 경로 ({result.rank}순위)",
        "origin": origin_name,
        "destination": destination_name,
        "segments": [segment],
        "totalDurationMin": duration_min,
        "totalWalkM": round(result.total_distance_m, 1),
        "transferCount": 0,
        "path": path_coords,
        # NOTE: _meta 는 RouteCandidate 표준 스키마에 없지만 알고리즘 비교·검증용으로 추가.
        # 점수화 엔진은 이 필드를 무시해도 동작에 지장 없다(선택적 필드).
        "_meta": {
            "algorithm": result.algorithm,
            "computation_time_ms": result.computation_time_ms,
        },
    }

    return candidate


def batch_convert(
    results: list,
    graph: nx.MultiDiGraph,
    origin_name: str,
    destination_name: str,
) -> list:
    """RawPathResult 리스트 전체를 RouteCandidate 딕셔너리 리스트로 일괄 변환한다."""
    return [to_route_candidate(r, graph, origin_name, destination_name) for r in results]


def _algorithm_label(algorithm: str) -> str:
    """알고리즘 코드를 한국어 레이블로 변환한다."""
    return {
        "ksp": "최단경로",
        "aco": "개미군집",
        "ga": "유전알고리즘",
        "tree": "트리탐색",
    }.get(algorithm, algorithm)
