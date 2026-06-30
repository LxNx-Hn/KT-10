"""pathfinding/ 모듈을 백엔드 서버 없이 단독 실행하여 결과를 JSON 파일로 저장하는 스크립트.

용도: 알고리즘 개발·디버깅 중 빠른 확인, 또는 data/routes.generated.json 을
수동으로 갱신하고 싶을 때 사용한다.

실행 (저장소 루트 기준):
    python -m pathfinding.cli.generate_routes \\
        --origin-lat 35.1626 --origin-lng 129.053 --origin-name "부산진구청" \\
        --dest-lat 35.1578 --dest-lng 129.0594 --dest-name "서면역" \\
        --output data/routes.generated.json
"""
import argparse
import json
import logging
import sys
from pathlib import Path

from pathfinding.graph.build_graph import build_or_load_graph, find_nearest_node
from pathfinding.algorithms.ksp import KSPAlgorithm
from pathfinding.algorithms.aco import ACOAlgorithm
from pathfinding.algorithms.ga import GAAlgorithm
from pathfinding.algorithms.tree_search import TreeSearchAlgorithm
from pathfinding.adapters.route_candidate_adapter import to_route_candidate

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
log = logging.getLogger(__name__)


def main() -> None:
    parser = argparse.ArgumentParser(description="경로 후보 생성 후 JSON으로 출력")
    parser.add_argument("--origin-lat", type=float, required=True, help="출발지 위도")
    parser.add_argument("--origin-lng", type=float, required=True, help="출발지 경도")
    parser.add_argument("--origin-name", type=str, required=True, help="출발지 이름")
    parser.add_argument("--dest-lat", type=float, required=True, help="도착지 위도")
    parser.add_argument("--dest-lng", type=float, required=True, help="도착지 경도")
    parser.add_argument("--dest-name", type=str, required=True, help="도착지 이름")
    parser.add_argument("--k", type=int, default=3, help="알고리즘별 후보 경로 수 (기본 3)")
    parser.add_argument(
        "--output",
        type=str,
        default="data/routes.generated.json",
        help="출력 파일 경로. data/routes.demo.json 은 절대 지정하지 말 것 (기존 검증 기준값 보존)",
    )
    args = parser.parse_args()

    # 기존 검증 기준값 파일 덮어쓰기 방지
    if "routes.demo.json" in args.output:
        log.error(
            "data/routes.demo.json 은 기존 점수화 검증 테스트의 기준값입니다. "
            "출력 경로를 data/routes.generated.json 등 다른 파일로 지정하세요."
        )
        sys.exit(1)

    log.info("그래프 로드 중 (캐시 없으면 OSMnx 다운로드)...")
    graph = build_or_load_graph()

    origin_node = find_nearest_node(graph, args.origin_lat, args.origin_lng)
    destination_node = find_nearest_node(graph, args.dest_lat, args.dest_lng)
    log.info("출발 노드: %d / 도착 노드: %d", origin_node, destination_node)

    algorithms = [
        KSPAlgorithm(graph),
        ACOAlgorithm(graph),
        GAAlgorithm(graph),
        TreeSearchAlgorithm(graph),
    ]

    candidates = []
    for algo in algorithms:
        try:
            raw_results = algo.find_paths(origin_node, destination_node, k=args.k)
        except Exception as exc:
            log.warning("[경고] %s 알고리즘 실패, 건너뜀: %s", algo.algorithm_name, exc)
            continue
        for raw in raw_results:
            candidates.append(to_route_candidate(raw, graph, args.origin_name, args.dest_name))
        log.info("[%s] 경로 %d개 생성", algo.algorithm_name, len(raw_results))

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(candidates, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    log.info("경로 후보 %d개 생성 완료 → %s", len(candidates), output_path)


if __name__ == "__main__":
    main()
