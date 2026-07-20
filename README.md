# 교통약자·이동취약자 맞춤형 경로 추천 PWA

서비스 권역은 부산광역시 전역이고, MVP의 실제 검증은 부산역 일대를 우선합니다. Kakao Maps는 배경지도와 오버레이 렌더링에 사용하고, 대중교통 후보는 ODsay, 보행 후보는 TMAP과 OpenStreetMap/OSMnx에서 수집합니다. 후보 순서는 9명 이상의 실제 라벨로 학습한 XGBoost learning-to-rank 모델이 정합니다.

사용자에게 임의의 “접근성 점수”를 보여주지 않습니다. 대신 소요시간, 도보거리, 환승, 계단·승강기·저상버스 확인 상태, 90m DEM 기반 지형 추정과 각 경로의 장점을 표시합니다. 미확인 값은 0이나 “없음”으로 바꾸지 않습니다.

## 현재 구현

- ODsay 대중교통 후보와 공식 `loadLane` geometry, TMAP/OSMnx 보행 geometry의 구간별 지도 오버레이
- 부산 전역 공간 레이어 결합: 쉼터, CCTV, AED, 휠체어 충전기, 스마트쉘터, 도시철도 접근성, 횡단보도, 정류장 등
- Open-Meteo Copernicus GLO-90 고도 기반 오르막·내리막·누적 상승량 추정(90m 해상도임을 UI에 명시)
- 합성 Y 라벨 없는 9인 초기 라벨링 → 프로필별 XGBRanker 학습 게이트
- 카카오 로그인 사용자만 PostgreSQL 프로필·후기·개인화 저장; 게스트는 개인화하지 않음
- 후기 기반 개인 온라인 모델과 동의 후기의 팀 승인 비중 제한 전역 후보 재학습(운영 모델 자동 교체 없음)
- 시설물 위치·운영상태 오류 신고와 관리자 검토 대기열
- 자주 바뀌는 `짐 많음`, `계단 회피`는 검색 UI에, 장기 이동지원 정보는 로그인 프로필에 분리

`data/ai/`는 데모·회귀검증 픽스처이고 임의 OD의 실제 경로가 아닙니다. 실서비스 추천은 `ai/data/rankers.pkl`과 실제 외부 공급자 응답이 모두 준비되어야 하며, 준비되지 않으면 AI API가 503으로 명시적으로 거부합니다.

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

## 초기 9인 라벨링

키를 설정하고 AI 서버를 실행한 뒤 `ai/data/training/od_template.csv`를 부산역 중심 검증 OD로 확장합니다.

```powershell
$env:PYTHONPATH='ai'
.\.venv\Scripts\python.exe -m labeling.generate_batch `
  --od-file ai\data\training\od_template.csv
```

생성된 `labeling_sheet.csv`를 9명이 0~4 relevance로 평가하고, 확정본을 `ai/data/training/route_labels.csv`, 같은 배치의 스냅샷을 `route_features.jsonl`로 둔 뒤 학습합니다.

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
