# 교통약자·이동취약자 맞춤형 경로 추천 PWA

부산광역시의 보행·대중교통 후보를 `경로 사실·특성 생성`과
`프로필·상황 적합도 산정`의 두 단계로 비교하는 PWA입니다. 결과는 적합
점수순으로 정렬하고, `빠른 길`, `경사가 완만한 길`, `그늘 많은 길`,
`환승이 단순한 길` 같은 사실 배지로 이유를 설명합니다.

최신 제품·모델·UI 기준은 [제품 의사결정 기준](docs/PRODUCT_DECISIONS.md),
현재 구현과 차단사항은
[현재 상태 보고서](docs/CURRENT_STATUS_AND_FOLLOW_UP_REPORT.md)를
기준으로 합니다.

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

- ODsay 대중교통 후보와 공식 `loadLane` geometry, TMAP/OSMnx 보행 geometry의 구간별 지도 오버레이
- 부산 전역 공간 레이어 결합: 쉼터, CCTV, AED, 휠체어 충전기, 스마트쉘터, 도시철도 접근성, 횡단보도, 정류장 등
- Open-Meteo Copernicus GLO-90 고도 기반 오르막·내리막·누적 상승량 추정(90m 해상도임을 UI에 명시)
- 태양 위치와 합성 건물 높이로 계산한 검증용 그늘 비율·지도 오버레이, VWorld 공공 건물 도형·높이 공급자(품질 상태 분리)
- `ROUTE_MODE=demo|live|ai` 공급자 선택과 실패 시 무단 폴백 금지
- 프로필별 XGBRanker, 초기 라벨링 후보 생성기와 모델 준비 상태 게이트
- 카카오 로그인 사용자만 PostgreSQL 프로필·후기·개인화 저장; 게스트는 개인화하지 않음
- 후기 기반 개인 온라인 모델과 동의 후기의 팀 승인 비중 제한 전역 후보 재학습(운영 모델 자동 교체 없음)
- 시설물 위치·운영상태 오류 신고와 관리자 검토 대기열
- 자주 바뀌는 상황 조건은 검색 UI에, 장기 이동지원 정보는 로그인 프로필에 분리

`data/ai/`는 데모·회귀검증 픽스처이고 임의 OD의 실제 경로가 아닙니다. 운영 기본 `live` 모드는 실제 외부 공급자 경로를 규칙으로 비교하므로 학습 모델이 없어도 동작합니다. `ROUTE_MODE=ai`의 학습 순위화는 `ai/data/rankers.pkl`이 준비되지 않으면 503으로 명시적으로 거부합니다.

그늘 데모의 입력·계산식·실데이터 교체 조건은 [docs/SHADE_RULE_DEMO.md](docs/SHADE_RULE_DEMO.md)를 참고하세요.

## 2026-07-24 상태

- `main`은 `origin/main`보다 로컬 9커밋 앞서며 아직 푸시되지 않았습니다.
- PostgreSQL·AI·백엔드·프론트 컨테이너는 정상 실행되지만 운영 readiness는
  `false`입니다.
- 현재 소스 상태는 장소·날씨 `mock`, 버스 `live`, 경로
  `verified-demo`, 건물 `synthetic-demo`, AI 모델 `inactive`입니다.
- `route_features.jsonl`은 0바이트, `route_labels.csv`는 헤더만 있고
  승인된 `rankers.pkl`이 없어 `/model/status`는 `ready=false`입니다.
- ODsay 키 값은 있으나 `ApiKeyAuthFailed`가 확인됐습니다. 로컬 백엔드
  Server Key 허용 IP에는 현재 공인 IPv4 `119.202.222.84`를 등록해야
  합니다.
- GLO-90 경사는 실제 DEM 조회 기반의 약 90m 지형 추정입니다. 그늘은
  건물만 계산하며 나무·지형 그늘을 포함하지 않습니다.

## 구조

```text
KT-10/
├─ frontend/   React + Vite + TypeScript PWA
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

운영용 구성은 개발 서버와 소스 마운트를 사용하지 않고, Nginx가 빌드된 PWA와 같은 origin의 `/api`를 제공합니다.

```powershell
$env:PYTHONUTF8='1'
python scripts\prepare_deployment_env.py --import-existing
# .env.production의 외부 키와 PUBLIC_ORIGIN 입력
python scripts\prepare_deployment_env.py --check
docker compose --env-file .env.production -f docker-compose.prod.yml up -d --build
python scripts\verify_deployment.py --base https://your-domain.example
```

키별 콘솔 등록, HTTPS, 실제 데이터 종단 검증은 [운영 배포 가이드](docs/DEPLOYMENT.md)를 따릅니다.

## 초기 평가·학습

키를 설정하고 AI 서버를 실행한 뒤 `ai/data/training/od_template.csv`를 부산역 중심 검증 OD로 확장합니다.

```powershell
$env:PYTHONPATH='ai'
.\.venv\Scripts\python.exe -m labeling.generate_batch `
  --od-file ai\data\training\od_template.csv
```

초기에는 동결된 경로 사실을 블라인드 입력으로 사용하는 LLM/Codex judge
평가를 베이스라인으로 만들 수 있습니다. 이 모델은
`rankers.judge-baseline.pkl`로 분리하고 실사용자 검증 모델로 표현하지
않습니다. 사람 평가 후보와 승인 운영 모델도 각각
`rankers.human-candidate.pkl`, `rankers.pkl`로 구분합니다.

기존 사람 라벨 절차는 생성된 `labeling_sheet.csv`를 9명이 0~4
relevance로 평가하고, 확정본을 `route_labels.csv`, 같은 배치의 스냅샷을
`route_features.jsonl`로 둔 뒤 학습합니다.

```powershell
$env:PYTHONPATH='ai'
.\.venv\Scripts\python.exe -m scoring.train
```

## 검증

```powershell
$env:PYTHONPATH='ai'
.\.venv\Scripts\python.exe -m pytest ai\tests -q
.\.venv\Scripts\python.exe -m pytest backend\tests -q
cd frontend
npm test -- --run
npm run build
```

공급자와 출처·라이선스 확인 상태는 [data/catalog.json](data/catalog.json), 상세 운영 경계는 [docs/IMPLEMENTATION.md](docs/IMPLEMENTATION.md)를 참고하세요.
