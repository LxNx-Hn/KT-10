"""pathfinding/ 모듈을 백엔드 API로 노출하는 라우터.

backend/app/main.py 에 [PATHFINDING-INTEGRATION] 블록으로 등록된다.
기존 backend/app/scoring/ 점수화 엔진과는 독립적으로 동작하며,
이 라우터는 순수하게 "경로 후보 생성"만 담당하고 점수화는 하지 않는다
(점수화는 기존 POST /api/routes/recommend 가 이 결과를 받아 수행하는 것을 권장).
"""
import logging

from fastapi import APIRouter
from pydantic import BaseModel

from pathfinding.graph.build_graph import build_or_load_graph, find_nearest_node
from pathfinding.algorithms.ksp import KSPAlgorithm
from pathfinding.algorithms.aco import ACOAlgorithm
from pathfinding.algorithms.ga import GAAlgorithm
from pathfinding.algorithms.tree_search import TreeSearchAlgorithm
from pathfinding.adapters.route_candidate_adapter import to_route_candidate

log = logging.getLogger(__name__)

router = APIRouter()

# 최초 요청 시 1회 로딩 후 재사용 (lazy singleton)
_graph = None


def _get_graph():
    global _graph
    if _graph is None:
        _graph = build_or_load_graph()
    return _graph


class PathfindingRequest(BaseModel):
    origin_lat: float
    origin_lng: float
    origin_name: str
    destination_lat: float
    destination_lng: float
    destination_name: str
    k: int = 3  # 알고리즘별 경로 후보 개수


@router.post("/candidates")
async def get_pathfinding_candidates(request: PathfindingRequest):
    """4개 알고리즘으로 경로 후보를 생성하여 RouteCandidate 스키마 리스트로 반환한다.

    각 알고리즘이 실패해도 다른 알고리즘 결과는 그대로 반환한다
    (KSP만 성공해도 최소 1개 이상의 후보는 보장됨).
    미구현 알고리즘(ACO/GA)은 빈 리스트를 반환하므로 API 에러 없이 동작한다.
    """
    graph = _get_graph()
    origin_node = find_nearest_node(graph, request.origin_lat, request.origin_lng)
    destination_node = find_nearest_node(graph, request.destination_lat, request.destination_lng)

    algorithms = [
        KSPAlgorithm(graph),
        ACOAlgorithm(graph),
        GAAlgorithm(graph),
        TreeSearchAlgorithm(graph),
    ]

    candidates = []
    for algo in algorithms:
        try:
            raw_results = algo.find_paths(origin_node, destination_node, k=request.k)
        except Exception as exc:
            # 한 알고리즘이 실패해도 나머지는 계속 진행
            log.warning("[%s] 경로 탐색 실패, 건너뜀: %s", algo.algorithm_name, exc)
            continue
        for raw in raw_results:
            candidates.append(
                to_route_candidate(raw, graph, request.origin_name, request.destination_name)
            )

    return {"routeCandidates": candidates}


@router.get("/health")
async def pathfinding_health():
    """pathfinding 모듈 헬스 체크."""
    return {"status": "ok", "module": "pathfinding"}
