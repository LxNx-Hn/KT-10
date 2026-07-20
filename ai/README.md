# AI 경로 수집·순위화 파이프라인

운영 추천은 합성 라벨이나 규칙 점수로 학습하지 않습니다. ODsay/TMAP/OSMnx에서 실제 후보를 만들고, 저장된 공간 레이어와 Open-Meteo GLO-90 지형 피처를 결합한 뒤 9명 이상의 실제 라벨로 학습한 프로필별 `XGBRanker`가 후보 순서를 정합니다.

## API

- `GET /health`: 프로세스 상태
- `GET /model/status`: 검증 모델 준비 여부·버전·프로필
- `POST /labeling/candidates`: 모델 없이 초기 라벨링 후보와 피처 스냅샷 생성
- `POST /recommend`: 모델이 준비된 경우에만 실제 후보 순위화

ODsay 또는 TMAP 키가 없으면 해당 공급자는 `CollectorNotConfigured`로 기록됩니다. OSMnx만 키 없이 동작합니다. 모든 공급자가 실패하면 가짜 직선이나 0분 경로를 반환하지 않고 503을 반환합니다.

## 학습 자료

- `ai/data/training/route_features.jsonl`: 후보 생성 당시의 피처 스냅샷
- `ai/data/training/route_labels.csv`: `reviewer_id,group_id,route_id,profile,relevance,notes`
- relevance: 0(추천 불가)~4(가장 적합)
- 지원 프로필: `general`, `elderly`, `child`, `youth`, `disabled`, `pregnant`
- 최소 9명의 서로 다른 reviewer와 프로필별 복수 OD·복수 후보가 필요

`짐 많음`, `계단 회피`, `저상버스 우선`, 휠체어·보행보조기·최대 도보거리 조건은 경로 피처와의 상호작용 피처로 들어갑니다. 그 영향 계수는 라벨에서 학습하며 코드에 임의 가중치를 넣지 않습니다.

## 실행

```powershell
$env:PYTHONPATH='ai'
.\.venv\Scripts\python.exe -m pytest ai\tests -q
.\.venv\Scripts\python.exe -m uvicorn main:app --app-dir ai --port 8001
.\.venv\Scripts\python.exe -m labeling.generate_batch --od-file ai\data\training\od_template.csv
.\.venv\Scripts\python.exe -m scoring.train
```

후기 전역 후보 모델은 `backend/ml/export_consented_reviews.py`와 `backend/ml/train_global_candidate.py`로 생성합니다. 동의 데이터만 익명화하며 후보 모델은 `rankers.candidate.pkl`에 저장되어 운영 모델을 자동 덮어쓰지 않습니다.
