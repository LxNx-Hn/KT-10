# AI 파트 작업 내용 및 향후 작업 목록

> 이 문서는 `feature/ai-pipeline` 이후 `ai-set` 브랜치에서 진행한 AI 파트(ai/) + 백엔드 연동 작업을 정리한 문서입니다.
> 지금 이 브랜치가 코드로서 "돌아가긴 하는" 상태이지, "제품으로 완성된" 상태는 아닙니다.
> 특히 3번(아직 안 된 것)과 4번(정확도 개선 과제)을 꼭 읽고 시작해주세요 — 지금 나오는 점수/추천 이유는
> 상당 부분 **가짜 데이터로 학습된 모델 + 팀이 임의로 정한 상수**로 만들어진 결과입니다.

---

## 0. 지금 뭐가 돌아가는 상태인가

```
[프론트엔드] --POST /api/routes/recommend--> [백엔드 :8000] --POST /recommend--> [AI 서버 :8001]
                                                     |
                                        AI_SERVER_URL 설정 안 하면
                                        기존 자체 mock/ODsay 스코어링으로 폴백
```

- `ai/` 폴더가 독립된 FastAPI 서버(`:8001`)로 분리되어 있고, 백엔드(`:8000`)는 `AI_SERVER_URL` 환경변수가 설정된 경우에만 이 서버에 경로 추천을 위임합니다.
- 실제로 브라우저에서 검색 → 백엔드 → AI 서버 → 응답까지 전체 흐름이 동작하는 것까지 확인했습니다(로컬 curl + 브라우저 실측).
- 다만 **경사(slope) 데이터가 전부 0으로 고정**, **XGBoost 랭킹 모델이 가짜 데이터로만 학습됨**, **ODsay 실연동 미검증** 등 핵심 정확도 관련 부분이 아직 플레이스홀더 수준입니다. 아래에서 상세히 다룹니다.

---

## 1. 지금까지 완료한 작업

### 1-1. 레포 구조 정리
- 여기저기 흩어져 있던 브랜치(`feature/ai-pipeline`, `feature/3-pathfinding-algorithms`, `feature/da-raw-data`, `agent/accessibility-feedback-routing`, `feature/odsay-facility-route-prototype`)를 `ai-set` 브랜치 하나로 병합.
- `pathfinding/` 폴더(KSP/ACO/GA/Tree-search 알고리즘 전체) 삭제. 경로 수집을 자체 알고리즘 대신 **ODsay API 기반**으로 전환하기로 한 팀 결정을 반영한 것.
- `ai_pipeline/` → `ai/` 로 이름 변경(상위 폴더를 `backend/frontend/data/docs/ai` 5개로 고정하는 팀 규칙에 맞춤). 기존에 구현돼 있던 `preprocessing/load_layers.py`, `features/extractor.py`, `scoring/{train,predict,explain}.py`는 내용을 거의 그대로 유지.
- `data/raw/`(원본 CSV/XLSX)는 그대로 두고, `data/da/`(데이터팀 원본 구조: raw/geocoded/processed/colab)도 손대지 않고 별개로 보존. 두 데이터가 겹치는 부분이 있는데 지금은 통합하지 않은 상태(3-9 참고).

### 1-2. `ai/collectors/` — 경로 후보 수집기 3종
| 파일 | 역할 | 상태 |
|---|---|---|
| `odsay_collector.py` | 대중교통 경로(메인 소스) | 코드는 완성, **API 키 인증 실패로 실제 검증 못 함** (2번 항목 참고) |
| `tmap_collector.py` | 보행자 경로(보조 소스) | 실제 키로 라이브 테스트 완료, 정상 동작 확인 |
| `osmnx_collector.py` | OSM 도로망 기반 fallback(항상 최소 1개 보장) | 라이브 테스트 완료. **버그 발견 후 수정**: OSMnx가 만드는 그래프가 `MultiDiGraph`인데 `nx.shortest_simple_paths`는 이를 지원하지 않아 항상 예외 처리(직선 플레이스홀더)로 빠지고 있었음. `ox.convert.to_digraph()`로 변환하도록 수정 |

- 세 수집기 모두 "실패해도 예외를 던지지 않고 빈 리스트/플레이스홀더 반환" 원칙으로 구현되어 있어서, API 키가 없거나 응답이 실패해도 서비스 전체가 죽지 않음.

### 1-3. `ai/merger/route_merger.py`
- ODsay/TMAP/OSMnx가 각각 내놓은 후보 중 사실상 같은 경로(좌표를 10개로 샘플링했을 때 평균 거리 30m 이내)를 하나로 합치는 로직. 실제 서로 다른 경로/비슷한 경로 섞어서 테스트해 정상 동작 확인.

### 1-4. `ai/scoring/` — 이미 구현돼 있던 부분 (이번 세션 이전)
- `train.py`: XGBRanker로 프로필별(general/elderly/child/disabled) 랭킹 모델 학습
- `predict.py`: XGB 점수 → 프로필별 로짓 패널티 적용 → Softmax → Top-K
- `explain.py`: SHAP으로 "왜 이 경로를 추천했는지" 자연어 이유 생성
- 이 세 파일은 이번 세션에서 거의 손대지 않음. **다만 이 모델이 학습하는 데이터가 전부 가짜(synthetic)라는 점이 가장 중요한 이슈** — 2-3번 참고.

### 1-5. `ai/api/router.py` + `ai/main.py` — AI 서버 자체
- `/recommend` 엔드포인트: 수집(3개 병렬 호출) → 병합 → 공간 데이터 피처 추출 → XGB 스코어링 → 로짓 패널티 → Softmax → SHAP 이유 → 응답 조립까지 한 번에 처리.
- `/health` 헬스체크.
- 기존 `ai/` 내부 모듈들이 전부 "패키지 접두사 없는(import 시 `ai.` 안 붙이는)" import 스타일로 짜여 있어서, 이 컨벤션을 유지하려고 `uvicorn main:app --app-dir ai --port 8001` 방식으로 기동하도록 함(레포 루트에서 실행).
- **버그 발견/수정**: 응답의 `features`에 `weather_risk`, `crowd_level`이 원래 빠져 있었음(내부 계산에는 쓰이지만 응답 JSON에는 안 실림). 백엔드 쪽에서 날씨 점수를 계산하려고 해도 항상 기본값(0)만 받게 되는 문제였음 → 두 필드를 응답에 추가.

### 1-6. 백엔드 연동
- `backend/app/settings.py`에 `ai_server_url` / `live_ai_pipeline` 추가.
- `backend/app/providers/ai_pipeline.py` 신규 작성: AI 서버 응답을 기존 `ScoredRoute` 모델(프론트가 원래 쓰던 타입)로 변환하는 어댑터.
  - AI 서버는 경로 "전체 집계값"(계단 개수, 엘리베이터 비율 등)만 주는데, 기존 `scoring/components.py`는 "구간(segment)별 상세 정보"를 전제로 8개 세부점수를 계산하는 구조라서 그대로 재사용할 수 없었음. 그래서 **세그먼트는 경로 전체를 나타내는 가상 세그먼트 1개로 압축**, **세부점수는 집계값 기반 단순 산식으로 근사** 처리함 (팀 논의 후 결정한 방식 — 3-7 참고).
- 기존 `/api/routes/recommend` 엔드포인트는 그대로 두고, `AI_SERVER_URL`이 설정된 경우에만 AI 서버로 위임하도록 분기 추가. **기존 인증/피드백/버스도착/날씨 API, mock 기반 로컬 스코어링은 전혀 건드리지 않음.**
- **버그 발견/수정**: AI 서버의 `final_score`(=`adjusted_score * 100`)가 **합성 데이터로 학습된 모델의 비정규화된 로짓 값**이라서, `general` 프로필 같은 경우 실제 좌표를 넣으면 `-133점` 같은 값이 나오고, 화면에는 0~100으로 clamp되어 **모든 경로가 "0점"으로 뭉개져 표시**되는 문제를 발견. `probability`(Softmax로 정규화된 0~1 값) 기반으로 최종 점수를 계산하도록 수정해서 경로 간 점수가 정상적으로 차등화되도록 함.

### 1-7. 프론트엔드 연동
- **중요한 발견**: 원래 프론트엔드는 `/api/routes/recommend`를 아예 호출하지 않고 있었음. live 모드에서도 `/api/routes/candidates`(원본 후보만)를 받아서 프론트엔드 자체 TypeScript 스코어링 엔진(`scoring/engine.ts`, 백엔드 로직을 그대로 복제해둔 것)으로 채점하고 있었음. 즉 지금까지 만든 AI 서버 연동이 화면에는 전혀 반영되지 않는 상태였음.
- `RouteAdapter`에 `recommend()` 메서드를 추가해서, live 모드에서는 실제로 `/api/routes/recommend`를 호출하도록 변경(mock 모드는 기존과 동일하게 로컬 채점 유지).
- 브라우저로 실제 검색까지 해서 확인: 네트워크 탭에서 `POST /api/routes/recommend` 200 확인, AI가 만든 SHAP 기반 추천 이유 문구가 화면에 뜨는 것, 지도에 실제 도로 형태 폴리라인이 그려지는 것까지 확인함.

### 1-8. Docker / 배포 준비
- `backend/Dockerfile`, `ai/Dockerfile`, `frontend/Dockerfile`(레포가 pnpm이 아니라 npm 기반이라 npm으로 작성), `docker-compose.yml` 작성.
- 컨테이너 네트워크에서는 `localhost`가 아니라 서비스명(`ai`)으로 접근해야 하는 문제를 발견해서 `AI_SERVER_URL`을 compose에서 오버라이드하도록 처리.
- `docker compose config`로 설정 파싱까지는 검증했지만, **이 작업 환경에 Docker 데몬이 떠 있지 않아서 실제 `docker compose up --build` 기동 테스트는 못 했음** (2-8 참고).

### 1-9. `ai/rl/` — 강화학습 모듈
- `environment.py`(경로 선택 환경), `agent.py`(DQN 에이전트)를 지시서대로 구현은 해뒀음.
- **하지만 이 모듈은 `ai/api/router.py`의 실제 추천 흐름에 전혀 연결돼 있지 않습니다.** 코드만 존재하는 스캐폴딩 상태. 실제로 쓰려면 학습 데이터 수집, 학습 루프 작성, API 연결까지 별도 작업이 필요함(2-6 참고).

---

## 2. 아직 안 됐거나, 데이터가 없어서 임의로 처리한 부분

### 2-1. ODsay 실연동 미검증 (제일 중요)
- 팀이 전달해준 ODsay API 키로 실제 호출해보니 인증 실패 응답을 받았습니다.
  ```json
  {"error":[{"code":"500","message":"[ApiKeyAuthFailed] ApiKey authentication failed."}]}
  ```
- ODsay Lab은 "API KEY"(쿼리 파라미터용)와 "Basic 인증키(secret)"(Authorization 헤더용) 두 종류를 발급하는데, 지금 코드는 API KEY 쿼리 파라미터 방식만 구현되어 있습니다. 혹시 잘못된 종류의 키를 받은 것일 수도 있고, 단순히 오타/만료일 수도 있습니다.
- **할 일**: ODsay Lab 콘솔에서 키 상태 확인 → 재발급/재확인 → `ai/collectors/odsay_collector.py`로 다시 라이브 테스트. 지금은 ODsay가 항상 실패하고 TMAP/OSMnx만 동작하는 상태로 서비스가 돌아가고 있습니다(fallback 덕분에 안 죽을 뿐).
- 지금까지 대중교통(버스/지하철) 경로는 **한 번도 실제 데이터로 검증되지 않았습니다.** TMAP은 보행자 경로만 주기 때문에, "저상버스인지", "환승 횟수", "지하철 엘리베이터 여부" 같은 정보는 전부 ODsay 응답에서만 나오는데 이 파싱 로직(`ai/api/router.py`의 `_parse_api_features`)이 실제 ODsay 응답으로 단 한 번도 테스트되지 않았다는 뜻입니다. ODsay 키가 살아나면 반드시 실제 응답 구조를 다시 확인해서 파싱 로직이 맞는지 검증해야 합니다.

### 2-2. 경사(slope) 데이터가 전부 0으로 고정됨
- `ai/api/router.py`의 `_parse_api_features()`에 이렇게 박혀 있습니다.
  ```python
  "avg_slope_percent": 0.0,   # TODO: DEM 데이터 연동 후 채움
  "max_slope_percent": 0.0,
  "min_slope_percent": 0.0,
  "slope_iqr":         0.0,
  ```
- 즉 "경사가 심한 경로를 피한다"는 기능이 **지금은 전혀 작동하지 않습니다.** elderly/disabled 프로필의 로짓 패널티에 `avg_slope_percent`, `max_slope_percent` 가중치가 들어가 있는데, 값이 항상 0이라 그 항목은 있으나 마나 한 상태.
- **할 일**: 국토지리정보원 DEM(수치표고모델) 데이터를 받아서, 경로 좌표를 따라 표고차를 계산해 경사도를 산출하는 모듈을 새로 만들어야 함. (OSMnx 그래프의 edge에 elevation을 추가하는 방법도 있고, 별도 DEM 래스터에서 좌표별 표고를 조회하는 방법도 있음 — 데이터팀과 상의 필요)

### 2-3. XGBoost 랭킹 모델이 100% 가짜 데이터로 학습됨
- `ai/scoring/train.py`의 `generate_synthetic_data()`가 `np.random`으로 만든 가상 경로 데이터를 학습에 사용하고 있습니다. `auto_label()`이라는 규칙 기반 함수로 "정답 라벨"도 임의로 만들어서 붙입니다(예: "계단이 많으면 점수 깎기" 같은 하드코딩된 규칙).
- 즉 지금 나오는 XGB 점수와 순위는 **실제 사용자 선호를 전혀 반영하지 않은, 팀이 짐작으로 만든 규칙을 모델이 재현한 것**에 가깝습니다.
- 이 세션에서 실제 좌표로 라이브 테스트해보니, 프로필/좌표 조합에 따라 원본 점수(`adjusted_score`)가 -133점처럼 튀는 경우가 있었던 것도 이 모델이 실제 데이터 분포 밖의 입력에 대해 이상한 값을 내놓기 때문입니다(1-6의 버그 수정 참고).
- **할 일**:
  1. 가장 먼저: 실제 사용자 선택 데이터가 없다면, 최소한 팀 내부에서 "샘플 경로 몇 개 + 프로필별 순위"를 사람이 직접 매겨서 소규모 검증셋이라도 만들어야 함(문서에 언급된 "조용빈 선임님 샘플 경로 평가" 같은 절차).
  2. 이후 실제 사용자 로그/선택 데이터가 쌓이면 `generate_synthetic_data()` 자리를 실데이터 로딩 함수로 교체.
  3. 그 전까지는 이 모델이 내놓는 점수를 "정답"이 아니라 "잠정적인 순위 힌트" 정도로만 취급하고, 화면에 점수 자체보다 순위/추천 이유 중심으로 노출하는 게 안전함.

### 2-4. 혼잡도(crowd_level)는 완전히 임의의 상수
- `ai/api/router.py`:
  ```python
  def _estimate_crowd_level(weather: str) -> float:
      """날씨 조건으로 혼잡도 추정 (0~1). 실제 KT 교통카드 데이터 수신 후 교체."""
      return {"heatwave": 0.3, "coldwave": 0.3, "rain": 0.6}.get(weather, 0.5)
  ```
- 날씨만 보고 대충 찍은 숫자입니다. 실제 혼잡도와는 무관.
- **할 일**: KT 교통카드/이동통신 데이터 등 실제 혼잡도 데이터가 확보되면 이 함수를 교체.

### 2-5. `stair_count` / `elevator_ratio` / `is_low_floor_bus` 파싱이 대략적인 휴리스틱
- ODsay 응답에서 `trafficType == 3`이고 `stairInfo.elevatorYN == "Y"`이면 엘리베이터 구간으로 카운트, 버스 이름에 "저상"이라는 문자열이 포함되면 저상버스로 판단하는 식의 매우 단순한 문자열/필드 매칭입니다.
- ODsay 실제 응답으로 한 번도 검증되지 않았다는 점이 2-1과 연결됩니다. TMAP 쪽 `stair_count`도 `facilityType`에 "계단"이 포함된 세그먼트 개수를 세는 정도라 정밀하지 않습니다.
- **할 일**: ODsay 키 복구 후 실제 응답을 로그로 찍어보면서 필드 구조가 코드와 맞는지, 놓치는 케이스가 있는지 검증 필요.

### 2-6. RL(강화학습) 모듈이 스캐폴딩만 있고 실제로 안 쓰임
- `ai/rl/environment.py`, `agent.py`는 지시서 스펙대로 작성은 해뒀지만 `ai/api/router.py`에서 전혀 호출되지 않습니다. 지금 실제 추천 로직은 XGBRanker + 로짓 패널티 + Softmax뿐이고, DQN 에이전트는 학습도, 추론 연결도 안 된 상태입니다.
- **할 일**: 이 모듈을 실제로 쓸 계획이 있다면 (1) 학습 데이터/보상 설계를 다시 검토, (2) 학습 스크립트 작성, (3) 학습된 정책을 API에 연결하는 작업이 별도로 필요합니다. 안 쓸 거라면 지금 상태로 방치하지 말고 팀 회의에서 "당장은 안 쓴다"는 결정을 명시적으로 하는 게 좋습니다.

### 2-7. backend 어댑터의 8개 세부점수는 근사치
- AI 서버는 경로 "전체"에 대한 집계 피처만 주기 때문에, 기존 백엔드의 정밀한 구간별 점수 계산(`backend/app/scoring/components.py`)을 그대로 쓸 수 없었습니다. `backend/app/providers/ai_pipeline.py`의 `_approximate_components()`는 단순 산식(계단 개수 × 상수, 엘리베이터 비율 × 100 등)으로 8개 점수를 흉내만 낸 것이라, 기존 mock/ODsay 경로에서 나오는 점수와 **계산 방식 자체가 다릅니다.**
- **할 일**: AI 서버가 구간(segment)별로 상세 데이터를 반환하도록 확장하거나(ODsay의 subPath 정보를 살려서), 아니면 이 근사 산식을 실제 데이터로 캘리브레이션하는 작업이 필요합니다.

### 2-8. Docker Compose 실제 기동 테스트 못 함
- `docker-compose.yml`, 3개 Dockerfile 모두 작성하고 `docker compose config`로 문법 검증까지는 했지만, 이 작업 환경에 Docker Desktop이 켜져 있지 않아서 **실제로 `docker compose up --build`를 돌려서 3개 컨테이너가 다 뜨는지는 확인 못 했습니다.** 로컬 프로세스로는 backend/ai/frontend를 각각 직접 띄워서 확인했습니다.
- **할 일**: Docker Desktop 켜고 `docker compose up --build` 한 번 돌려서 이미지 빌드/기동 확인 필요.

### 2-9. `data/raw/` 와 `data/da/` 데이터 중복·미통합
- 데이터팀이 관리하는 `data/da/`(raw→geocoded→processed 파이프라인)와 AI 팀이 쓰는 `data/raw/`(평평한 구조) 사이에 **같은 원본을 다르게 처리한 파일이 섞여 있습니다.** 예를 들어 무더위쉼터/한파쉼터 데이터가 양쪽에 다 있는데 컬럼 구성과 전처리 방식이 다를 수 있습니다. 이번 작업에서는 두 구조를 통합하지 않고 그대로 병존시켰습니다(팀 협의 결과).
- **미활용 데이터도 있습니다**:
  - `data/raw/busan_elevator_info_csv_processed.xlsx` — `load_layers.py`에서 전혀 로딩하지 않는 파일. 엘리베이터 관련 레이어를 보강할 수 있는데 방치되어 있음.
  - `data/da/geocoded/부산_KOROAD 사고다발지역/` — 교통사고 다발지역 데이터인데 `ai/features/extractor.py`에는 이걸 쓰는 피처가 없음. 백엔드 모델(`RouteSegment.accident_risk`)에는 이미 필드가 있지만 AI 파이프라인에서 채워주질 않아서 항상 비어 있는 상태.
- **할 일**: 데이터팀과 어떤 데이터를 최종본으로 쓸지 정리, 안 쓰는 파일 중 쓸만한 건 `extractor.py`에 피처로 추가.

### 2-10. 날씨: 실측값이 AI 서버까지 전달되지 않음
- 백엔드는 OpenWeather 같은 실제 날씨 API에서 온도/강수량 등을 받아올 수 있지만(`backend/app/providers/weather.py`), AI 서버로는 `weather` 시나리오 이름(`normal`/`rain`/... 문자열)만 전달됩니다. AI 서버의 `_calc_weather_risk()`는 이 시나리오 이름별로 고정된 위험도 상수(0/15/20/30 등)를 매길 뿐, 실제 강수량이 5mm인지 50mm인지는 구분하지 못합니다.
- **할 일**: 필요하다면 AI 서버의 `RecommendRequest`에 실측 날씨값(강수량, 체감온도 등)을 추가로 받아서 `_calc_weather_risk()`를 더 정밀하게 만드는 작업.

### 2-11. OSMnx 그래프가 "부산진구"로 하드코딩됨
- `ai/collectors/osmnx_collector.py`:
  ```python
  _graph = ox.graph_from_place("Busanjin-gu, Busan, South Korea", network_type="walk")
  ```
- 서비스 범위가 부산진구를 벗어나면(예: 다른 구 데모 확장 시) 이 그래프에 없는 좌표라 `nearest_nodes`가 엉뚱한 결과를 주거나 매우 먼 거리를 반환할 수 있습니다.
- **할 일**: 서비스 지역이 확장될 경우 그래프 범위/캐싱 전략을 다시 설계해야 함.

---

## 3. 정확도/파라미터 개선을 위해 튜닝이 필요한 값들

지금 코드에 있는 아래 상수들은 전부 **팀이 감으로 정한 값**이고, 실데이터/사용자 피드백 기반으로 다시 잡아야 하는 것들입니다.

| 위치 | 값 | 설명 |
|---|---|---|
| `ai/scoring/train.py` | `XGBRanker(max_depth=6, learning_rate=0.05, n_estimators=300, subsample=0.8, colsample_bytree=0.8)` | 하이퍼파라미터 전혀 튜닝 안 됨. 실데이터 확보 후 GridSearch/Optuna 등으로 재조정 필요 |
| `ai/scoring/predict.py` | `LOGIT_PENALTIES` (프로필별 가중치, 예: elderly의 `stair_count: 2.0`) | 사람이 "이 정도면 되겠지"하고 정한 값. 실사용자 피드백으로 보정 필요 |
| `ai/scoring/train.py` | `auto_label()` 내부 가중치(`score -= features.get("stair_count", 0) * 0.15` 등) | 가짜 라벨 생성 규칙. 실데이터 확보 시 이 함수 자체가 통째로 대체되어야 함 |
| `ai/features/extractor.py` | `BUF_50M = 0.00045`, `BUF_200M = 0.0018` (버퍼 반경) | CCTV/횡단보도는 50m, 쉼터/AED/충전기 등은 200m로 임의 설정. 실제 도보 인지 거리 기준으로 재검토 필요 |
| `ai/merger/route_merger.py` | `MERGE_THRESHOLD_M = 30.0` | 이 거리 이내면 "같은 경로"로 병합. 너무 좁으면 중복이 안 걸러지고, 너무 넓으면 다른 경로가 합쳐짐 |
| `ai/api/router.py` | `_calc_weather_risk()`의 `base` 딕셔너리(`heatwave: 20` 등) | 날씨 시나리오별 위험도 상수. 실측 데이터 기반 재조정 필요 |
| `ai/api/router.py` | `_estimate_crowd_level()` | 완전 임의 상수 (2-4와 동일) |
| `backend/app/providers/ai_pipeline.py` | `_approximate_components()` 내부 산식(`stair_count * 8`, `walk_distance_m / 25` 등) | 근사 매핑용 임의 상수 (2-7과 동일) |
| `ai/scoring/train.py` | `generate_synthetic_data()`의 랜덤 분포 범위 | 실데이터 도착 전까지 파이프라인 검증용. 실데이터로 교체되면 이 함수 자체가 사라져야 함 |

---

## 4. 우선순위 제안 (다음에 뭐부터 하면 좋을지)

1. **ODsay API 키 문제 해결** — 지금 대중교통 경로 추천이 사실상 반쪽(OSMnx 도보 경로 위주)으로만 동작 중. 이게 안 풀리면 저상버스/환승/엘리베이터 관련 기능 전체가 검증 불가능.
2. **DEM 기반 경사도 연동** — elderly/disabled 프로필의 핵심 기능인데 지금 완전히 죽어 있음(항상 0).
3. **실데이터 기반 라벨/검증셋 확보** — 최소한 팀 내부 평가라도 없으면 XGB 점수를 아무도 신뢰할 수 없음.
4. **ODsay 응답 파싱 검증** (1번이 풀리면 바로 이어서).
5. Docker Compose 실제 기동 확인.
6. 나머지(혼잡도 실데이터, RL 모듈 사용 여부 결정, 미활용 데이터 통합 등)는 우선순위 낮음 — 팀 상황 봐서 진행.
