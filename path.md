# pathfinding/ — 경로탐색 알고리즘 모듈 구축 지시서

> 이 문서는 Claude Code가 읽고 작업을 진행하기 위한 지시서입니다.
> 기존 레포(포크 대상)는 이미 완성도 높은 PWA 프로젝트이며, 그 구조와 컨벤션은 절대 건드리지 않습니다.
> 이 작업의 범위는 **`pathfinding/` 독립 폴더 신설 + 그 폴더가 `backend/`에 최소 침습으로 연결되는 지점**까지입니다.

---

## 0. 작업 시작 전 필수 단계

코드를 작성하기 전에 반드시 아래 파일들을 전부 읽고 구조를 완전히 파악하라.

```
docs/PLAN.md
docs/IMPLEMENTATION.md
docs/DATA.md
docs/BACKEND.md
data/routes.demo.json
data/places.json
backend/app/main.py
backend/app/models.py
backend/app/scoring/
backend/app/data/
```

특히 `data/routes.demo.json`의 `RouteCandidate` 스키마(필드명, 타입, `segments[]` 구조)를
정확히 파악해야 한다. 이 모듈이 만들어내는 출력은 이 스키마와 **완전히 동일한 형태**여야
기존 점수화 엔진(`backend/app/scoring/`)이 코드 수정 없이 그대로 채점할 수 있다.

---

## 1. 작업 개요

### 1.1 배경

기존 프로젝트는 경로 후보를 `data/routes.demo.json`에 **수동으로 검증해둔 mock 데이터**로 사용 중이다.
이 데이터는 부산진구청 → 서면역 구간의 대표 경로 4개(도보 최단/지하철 승강기/저상버스/일반버스)이며,
점수화 엔진의 검증 기준(`validation.test.ts`, `test_scoring_validation.py`)이 이 데이터에 고정되어 있다.

이 작업은 이 mock 데이터를 대체할 **실제 경로 탐색 알고리즘 4종**을 구현하여,
임의의 출발지·도착지에 대해서도 경로 후보를 직접 계산할 수 있게 만드는 것이다.

### 1.2 구현할 알고리즘 4종

| 알고리즘 | 설명 |
|---|---|
| KSP (K-Shortest Path) | Yen's algorithm 등으로 최단경로 K개를 순차 탐색 |
| ACO (Ant Colony Optimization) | 페로몬 기반 확률적 경로 탐색 |
| GA (Genetic Algorithm) | 경로를 유전자로 인코딩, 교차·변이로 최적화 |
| Tree-based Search | 그래프 탐색 트리 기반 (예: A* 변형 또는 빔서치) |

각 알고리즘은 동일한 입력(출발지/도착지 좌표)을 받아 **경로 후보**를 출력하며,
4개 알고리즘 결과를 모두 모아 최종적으로 기존 점수화 엔진에 넘긴다.
4개 중 어느 게 가장 정확한지는 추후 점수화 엔진의 점수로 비교 평가한다 — 이 모듈은 비교를 위한
**후보 생성기**이지, 자체적으로 "최고 경로"를 판단하지 않는다.

### 1.3 지도·그래프 데이터 처리 원칙 (중요)

이 프로젝트는 카카오맵 API를 **지도 렌더링 + 장소/좌표 제공**용으로만 사용하고 있다
(`frontend/src/map/kakaoLoader.ts`, `backend`의 `KAKAO_REST_API_KEY` 기반 장소검색).
카카오맵은 도로망 그래프(노드·엣지 연결 정보)를 API로 제공하지 않으므로,
경로 탐색 알고리즘이 동작할 그래프는 **OSMnx로 부산진구 보행자 도로망을 직접 구축**한다.

```
[카카오맵 API]                    [pathfinding/ 모듈]
  - 지도 렌더링                      - OSMnx로 부산진구 보행자 도로망 그래프 구축
  - 장소 검색 (좌표 획득)      →      - 카카오에서 받은 출발지/도착지 좌표를
  - 주소 → 좌표 변환                   그래프의 가장 가까운 노드로 스냅
                                    - 4개 알고리즘으로 그 그래프 위에서 경로 탐색
                                    - 결과 좌표 시퀀스를 다시 카카오맵 위에 표시
```

즉 **카카오맵과 OSMnx 그래프는 서로 다른 레이어**다. 카카오맵은 화면에 보여주는 용도,
OSMnx 그래프는 알고리즘이 계산하는 용도이며, 둘을 잇는 지점은 "좌표"뿐이다.
이 모듈에서 카카오맵 SDK나 카카오 REST API를 직접 호출하는 코드는 작성하지 않는다
(이미 `frontend/src/map/`, `backend/app/providers/places.py`에 구현되어 있으므로 재사용한다).

---

## 2. 폴더 구조

저장소 루트에 `pathfinding/`을 독립 폴더로 신설한다. 기존 4폴더 구조(`frontend/` `backend/` `data/` `docs/`)
바로 옆에 위치하며, 기존 폴더 내부 파일은 **2.3절에 명시된 연결 지점 외에는 일체 수정하지 않는다.**

### 2.1 신설 폴더: `pathfinding/`

```
pathfinding/
├─ README.md                    # 이 모듈 사용법 (실행 방법, API, CLI)
├─ requirements.txt
├─ .env.example
├─ graph/
│  ├─ __init__.py
│  ├─ build_graph.py            # OSMnx로 부산진구 보행자 그래프 구축 + 캐싱
│  └─ cache/                    # 구축된 그래프 캐시 파일 저장 위치 (.gitignore 처리)
│     └─ .gitkeep
├─ algorithms/
│  ├─ __init__.py
│  ├─ base.py                   # 알고리즘 공통 인터페이스 (추상 베이스 클래스)
│  ├─ ksp.py                    # K-Shortest Path (Yen's algorithm)
│  ├─ aco.py                    # Ant Colony Optimization
│  ├─ ga.py                     # Genetic Algorithm
│  └─ tree_search.py            # Tree-based Search (A* 기반)
├─ adapters/
│  ├─ __init__.py
│  └─ route_candidate_adapter.py  # 알고리즘 결과 → RouteCandidate 스키마 변환
├─ api/
│  ├─ __init__.py
│  └─ router.py                 # FastAPI APIRouter (백엔드에 연결될 라우터 정의)
├─ cli/
│  ├─ __init__.py
│  └─ generate_routes.py        # 독립 실행 스크립트 — JSON 파일로 결과 출력
└─ tests/
   ├─ __init__.py
   ├─ test_algorithms.py
   └─ test_adapter.py
```

### 2.2 신설 폴더: `data/`에 출력 파일 추가 위치

```
data/
└─ routes.generated.json        # [신규] 알고리즘이 생성한 경로 후보 (mock과 분리, 덮어쓰지 않음)
```

**`data/routes.demo.json`은 절대 수정하거나 덮어쓰지 않는다.** 이 파일은 기존 점수화 엔진의
검증 테스트 기준값이 고정된 파일이라 건드리면 기존 테스트(`validation.test.ts`,
`test_scoring_validation.py`)가 깨진다. 알고리즘 출력은 반드시 별도 파일
`data/routes.generated.json`에 쓴다.

### 2.3 기존 폴더에 대한 최소 침습 연결 지점

아래 두 곳만 수정한다. 그 외 기존 파일은 일절 건드리지 않는다.

**`backend/app/main.py`**

```python
# ============================================================
# [PATHFINDING-INTEGRATION-START]
# pathfinding/ 모듈 연결 지점. 이 블록은 pathfinding/ 알고리즘이
# data/routes.demo.json 의 mock 데이터를 완전히 대체하기로 확정되면
# 통째로 제거 가능하다. (그 시점엔 위 mock 의존 코드도 함께 정리)
from pathfinding.api.router import router as pathfinding_router

app.include_router(pathfinding_router, prefix="/api/pathfinding", tags=["pathfinding"])
# [PATHFINDING-INTEGRATION-END]
# ============================================================
```

이 블록을 기존 `app = FastAPI(...)` 및 다른 `include_router` 호출부 근처,
가장 마지막에 추가한다 (기존 라우터 등록 순서에 영향 주지 않도록).

**`backend/requirements.txt`**

```
# ============================================================
# [PATHFINDING-INTEGRATION-START]
# pathfinding/ 모듈 의존성. 통합 확정 시 pathfinding/requirements.txt 와 통합하거나
# 모듈 제거 시 이 블록도 함께 제거.
osmnx==1.9.4
networkx==3.3
geopandas==1.0.1
shapely==2.0.6
deap==1.4.1
# [PATHFINDING-INTEGRATION-END]
# ============================================================
```

기존 `requirements.txt` 맨 아래에 추가한다.

**그 외 절대 수정 금지 파일**: `backend/app/models.py`, `backend/app/scoring/`,
`backend/app/data/`, `frontend/` 전체, `data/routes.demo.json`, `data/places.json`,
`data/bus_arrivals.json`, `data/weather.json`, `docs/` 전체.

---

## 3. 데이터 계약 (Data Contract) — `RouteCandidate` 스키마 정합성

`docs/DATA.md`의 `routes.demo.json` 스키마를 그대로 따른다. 알고리즘 결과를 이 스키마로
변환하는 책임은 전부 `adapters/route_candidate_adapter.py`가 진다 — 알고리즘 코드 자체는
이 스키마를 몰라도 되도록 분리한다.

```jsonc
// 목표 출력 형태 (docs/DATA.md 기준, 동일 구조 유지)
{
  "id": "r-ksp-1",                          // 알고리즘명-순번으로 생성
  "summary": "도보 경로 (KSP 1순위)",         // 알고리즘별 자동 생성 요약
  "origin": "부산진구청",
  "destination": "서면역",
  "segments": [
    {
      "id": "seg-1",
      "mode": "walk",                       // walk | bus | subway
      "description": "...",
      "durationMin": 0,
      "waitMin": 0,
      // 아래는 모두 tristate(생략 가능) — 정보 미확인 시 키 자체를 생략한다
      // (docs/DATA.md 의 tristate 원칙: null 아님, 키 생략)
      "hasElevator": false,
      "needsVerticalMove": false
    }
  ],
  "totalDurationMin": 0,
  "totalWalkM": 0,
  "transferCount": 0,
  "path": [ { "lat": 35.1626, "lng": 129.053 } ]   // 지도에 그릴 좌표 시퀀스
}
```

**tristate 원칙 준수가 중요하다.** 알고리즘이 계단·엘리베이터 여부를 판단할 수 없는 구간이면
해당 필드를 `false`로 채우지 말고 **키 자체를 생성하지 않는다** (`docs/DATA.md` 명시 규칙).
이 원칙을 어기면 기존 점수화 엔진의 "정보신뢰도 점수" 로직이 잘못 작동한다.

---

## 4. 구현 상세

### 4.1 그래프 구축 (`graph/build_graph.py`)

```python
"""부산진구 보행자 도로망 그래프를 OSMnx로 구축하고 캐싱한다.

카카오맵 API는 도로망 그래프를 제공하지 않으므로, 경로 탐색 알고리즘이 동작할
그래프는 이 모듈이 OSMnx를 통해 OpenStreetMap에서 직접 가져와 구축한다.
카카오맵은 화면 렌더링과 좌표 제공(geocoding)에만 쓰이며, 이 그래프와는
독립적인 레이어이다 — 연결점은 "좌표값"뿐이다.

최초 1회 구축 후 GraphML 파일로 캐싱하여, 매 요청마다 OSM에서 재다운로드하지 않는다.
"""
import osmnx as ox
import networkx as nx
from pathlib import Path

CACHE_DIR = Path(__file__).parent / "cache"
CACHE_PATH = CACHE_DIR / "busanjin_walk.graphml"

# 부산진구 행정구역 경계 기준으로 보행자 전용 그래프 구축
PLACE_NAME = "Busanjin-gu, Busan, South Korea"


def build_or_load_graph() -> nx.MultiDiGraph:
    """캐시가 있으면 로드하고, 없으면 OSMnx로 새로 구축 후 캐싱한다."""
    if CACHE_PATH.exists():
        return ox.load_graphml(CACHE_PATH)

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    graph = ox.graph_from_place(PLACE_NAME, network_type="walk")

    # TODO: 경사도 부여 — DEM 데이터 연동 후 ox.elevation.add_node_elevations_raster() 적용
    # TODO: 계단/인도폭 속성 부여 — V-World 인도 SHP 등 연동 후 엣지 속성 추가

    ox.save_graphml(graph, CACHE_PATH)
    return graph


def find_nearest_node(graph: nx.MultiDiGraph, lat: float, lng: float) -> int:
    """카카오맵에서 받은 좌표(lat, lng)를 그래프의 가장 가까운 노드로 스냅한다.

    이 함수가 카카오맵 좌표계와 OSMnx 그래프를 잇는 유일한 접점이다.
    """
    return ox.nearest_nodes(graph, X=lng, Y=lat)
```

### 4.2 알고리즘 공통 인터페이스 (`algorithms/base.py`)

```python
"""4개 경로탐색 알고리즘(KSP/ACO/GA/Tree)이 공통으로 구현하는 인터페이스.

모든 알고리즘은 동일한 그래프와 출발/도착 노드를 받아, 동일한 형태의
RawPathResult 리스트를 반환한다. 이 결과는 이후 adapters/route_candidate_adapter.py 에서
RouteCandidate 스키마로 변환된다 — 알고리즘 코드는 RouteCandidate 스키마를 알 필요가 없다.
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import List
import networkx as nx


@dataclass
class RawPathResult:
    algorithm: str                 # "ksp" | "aco" | "ga" | "tree"
    rank: int                      # 같은 알고리즘 내 순위 (1부터)
    node_path: List[int]           # 그래프 노드 ID 시퀀스
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
        pass
```

### 4.3 KSP 구현 (`algorithms/ksp.py`)

```python
"""K-Shortest Path — Yen's algorithm 기반.

NetworkX의 shortest_simple_paths를 사용하여 비용 오름차순으로 서로 다른 경로 k개를 찾는다.
4개 알고리즘 중 가장 결정론적이고 빠르며, 다른 3개 알고리즘(ACO/GA/Tree) 결과의
비교 기준선(baseline) 역할을 한다.
"""
import time
import networkx as nx
from itertools import islice
from app.algorithms.base import BasePathfindingAlgorithm, RawPathResult


class KSPAlgorithm(BasePathfindingAlgorithm):
    algorithm_name = "ksp"

    def find_paths(self, origin_node, destination_node, k: int = 3):
        start = time.time()
        results = []

        try:
            paths_generator = nx.shortest_simple_paths(
                self.graph, origin_node, destination_node, weight="length"
            )
            for rank, node_path in enumerate(islice(paths_generator, k), start=1):
                distance = sum(
                    self.graph[node_path[i]][node_path[i + 1]][0].get("length", 0)
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

        return results
```

### 4.4 ACO 구현 (`algorithms/aco.py`)

```python
"""Ant Colony Optimization — 페로몬 기반 확률적 경로 탐색.

베이스 단계에서는 단순화된 ACO를 구현한다: 가상의 개미들이 그래프 위에서
확률적으로 경로를 구성하고, 짧은 경로일수록 페로몬을 더 많이 남겨 다음 반복에서
선택 확률을 높인다. 반복(iteration) 종료 후 상위 k개의 서로 다른 경로를 반환한다.

TODO: 하이퍼파라미터(개미 수, 증발률, alpha/beta) 튜닝은 실제 그래프 규모 확인 후 진행.
"""
import time
import random
import networkx as nx
from app.algorithms.base import BasePathfindingAlgorithm, RawPathResult


class ACOAlgorithm(BasePathfindingAlgorithm):
    algorithm_name = "aco"

    def __init__(self, graph, n_ants: int = 20, n_iterations: int = 30, evaporation: float = 0.5):
        super().__init__(graph)
        self.n_ants = n_ants
        self.n_iterations = n_iterations
        self.evaporation = evaporation
        self.pheromone: dict = {}

    def find_paths(self, origin_node, destination_node, k: int = 3):
        start = time.time()
        # TODO: 실제 그래프 규모 확인 후 페로몬 초기화, 개미 이동, 페로몬 업데이트 로직 구현
        # 현재는 베이스 구조만 — KSP 결과를 임시로 빌려와 더미 반환 (개발 중 인터페이스 검증용)
        return []

    def _construct_solution(self, origin_node, destination_node) -> list:
        """개미 한 마리가 그래프 위에서 확률적으로 경로를 구성한다. (TODO)"""
        raise NotImplementedError
```

### 4.5 GA 구현 (`algorithms/ga.py`)

```python
"""Genetic Algorithm — 경로를 유전자로 인코딩하여 교차·변이로 최적화.

베이스 단계에서는 DEAP 라이브러리 기반 구조만 잡는다.
경로(노드 시�퀀스)를 개체로, 총 이동거리를 적합도(fitness)로 정의하고,
세대를 거듭하며 더 짧고 유효한(그래프상 실제 연결되는) 경로를 진화시킨다.

TODO: 그래프 규모 확인 후 개체군 크기, 세대 수, 교차/변이 확률 등 하이퍼파라미터 확정.
"""
import time
from app.algorithms.base import BasePathfindingAlgorithm, RawPathResult


class GAAlgorithm(BasePathfindingAlgorithm):
    algorithm_name = "ga"

    def __init__(self, graph, population_size: int = 50, generations: int = 100):
        super().__init__(graph)
        self.population_size = population_size
        self.generations = generations

    def find_paths(self, origin_node, destination_node, k: int = 3):
        start = time.time()
        # TODO: DEAP creator/toolbox 설정, 개체 인코딩(경로 = 노드 시퀀스),
        #       교차(crossover) 시 그래프 연결성 보존 전략, 변이(mutation) 설계
        return []
```

### 4.6 Tree-based Search 구현 (`algorithms/tree_search.py`)

```python
"""Tree-based Search — A* 알고리즘 기반 트리 탐색.

휴리스틱(직선거리 = haversine distance)을 활용하여 KSP보다 빠르게 단일 최적 경로를
찾고, 빔서치(beam search) 방식으로 분기를 일부 유지해 서로 다른 경로 k개를 확보한다.

TODO: 빔 너비(beam width) 등 하이퍼파라미터는 실제 그래프 규모 확인 후 조정.
"""
import time
import networkx as nx
from app.algorithms.base import BasePathfindingAlgorithm, RawPathResult


class TreeSearchAlgorithm(BasePathfindingAlgorithm):
    algorithm_name = "tree"

    def find_paths(self, origin_node, destination_node, k: int = 3):
        start = time.time()
        try:
            # 1순위는 NetworkX의 A* 구현 활용 (휴리스틱: 직선거리)
            node_path = nx.astar_path(
                self.graph, origin_node, destination_node,
                heuristic=self._haversine_heuristic, weight="length"
            )
            distance = sum(
                self.graph[node_path[i]][node_path[i + 1]][0].get("length", 0)
                for i in range(len(node_path) - 1)
            )
            results = [
                RawPathResult(
                    algorithm=self.algorithm_name,
                    rank=1,
                    node_path=node_path,
                    total_distance_m=distance,
                    computation_time_ms=(time.time() - start) * 1000,
                )
            ]
            # TODO: 빔서치로 2·3순위 경로 추가 확보
            return results
        except nx.NetworkXNoPath:
            return []

    def _haversine_heuristic(self, node_a, node_b) -> float:
        """A* 휴리스틱 — 두 노드 간 직선거리(m). (TODO: 실제 haversine 공식 구현)"""
        return 0.0
```

### 4.7 결과 변환 어댑터 (`adapters/route_candidate_adapter.py`)

```python
"""4개 알고리즘의 RawPathResult를 docs/DATA.md 의 RouteCandidate 스키마로 변환한다.

알고리즘 코드(algorithms/*.py)는 RouteCandidate 스키마를 전혀 알 필요가 없도록
이 어댑터가 변환 책임을 전담한다. 친구 프로젝트의 점수화 엔진과의 데이터 계약은
오직 이 파일을 통해서만 맺어진다.
"""
import networkx as nx
from app.algorithms.base import RawPathResult


def to_route_candidate(
    result: RawPathResult, graph: nx.MultiDiGraph, origin_name: str, destination_name: str
) -> dict:
    """RawPathResult 1개를 RouteCandidate 딕셔너리 1개로 변환한다."""

    path_coords = [
        {"lat": graph.nodes[node_id]["y"], "lng": graph.nodes[node_id]["x"]}
        for node_id in result.node_path
    ]

    # 도보 시간 추정 (분속 67m 기준 — 추후 실제 속도 모델로 교체 가능)
    duration_min = round(result.total_distance_m / 67, 1)

    return {
        "id": f"r-{result.algorithm}-{result.rank}",
        "summary": f"{_algorithm_label(result.algorithm)} 경로 ({result.rank}순위)",
        "origin": origin_name,
        "destination": destination_name,
        "segments": [
            {
                "id": f"seg-{result.algorithm}-{result.rank}-1",
                "mode": "walk",
                "description": f"{origin_name}에서 {destination_name}까지 도보",
                "durationMin": duration_min,
                "waitMin": 0,
                # NOTE: 계단/엘리베이터 등 접근성 속성은 그래프에 아직 부여되지 않았으므로
                # tristate 원칙에 따라 키 자체를 생략한다 (build_graph.py 의 TODO 완료 후 추가)
            }
        ],
        "totalDurationMin": duration_min,
        "totalWalkM": round(result.total_distance_m, 1),
        "transferCount": 0,
        "path": path_coords,
        # NOTE: 아래 필드는 RouteCandidate 표준 스키마엔 없지만, 알고리즘 비교/검증용으로
        # 추가한 메타 정보 — 점수화 엔진이 무시해도 동작에 지장 없도록 선택적 필드로만 추가
        "_meta": {
            "algorithm": result.algorithm,
            "computation_time_ms": result.computation_time_ms,
        },
    }


def _algorithm_label(algorithm: str) -> str:
    return {"ksp": "최단경로", "aco": "개미군집", "ga": "유전알고리즘", "tree": "트리탐색"}.get(
        algorithm, algorithm
    )
```

### 4.8 FastAPI 라우터 (`api/router.py`)

```python
"""pathfinding/ 모듈을 백엔드 API로 노출하는 라우터.

backend/app/main.py 에 [PATHFINDING-INTEGRATION] 블록으로 등록된다.
기존 backend/app/scoring/ 점수화 엔진과는 독립적으로 동작하며,
이 라우터는 순수하게 "경로 후보 생성"만 담당하고 점수화는 하지 않는다
(점수화는 기존 POST /api/routes/recommend 가 이 결과를 받아 수행하는 것을 권장).
"""
from fastapi import APIRouter
from pydantic import BaseModel
from pathfinding.graph.build_graph import build_or_load_graph, find_nearest_node
from pathfinding.algorithms.ksp import KSPAlgorithm
from pathfinding.algorithms.aco import ACOAlgorithm
from pathfinding.algorithms.ga import GAAlgorithm
from pathfinding.algorithms.tree_search import TreeSearchAlgorithm
from pathfinding.adapters.route_candidate_adapter import to_route_candidate

router = APIRouter()

_graph = None  # 최초 요청 시 1회 로딩 후 재사용 (lazy singleton)


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
        except Exception:
            # 한 알고리즘이 실패해도 나머지는 계속 진행
            continue
        for raw in raw_results:
            candidates.append(
                to_route_candidate(raw, graph, request.origin_name, request.destination_name)
            )

    return {"routeCandidates": candidates}


@router.get("/health")
async def pathfinding_health():
    return {"status": "ok", "module": "pathfinding"}
```

### 4.9 독립 실행 CLI (`cli/generate_routes.py`)

```python
"""pathfinding/ 모듈을 백엔드 서버 없이 단독 실행하여 결과를 JSON 파일로 저장하는 스크립트.

용도: 알고리즘 개발·디버깅 중 빠른 확인, 또는 data/routes.generated.json 을
수동으로 갱신하고 싶을 때 사용한다.

실행:
    python -m pathfinding.cli.generate_routes \\
        --origin-lat 35.1626 --origin-lng 129.053 --origin-name "부산진구청" \\
        --dest-lat 35.1578 --dest-lng 129.0594 --dest-name "서면역" \\
        --output data/routes.generated.json
"""
import argparse
import json
from pathlib import Path
from pathfinding.graph.build_graph import build_or_load_graph, find_nearest_node
from pathfinding.algorithms.ksp import KSPAlgorithm
from pathfinding.algorithms.aco import ACOAlgorithm
from pathfinding.algorithms.ga import GAAlgorithm
from pathfinding.algorithms.tree_search import TreeSearchAlgorithm
from pathfinding.adapters.route_candidate_adapter import to_route_candidate


def main():
    parser = argparse.ArgumentParser(description="경로 후보 생성 후 JSON으로 출력")
    parser.add_argument("--origin-lat", type=float, required=True)
    parser.add_argument("--origin-lng", type=float, required=True)
    parser.add_argument("--origin-name", type=str, required=True)
    parser.add_argument("--dest-lat", type=float, required=True)
    parser.add_argument("--dest-lng", type=float, required=True)
    parser.add_argument("--dest-name", type=str, required=True)
    parser.add_argument("--k", type=int, default=3)
    parser.add_argument(
        "--output", type=str, default="data/routes.generated.json",
        help="data/routes.demo.json 은 절대 지정하지 말 것 (기존 검증 기준값 보존)",
    )
    args = parser.parse_args()

    if "routes.demo.json" in args.output:
        raise ValueError(
            "data/routes.demo.json 은 기존 점수화 검증 테스트의 기준값입니다. "
            "출력 경로를 data/routes.generated.json 등 다른 파일로 지정하세요."
        )

    graph = build_or_load_graph()
    origin_node = find_nearest_node(graph, args.origin_lat, args.origin_lng)
    destination_node = find_nearest_node(graph, args.dest_lat, args.dest_lng)

    algorithms = [KSPAlgorithm(graph), ACOAlgorithm(graph), GAAlgorithm(graph), TreeSearchAlgorithm(graph)]

    candidates = []
    for algo in algorithms:
        try:
            raw_results = algo.find_paths(origin_node, destination_node, k=args.k)
        except Exception as e:
            print(f"[경고] {algo.algorithm_name} 알고리즘 실패, 건너뜀: {e}")
            continue
        for raw in raw_results:
            candidates.append(to_route_candidate(raw, graph, args.origin_name, args.dest_name))

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(candidates, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"경로 후보 {len(candidates)}개 생성 완료 → {output_path}")


if __name__ == "__main__":
    main()
```

---

## 5. 환경변수

### `pathfinding/.env.example`

```env
# OSMnx 그래프 캐시 경로 (기본값 사용 시 비워둬도 됨)
GRAPH_CACHE_DIR=pathfinding/graph/cache

# ACO 하이퍼파라미터 (베이스 기본값)
ACO_N_ANTS=20
ACO_N_ITERATIONS=30
ACO_EVAPORATION_RATE=0.5

# GA 하이퍼파라미터 (베이스 기본값)
GA_POPULATION_SIZE=50
GA_GENERATIONS=100
```

---

## 6. 패키지 (`pathfinding/requirements.txt`)

```
osmnx==1.9.4
networkx==3.3
geopandas==1.0.1
shapely==2.0.6
deap==1.4.1
numpy==2.1.0
fastapi==0.115.0
pydantic==2.9.0
```

> `backend/requirements.txt`에도 3절(2.3)에 명시된 `[PATHFINDING-INTEGRATION]` 블록으로
> 동일 패키지를 추가하므로, 이 파일은 `pathfinding/` 모듈을 backend와 독립적으로
> 실행/테스트할 때 별도 가상환경에서 쓰기 위한 용도다.

---

## 7. `pathfinding/README.md` 내용

```markdown
# pathfinding/ — 경로탐색 알고리즘 모듈

KSP / ACO / GA / Tree-based Search 4개 알고리즘으로 경로 후보를 생성하는 독립 모듈.
부산진구 보행자 도로망은 OSMnx로 직접 구축하며, 카카오맵 API는 이 모듈에서 사용하지 않는다
(좌표·장소 검색은 기존 backend/app/providers/places.py 가 담당).

## 단독 실행 (백엔드 없이)

\`\`\`bash
cd pathfinding
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

python -m cli.generate_routes \\
  --origin-lat 35.1626 --origin-lng 129.053 --origin-name "부산진구청" \\
  --dest-lat 35.1578 --dest-lng 129.0594 --dest-name "서면역" \\
  --output ../data/routes.generated.json
\`\`\`

## 백엔드 API로 사용

기존 백엔드 실행 시 자동으로 함께 뜬다 (\`backend/app/main.py\`의 통합 블록 참고).

\`\`\`bash
cd backend
uvicorn app.main:app --reload --port 8000
\`\`\`

\`\`\`
POST http://localhost:8000/api/pathfinding/candidates
{
  "origin_lat": 35.1626, "origin_lng": 129.053, "origin_name": "부산진구청",
  "destination_lat": 35.1578, "destination_lng": 129.0594, "destination_name": "서면역",
  "k": 3
}
\`\`\`

## 출력

\`docs/DATA.md\`의 \`RouteCandidate\` 스키마와 동일한 형태의 JSON 배열을 반환한다.
기존 \`backend/app/scoring/\` 엔진에 그대로 입력으로 사용할 수 있다.

## 테스트

\`\`\`bash
pytest pathfinding/tests/
\`\`\`

## 통합 확정 시 정리 방법

\`backend/app/main.py\`, \`backend/requirements.txt\` 내 \`[PATHFINDING-INTEGRATION-START/END]\`
주석 블록을 찾아 제거하면 이 모듈을 깔끔하게 분리할 수 있다. 반대로 mock(\`routes.demo.json\`)을
완전히 대체하기로 확정되면, 해당 mock 의존 코드 정리는 기존 팀(점수화 엔진 담당)과 협의 후 진행한다.
```

---

## 8. 작업 순서

1. **0절의 필수 파일을 전부 읽고 `RouteCandidate` 스키마를 정확히 파악한다.**
2. `pathfinding/` 폴더 구조 생성 (2.1절)
3. `graph/build_graph.py` 작성
4. `algorithms/base.py` 작성 → `ksp.py` → `aco.py` → `ga.py` → `tree_search.py` 순서로 작성
   (KSP가 가장 구현 난이도가 낮고 다른 알고리즘의 비교 기준이 되므로 우선 완성)
5. `adapters/route_candidate_adapter.py` 작성 — `docs/DATA.md` 스키마와 한 글자도 다르지 않게 검증
6. `api/router.py` 작성
7. `cli/generate_routes.py` 작성
8. `pathfinding/requirements.txt`, `.env.example`, `README.md` 작성
9. **2.3절에 명시된 연결 지점만** `backend/app/main.py`, `backend/requirements.txt`에 추가
   (반드시 `[PATHFINDING-INTEGRATION-START/END]` 주석으로 감쌀 것)
10. `pathfinding/tests/test_algorithms.py`, `test_adapter.py` 작성
11. `python -m cli.generate_routes` 실행하여 `data/routes.generated.json`이 정상 생성되는지 확인
12. `data/routes.demo.json`이 변경되지 않았는지, 기존 테스트(`pytest`, `npm test`)가 여전히
    통과하는지 최종 확인

---

## 9. 주의사항 (반드시 준수)

- **`data/routes.demo.json`을 절대 수정하지 않는다.** 기존 점수화 검증 테스트의 기준값이다.
- **`frontend/` 폴더는 일체 건드리지 않는다.** 이 작업은 백엔드·독립 모듈 범위로 한정한다.
- **`backend/app/scoring/`, `backend/app/models.py`, `backend/app/data/`를 수정하지 않는다.**
  이 모듈은 기존 점수화 엔진에 "입력"만 제공하며, 엔진 자체에는 관여하지 않는다.
- 기존 코드에 추가하는 모든 줄은 `[PATHFINDING-INTEGRATION-START]` ~
  `[PATHFINDING-INTEGRATION-END]` 주석으로 감싸서, 나중에 통합 여부가 확정되면
  이 블록만 찾아 제거하거나 유지할 수 있게 한다.
- 4개 알고리즘 중 일부가 미구현 상태(TODO)여도 전체 API가 에러 없이 동작해야 한다
  (`api/router.py`의 `try/except`가 이를 보장 — 빈 리스트를 반환하는 알고리즘이 있어도 무방).
- `docs/DATA.md`의 **tristate 원칙**(미확인 값은 키 자체를 생략)을 반드시 지킨다.
- 모든 코드에 한국어 주석을 작성한다.
- OSMnx 그래프 구축은 시간이 걸리므로 반드시 캐싱하고, 캐시 파일은 `.gitignore`에 추가한다.
- `pathfinding/`은 기존 4폴더(`frontend/` `backend/` `data/` `docs/`)와 동일 레벨의
  독립 폴더이며, 그 어떤 기존 폴더 하위에도 위치하지 않는다.
