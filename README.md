# 교통약자·이동취약자 맞춤형 경로 추천 PWA

[![CI](https://github.com/LxNx-Hn/KT-10/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/LxNx-Hn/KT-10/actions/workflows/ci.yml)

부산광역시의 보행·대중교통 후보를 `경로 사실·특성 생성`과
`프로필·상황 적합도 산정`의 두 단계로 비교하는 PWA입니다. 결과는 적합
점수순으로 정렬하고, `빠른 길`, `경사가 완만한 길`, `그늘 많은 길`,
`환승이 단순한 길` 같은 사실 배지로 이유를 설명합니다. 프론트의 현재
단일 진입점은 `feature/frontend-map-first-v2` 디자인을 통합한 Kakao 지도
중심 UI이며, 고정 데모 경로나 자동 가짜 검색 없이 실제 상태를 표시합니다.

최신 제품·모델·UI 기준은 [제품 의사결정 기준](docs/PRODUCT_DECISIONS.md),
현재 구현과 차단사항은
[현재 상태 보고서](docs/CURRENT_STATUS_AND_FOLLOW_UP_REPORT.md)를
기준으로 합니다. 활성 프론트 구조와 실행 계약은
[Map-first UI v2](frontend/src/v2/README.md)에 정리되어 있습니다.
실제 공개 전에 필요한 도메인·공급자 콘솔·검증 순서는
[최종 배포 잔여 작업 체크리스트](docs/FINAL_DEPLOYMENT_REMAINING_CHECKLIST.md)를
따릅니다.
Windows에서 키 확인부터 실제 장소검색·경로·경사·건물 그늘과 비운영
초기 평가 모델까지 점검하는 명령은 [로컬 테스트 가이드](docs/LOCAL_TESTING.md)에
분리했습니다.

## 확정된 추천 계약

- 기본 프로필: 일반, 고령자, 아동, 청소년, 장애인, 임산부
- 이번 이동 조건: 짐 많음, 유아차, 계단 회피, 그늘 우선, 저상버스 우선,
  환승 최소
- 주 결과: 프로필·조건 적합 점수순의 경로 순위
- 설명: 관측·계산된 경로 지표와 사실 기반 특성 배지
- UI: 지도와 동기화된 수평 스와이프 카드, 버튼·키보드 대체 조작
- 개인화: 초기 5건은 베이스라인 우선, 사용자별 영향 최대 35%
- 전역 학습: 동의 후기를 관리자가 검토·가공하고 후보 모델을 수동 승격

## 현재 구현

- ODsay 대중교통 후보와 공식 `loadLane` geometry, TMAP 보행 후보,
  OSMnx 보행 geometry의 영구 그래프 캐시와 구간별 지도 오버레이
- 부산 전역 공간 레이어 결합: 쉼터, CCTV, AED, 휠체어 충전기, 스마트쉘터, 도시철도 접근성, 횡단보도, 정류장 등
- 정적 공간 레이어를 시작 시 EPSG:5179로 한 번 투영하고 Shapely
  STRtree를 선생성하여 요청마다 전체 레이어를 재투영·전수 검사하지 않음
- Open-Meteo Copernicus GLO-90 고도 기반 오르막·내리막·누적 상승량 추정(90m 해상도임을 UI에 명시)
- 태양 위치와 합성 건물 높이로 계산한 검증용 그늘 비율·지도 오버레이, VWorld 공공 건물 도형·높이 공급자(품질 상태 분리)
- ODsay 원시 응답, OSMnx 보행 그래프, GLO-90 경로 표본, VWorld 건물
  corridor의 Docker 영구 캐시와 우선 OD 사전 준비 스크립트
- `ROUTE_MODE=demo|live|ai` 공급자 선택과 실패 시 무단 폴백 금지
- 프로필별 XGBRanker 학습·검증 파이프라인, 초기 라벨링 후보 생성기와 모델 준비 상태 게이트
- 카카오 로그인 사용자만 PostgreSQL 프로필·후기·개인화 저장; 게스트는 개인화하지 않음
- 후기 기반 개인 온라인 모델과 동의 후기의 팀 승인 비중 제한 전역 후보 재학습(운영 모델 자동 교체 없음)
- 시설물 위치·운영상태 오류 신고와 관리자 검토 대기열
- 자주 바뀌는 상황 조건은 검색 UI에, 장기 이동지원 정보는 로그인 프로필에 분리
- Kakao 지도 중심 모바일 UI, 수평 스와이프 경로 비교, 프로필·조건 drawer,
  경로·날씨·후기·설정 상세 drawer와 실제 음성 챗봇 진입점

`data/ai/`는 데모·회귀검증 픽스처이고 임의 OD의 실제 경로가 아닙니다.
운영 `live` 모드는 실제 외부 공급자 경로를 규칙으로 비교하므로 학습
모델이 없어도 동작합니다. `ROUTE_MODE=ai`의 학습 순위화는 명시적으로
선택한 tier의 안전한 XGBoost JSON ZIP artifact가 준비되지 않으면 503으로
거부합니다.

모델 파일은 pickle을 사용하지 않습니다. ZIP 내부의 프로필별 XGBoost
JSON과 manifest checksum을 검증한 뒤 로드하며 역할은 다음과 같이
분리합니다.

- `ai/data/rankers.human-candidate.zip`: 사람 평가로 학습한 관리자 검토 전 후보
- `ai/data/rankers.human-validated.zip`: checksum·승인자·승인 근거를 남겨 수동 승격한 운영 모델
- `ai/data/rankers.bootstrap-baseline.zip`: 초기 평가로 학습하는 비운영 baseline
- `ai/data/rankers.review-mixed-candidate.zip`: 동의 후기를 제한적으로 섞은 별도 검토 후보

그늘 데모의 입력·계산식·실데이터 교체 조건은 [docs/SHADE_RULE_DEMO.md](docs/SHADE_RULE_DEMO.md)를 참고하세요.

## 2026-07-24 상태

- 로컬 최종 회귀는 AI `153 passed, 2 skipped`, 백엔드
  `185 passed, 1 skipped`, 프론트 `92 passed`(15개 파일)입니다.
  TypeScript/PWA build, 접근성 Playwright `5 passed, 1 expected skip`,
  Python compileall·Ruff·Bandit·pip check와 `npm audit`(취약점 0건)도
  통과했습니다.
- 프로덕션 Compose의 PostgreSQL·AI·백엔드·프론트 4개 서비스가 모두
  `healthy`이며, 실제 공급자는 Kakao Local, OpenWeather, 부산 버스,
  ODsay, VWorld가 `live`입니다. 현재 readiness에서 남은 항목은 로컬
  HTTP로는 충족할 수 없는 운영 HTTPS origin과 Kakao OAuth 콘솔 등록뿐입니다.
- 실제 브라우저에서 Kakao Places의 `북구청`·`부산역` 검색·선택, ODsay
  실경로 3개, GLO-90 경사 특성, 수평 카드의 다음 경로 `2/3`, Kakao 지도
  렌더링을 확인했고 콘솔 오류는 0건이었습니다.
- 정적 공간 레이어 9개는 AI 시작 시 EPSG:5179로 고정하고 STRtree를
  선생성합니다. ODsay·OSMnx·GLO-90·VWorld 입력은 영구 캐시에 보존해
  요청 경로에서 외부 전체 계산을 반복하지 않습니다.
- 우선 OD 3개(`북구청→부산역`, `부산진구청→서면역`,
  `부산역→서면역`)를 사전 준비한 뒤 캐시 응답은 각각 2.07초, 1.72초,
  1.88초였고 모든 후보가 실제 보행 geometry와 90m 지형 상태를
  갖췄습니다. 야간에는 그늘을 0%로 만들지 않고 `not_daylight`로
  명시합니다.
- 사람 평가용 `route_features.jsonl`은 0바이트,
  `route_labels.csv`는 헤더만이며 사람 후보·승인 모델은 아직 없습니다.
  2026-07-24의 부산 OD 3개·후보 9개·프로필 평가 54개는 모델 계약을
  확인한 기술 스모크 기록입니다. 확대 학습 입력과 혼동하지 않도록 당시
  평가 원문과 모델은 현재 배포 저장소에서 제외했습니다. 기본
  `RANKER_TIER=human_validated`의 `/model/status`는 계속 `ready=false`입니다.
- `ROUTE_MODE=live` 규칙 베이스라인은 모델 없이 동작합니다. 운영
  `ROUTE_MODE=ai`, `RANKER_TIER=human_validated`는 사람 라벨과 관리자
  승인 모델이 준비되기 전까지 비활성입니다. 비운영 초기 평가 비교는
  새 아티팩트를 생성한 뒤 `RANKER_TIER=bootstrap_baseline`을 명시한
  로컬 환경에서만 사용할 수 있습니다.
- 제공된 2023~2025 대중교통 만족도 압축파일은 161개 시군의 집단 평균
  데이터로 감사했습니다. OD·후보 경로·좌표·선택 순위가 없어 경로
  학습 라벨로 사용하지 않았고, 혼잡·환승 안내·교통약자 시설의 선택형
  직접 후기 항목과 데이터 감사 산출물로 반영했습니다.
- 실제 후보 9개에 대해 6개 프로필의 54개 외부 평가와 근거,
  평가 지침 해시·평가시각·피처 해시를 고정해 계약을 검증했습니다.
  이 결과는 부산 OD 3개뿐인 역사적 기술 스모크이며 실제 사용자 검증이나
  장애인 접근성 보장으로 표현하지 않습니다.
- GLO-90 경사는 실제 DEM 조회 기반의 약 90m 지형 추정입니다. 그늘은
  건물만 계산하며 나무·지형 그늘을 포함하지 않습니다.
- AI·백엔드·프론트 운영 이미지는 비루트·capability 제거·
  no-new-privileges로 실제 기동 검증했고, 백엔드 root filesystem은
  read-only 쓰기 차단까지 확인했습니다. CPU 전용 XGBoost 패키지로 AI
  이미지는 약 1.01GB에서 250MB로 줄였고, 앱 포트는 loopback에만
  바인딩해 외부 TLS 종료 계층을 필수로 둡니다.

## 구조

```text
KT-10/
├─ frontend/   React + Vite + TypeScript PWA (src/v2가 현재 지도 중심 shell)
├─ backend/    FastAPI + Kakao OAuth + PostgreSQL/Alembic + 후기 개인화
├─ ai/         실제 경로 수집 + 공간/지형 피처 + XGBRanker
├─ data/       앱 픽스처, 공간 원본/가공본, 데이터 카탈로그
└─ docs/       기획·구현·백엔드·데이터 문서
```

## 로컬 실행

저장소 루트에서 Python 환경을 만든 뒤 각 요구사항을 설치합니다.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r backend\requirements-dev.txt -r ai\requirements-dev.txt

# AI (8001)
$env:PYTHONPATH='ai'
.\.venv\Scripts\python.exe -m uvicorn main:app --app-dir ai --port 8001

# 백엔드 (새 터미널, 8002)
.\.venv\Scripts\python.exe -m uvicorn backend.app.main:app --port 8002

# 프론트 (새 터미널, 5173)
cd frontend
npm ci
npm run dev
```

PostgreSQL까지 한 번에 실행하려면 저장소 루트에서 `docker compose up --build`를 사용합니다. 로컬 키 입력 파일 `ai/.env`, `backend/.env`, `frontend/.env`는 이미 생성되며 Git에서 무시됩니다.

## 운영 배포

운영용 구성은 개발 서버와 소스 마운트를 사용하지 않고, Nginx가 빌드된
PWA와 같은 origin의 `/api`를 제공합니다. Compose의 앱 포트는 기본적으로
`127.0.0.1:8080`에만 바인딩되며, 공인 배포에는 별도 Caddy/Load
Balancer의 HTTPS 종료가 필수입니다.

```powershell
$env:PYTHONUTF8='1'
python scripts\prepare_deployment_env.py --import-existing
# 별도 전달 환경파일이 있으면 함께 가져오기:
# python scripts\prepare_deployment_env.py --import-existing --import-env C:\path\to\env
# .env.production의 외부 키와 PUBLIC_ORIGIN 입력
python scripts\prepare_deployment_env.py --check
docker compose --env-file .env.production -f docker-compose.prod.yml up -d --build
python scripts\prewarm_route_cache.py `
  --base-url http://localhost:8080 `
  --od-file data\precompute\priority_od_pairs.json `
  --max-cached-seconds 3
python scripts\verify_deployment.py --base https://your-domain.example
```

키별 콘솔 등록, HTTPS, 실제 데이터 종단 검증은 [운영 배포 가이드](docs/DEPLOYMENT.md)를 따릅니다.
카카오 JavaScript 키는 지도와 브라우저 Places SDK용이며 서버의 REST API
키를 대신하지 않습니다.
실제 보행 geometry용 TMAP 키가 없고 OSMnx 복구도 비활성화된 경우,
정류장·역 양 끝점을 이은 직선은 지도 연결선으로만 쓰며 경사나 주변
시설 피처를 만들지 않습니다.
우선 OD 사전 준비는 공급자 전체 원본을 복제하지 않고 실제 요청 가능성이
높은 OD의 ODsay 응답·보행 그래프·고도 표본·건물 corridor만 채웁니다.
시간에 따라 달라지는 태양 위치와 경로-그늘 교차는 요청 시 로컬에서
계산하므로 과거 시각의 그늘을 현재 값으로 재사용하지 않습니다.

## 초기 평가·학습

실제 후보 생성에는 AI 서버와 백엔드가 모두 실행 중이어야 합니다.
AI 서버가 실제 후보를 수집하고, 백엔드가 출발시각의 건물 그늘을 결합한
뒤 고정 스냅샷을 생성합니다. `LABELING_API_TOKEN`은
`backend/.env`와 배치 실행 환경에 같은 32자 이상 난수로 설정하고
로그·채팅·Git에 남기지 않습니다. 백엔드는 `ROUTE_MODE=ai`와
`AI_SERVER_URL`이 필요합니다.

키를 설정한 뒤 `ai/data/training/od_template.csv`를 검증 OD와
출발시각·상황 조합으로 확장합니다.

```powershell
$env:LABELING_API_TOKEN='<backend/.env와 같은 32자 이상 내부 토큰>'
$env:PYTHONPATH='ai'
.\.venv\Scripts\python.exe -m labeling.generate_batch `
  --od-file ai\data\training\od_template.csv `
  --output-dir ai\data\training\generated\initial_batch
```

배치는 공개 추천과 같은
`수집 → 건물 그늘 → enriched snapshot → 특성 라벨` 경로를 사용합니다.
`captured_at`은 실제 후보 수집시각, `shade_evaluated_at`은 태양·건물
그늘을 계산한 출발시각으로 분리되며 둘 다 스냅샷에 보존됩니다.

동결된 경로 사실을 블라인드 입력으로 사용하는 외부 평가는 별도
baseline입니다. 새 배치를 만들 때는 빈 평가표의 `evaluated_at`,
`relevance`, `rationale`를 실제 평가 결과로 모두 채워야 합니다.
기존·새 결과 모두 실사용자 검증 모델로 표현하거나 자동 승격하지
않습니다.

기존 사람 라벨 절차는 생성된 `labeling_sheet.csv`를 9명이 0~4
relevance로 평가하고, 확정본을 `route_labels.csv`, 같은 배치의 스냅샷을
`route_features.jsonl`로 둔 뒤 관리자 검토 전 후보를 학습합니다.

```powershell
$env:PYTHONPATH='ai'
.\.venv\Scripts\python.exe -m scoring.train `
  --labels ai\data\training\route_labels.csv `
  --features ai\data\training\route_features.jsonl `
  --output ai\data\rankers.human-candidate.zip
```

검증을 마친 후보만 파일 SHA-256을 고정해 관리자가 수동 승격합니다.

```powershell
$candidateSha = (Get-FileHash ai\data\rankers.human-candidate.zip -Algorithm SHA256).Hash.ToLowerInvariant()
.\.venv\Scripts\python.exe -m labeling.promote_human_candidate `
  --source ai\data\rankers.human-candidate.zip `
  --output ai\data\rankers.human-validated.zip `
  --expected-source-sha256 $candidateSha `
  --approved-by '<승인자>' `
  --approval-note '<검증 결과와 승인 근거>'
```

## 검증

```powershell
$env:PYTHONUTF8='1'
$env:PYTHONPATH='ai'
.\.venv\Scripts\python.exe -m pytest ai\tests -q
$env:PYTHONPATH='backend'
.\.venv\Scripts\python.exe -m pytest backend\tests -q
.\.venv\Scripts\python.exe -m compileall -q ai backend
cd frontend
npm test -- --run
npm run build
npm audit --audit-level=moderate
```

공급자와 출처·라이선스 확인 상태는 [data/catalog.json](data/catalog.json), 상세 운영 경계는 [docs/IMPLEMENTATION.md](docs/IMPLEMENTATION.md)를 참고하세요.
