# pathfinding/ — 경로탐색 알고리즘 모듈

KSP / ACO / GA / Tree-based Search 4개 알고리즘으로 경로 후보를 생성하는 독립 모듈.
부산진구 보행자 도로망은 OSMnx로 직접 구축하며, 카카오맵 API는 이 모듈에서 사용하지 않는다
(좌표·장소 검색은 기존 `backend/app/providers/places.py` 가 담당).

## 단독 실행 (백엔드 없이)

```bash
cd /path/to/KT-10  # 저장소 루트
python -m venv pathfinding/.venv
source pathfinding/.venv/bin/activate
pip install -r pathfinding/requirements.txt

python -m pathfinding.cli.generate_routes \
  --origin-lat 35.1626 --origin-lng 129.053 --origin-name "부산진구청" \
  --dest-lat 35.1578 --dest-lng 129.0594 --dest-name "서면역" \
  --output data/routes.generated.json
```

> 최초 실행 시 OSMnx가 OpenStreetMap에서 부산진구 보행자 도로망을 다운로드합니다 (수 분 소요).
> 이후 `pathfinding/graph/cache/busanjin_walk.graphml` 에 캐싱되어 재사용됩니다.

## 백엔드 API로 사용

기존 백엔드 실행 시 자동으로 함께 뜬다 (`backend/app/main.py` 의 통합 블록 참고).

```bash
cd backend
uvicorn app.main:app --reload --port 8000
```

```
POST http://localhost:8000/api/pathfinding/candidates
{
  "origin_lat": 35.1626, "origin_lng": 129.053, "origin_name": "부산진구청",
  "destination_lat": 35.1578, "destination_lng": 129.0594, "destination_name": "서면역",
  "k": 3
}
```

## 출력

`docs/DATA.md` 의 `RouteCandidate` 스키마와 동일한 형태의 JSON 배열을 반환한다.
기존 `backend/app/scoring/` 엔진에 그대로 입력으로 사용할 수 있다.

## 테스트

```bash
# 저장소 루트에서
pytest pathfinding/tests/
```

## 알고리즘 구현 상태

| 알고리즘 | 상태 | 설명 |
|---|---|---|
| KSP (Yen's) | ✅ 구현 완료 | NetworkX `shortest_simple_paths` 기반, baseline |
| Tree (A*) | ✅ 구현 완료 | haversine 휴리스틱 A*, 빔서치 확장 예정 |
| ACO | 🚧 인터페이스만 | 그래프 규모 확인 후 하이퍼파라미터 튜닝 예정 |
| GA | 🚧 인터페이스만 | DEAP 기반 구현 예정 |

미구현 알고리즘은 빈 리스트를 반환하며 API 에러를 발생시키지 않는다.

## 통합 확정 시 정리 방법

`backend/app/main.py`, `backend/requirements.txt` 내 `[PATHFINDING-INTEGRATION-START/END]`
주석 블록을 찾아 제거하면 이 모듈을 깔끔하게 분리할 수 있다. 반대로 mock(`routes.demo.json`)을
완전히 대체하기로 확정되면, 해당 mock 의존 코드 정리는 기존 팀(점수화 엔진 담당)과 협의 후 진행한다.
