# AI 경로 수집·순위화 파이프라인

운영 추천은 합성 라벨이나 규칙 점수로 학습하지 않습니다. 일반 요청은
ODsay 대중교통과 TMAP 보행 후보를 수집하고, 휠체어 요청은 ODsay 대중교통과
OpenRouteService wheelchair 보행 후보를 수집합니다. OSMnx 보행 geometry
복구는 `OSMNX_WALK_GEOMETRY_ENABLED=true`인 일반 요청 환경에서만 사용하며
기본값은 응답 지연을 막기 위해 `false`입니다. 운영 경사는 메모리에 적재한 부산
QGIS 90m DEM을 사용하고, 지역 DEM 범위 밖은 Open-Meteo GLO-90을
fallback으로 사용합니다. 백엔드는 출발시각의 건물 그늘을 계산하고 마지막으로
동결된 enriched snapshot을 프로필별 `XGBRanker`가 비교합니다.

사람 평가용 `ai/data/training/route_features.jsonl`은 비어 있고
`route_labels.csv`에는 헤더만입니다. 별도 초기 평가 데이터셋은
`training/bootstrap_baseline/`의 380 OD·실제 후보 1,137개·6개 프로필
평가 6,822개이며 `rankers.bootstrap-baseline.zip`을 학습했습니다.
사람 평가와 관리자 승격을 거친 모델은 아직 없습니다. 현재 배포 기준선은
동결된 초기 평가 데이터로 학습한 `bootstrap_baseline` AI 경로 추천 모델이며,
사람 평가 완료나 휠체어 접근성 보장을 뜻하지 않습니다.

## 공개 경로와 내부 API

클라이언트가 사용하는 정식 추천 경로는 백엔드
`POST /api/routes/recommend`입니다. `ROUTE_MODE=ai`에서 백엔드는 다음
순서를 강제합니다.

1. AI `POST /labeling/candidates`로 실제 후보·기본 스냅샷 수집
2. 백엔드에서 VWorld 또는 명시한 건물 공급자로 출발시각 그늘 계산
3. AI `POST /labeling/enriched-snapshots`로 고정 피처 해시와 사실 특성 생성
4. AI `POST /rank/candidates`로 선택한 모델 tier의 후보 순위화

AI의 직접 `POST /recommend`는 그늘 보강을 우회할 수 있어 비활성화되어
항상 409를 반환합니다.

AI 내부 API는 다음과 같습니다.

- `GET /health`: 프로세스 상태
- `GET /model/status`: 선택한 tier의 준비 여부·버전·프로필
- `POST /labeling/candidates`: 모델 없이 실제 후보와 기본 피처 스냅샷 생성
- `POST /labeling/enriched-snapshots`: 건물 그늘을 포함한 최종 스냅샷·사실 특성 생성
- `POST /rank/candidates`: 준비된 모델로 이미 보강된 후보만 순위화
- `POST /recommend`: 409를 반환하는 비활성 호환 endpoint

초기 평가 배치는 백엔드
`POST /api/routes/labeling-candidates`만 호출합니다. 이 endpoint는 공개
추천과 같은 수집·그늘·enriched snapshot 경로를 재사용하며
`LABELING_API_TOKEN`과 `X-Labeling-Token` 헤더가 일치해야 합니다.
토큰은 32자 이상이어야 하고 로그·채팅·Git에 남기지 않습니다.

공급자 키가 없으면 해당 공급자는 `CollectorNotConfigured`로 기록됩니다.
일반 요청에서 모든 실제 경로 공급자가 실패하면 가짜 직선이나 0분 경로로
대체하지 않고 503을 반환합니다. 일반 ODsay 후보 안의 보행 구간은 TMAP을
우선 사용하고, TMAP이 없거나 실패하면 opt-in된 OSMnx를 시도합니다. 둘 다
사용할 수 없으면 화면 연결선만 `estimated`로 명시하며 시간·거리를 새로
추정하지 않습니다.

휠체어 설정은 일반 경로와 분리됩니다. 모든 실제 보행·환승 구간은 ORS
wheelchair profile의 계단·노면·평탄도·폭·턱·경사·접근 제한과
`extra_info` 전 구간 coverage를 통과해야 합니다. 버스는 모든 탑승 구간의
저상버스 여부가 확인돼야 하고, 도시철도는 공식 엘리베이터 동선이 확인된
출구 좌표로 지상 보행을 다시 계산합니다. 확인되지 않은 후보는 ORS 호출 전에도
닫힌 방식으로 제외하고, ORS가 없거나 실패하면 TMAP 결과로 대체하지 않습니다.

운영 휠체어 요청은 TMAP 네트워크를 호출하지 않습니다. 배포·데이터 갱신 때
`searchOption=30`으로 사전 수집한 캐시에서 같은 ORS 선형과 일치하는
`turnType=128/129` 안내점 또는 `facilityType=19/20` 시설 구간만 물리
경사로 좌표로 공개합니다. QGIS 90m DEM의 지형 경사도는 별도 피처이며
경사로 또는 계단 대체 경사로로 해석하지 않습니다.

물리 경사로 TMAP 캐시는 사용자 요청이 아니라 배포·데이터 갱신 단계에서
AI 컨테이너의 `/app/ai`를 작업 디렉터리로 두고 다음처럼 준비합니다.

```bash
python -m data_tools.precollect_tmap_ramps \
  --od-catalog data/training/od_catalog.csv \
  --report /app/data/audits/tmap_ramp_precollection.audit.json \
  --artifact-dir data/precomputed/tmap
```

성공 응답은 키를 포함하지 않는 스키마 검증 캐시로 내보내며 AI 이미지에
포함됩니다. 운영 요청은 쓰기 캐시와 이 읽기 전용 fallback만 확인합니다.
시간 경과만으로 만료시키지 않고, TMAP 계약·정규화 규칙이 바뀌면 코드의
데이터 버전을 올린 뒤 갱신 작업을 다시 수행합니다. 인증·쿼터·일시 오류는
artifact에 기록하지 않습니다.

로컬 Geofabrik PBF에 명시된 `highway=steps + ramp=no` 계단은 별도 배치로
가공합니다. 휠체어 경로가 이 선형을 통과하면 ORS 결과라도 거부하며, ramp 태그
누락을 `ramp=no`로 추정하지 않습니다.

```bash
PYTHONPATH=ai python -m data_tools.extract_osm_wheelchair_blockers
```

보고서가 `complete`가 아니면 기본 종료코드는 1입니다. 부분 실패를 운영
완료로 간주하지 않으며, 키·쿼터·일시 오류 응답은 캐시에 저장하지 않습니다.

## 스냅샷과 학습 자료

- `ai/data/training/route_features.jsonl`: 후보 생성 당시의 고정 피처 스냅샷
- `ai/data/training/route_labels.csv`: 확정한 사람 평가
- `captured_at`: 실제 후보와 원천 피처를 수집한 시각
- `shade_evaluated_at`: 태양 위치와 건물 그늘을 계산한 출발시각
- `feature_snapshot_hash`: 피처와 provenance를 묶은 변경 감지 해시
- relevance: 0(확인된 필수조건과 양립 불가)~4(가장 적합)
- 지원 프로필: `general`, `elderly`, `child`, `youth`, `disabled`, `pregnant`
- 실제 사람 모델: 모든 평가 항목에 최소 9명의 서로 다른 reviewer 필요

`짐 많음`, `유아차`, `그늘 우선`, `환승 최소`, `계단 회피`,
`저상버스 우선`, 휠체어·보행보조기·최대 도보거리 조건은 경로 피처와의
상호작용 피처로 들어갑니다. 그 영향 계수는 라벨에서 학습하며 코드에
임의 가중치를 넣지 않습니다. 원천값이 미확인이면 0으로 바꾸지 않고
`null`을 유지합니다.

## 안전한 모델 artifact

모델은 실행 가능한 pickle이 아니라 checksum이 포함된 ZIP archive로
저장합니다. 각 archive에는 manifest와 6개 프로필의 XGBoost JSON만
허용되며 로드 전에 경로·크기·SHA-256을 검증합니다.

- `ai/data/rankers.human-candidate.zip`: 사람 평가 학습 결과, 관리자 검토 전
- `ai/data/rankers.human-validated.zip`: checksum을 고정해 수동 승인한 운영 모델
- `ai/data/rankers.bootstrap-baseline.zip`: 초기 평가 기반 비운영 baseline
- `ai/data/rankers.review-mixed-candidate.zip`: 동의 후기를 제한적으로 혼합한 후보

기본 `RANKER_TIER=bootstrap_baseline`은 동결된 초기 평가 artifact를
로드합니다. `human_validated`는 사람 평가와 수동 승인 후에만 선택합니다.
후기 혼합 후보는 운영 모델로 자동 승격되지 않습니다.

## 실행과 초기 사람 평가

테스트와 AI 서버 실행:

```powershell
$env:PYTHONPATH='ai'
.\.venv\Scripts\python.exe -m pytest ai\tests -q
.\.venv\Scripts\python.exe -m uvicorn main:app --app-dir ai --port 8001
```

다른 터미널에서 `backend/.env`의 `ROUTE_MODE=ai`,
`AI_SERVER_URL=http://localhost:8001`, 실제 공급자 설정과
`LABELING_API_TOKEN`을 확인하고 백엔드를 실행합니다.

```powershell
.\.venv\Scripts\python.exe -m uvicorn backend.app.main:app --port 8002
```

세 번째 터미널에서 백엔드와 같은 토큰으로 실제 라벨링 패키지를
생성합니다.

```powershell
$env:LABELING_API_TOKEN='<backend/.env와 같은 32자 이상 내부 토큰>'
$env:PYTHONPATH='ai'
.\.venv\Scripts\python.exe -m labeling.generate_batch `
  --od-file ai\data\training\od_template.csv `
  --output-dir ai\data\training\generated\initial_batch
```

사람 평가를 확정한 뒤 관리자 검토 전 모델을 학습합니다.

```powershell
.\.venv\Scripts\python.exe -m scoring.train `
  --labels ai\data\training\route_labels.csv `
  --features ai\data\training\route_features.jsonl `
  --output ai\data\rankers.human-candidate.zip
```

검증한 파일의 SHA-256을 고정하고 승인자·근거를 남겨야만 운영
artifact로 수동 승격할 수 있습니다.

```powershell
$candidateSha = (Get-FileHash ai\data\rankers.human-candidate.zip -Algorithm SHA256).Hash.ToLowerInvariant()
.\.venv\Scripts\python.exe -m labeling.promote_human_candidate `
  --source ai\data\rankers.human-candidate.zip `
  --output ai\data\rankers.human-validated.zip `
  --expected-source-sha256 $candidateSha `
  --approved-by '<승인자>' `
  --approval-note '<검증 결과와 승인 근거>'
```

초기 평가 baseline의 데이터셋, 평가 입력 계약, 재생성·학습 명령은
[초기 평가 baseline](docs/BASELINE_EVALUATION.md)에 있습니다. 현재
모델의 프로필별 OD holdout 지표와 학습 계보는
`rankers.bootstrap-baseline.metadata.json`에 고정돼 있습니다.

동의 후기 기반 전역 후보는
`backend/ml/export_consented_reviews.py`와
`backend/ml/train_global_candidate.py`로 생성합니다. 후기 데이터는
동의·익명화·출처 검증을 통과해야 하며 결과는
`rankers.review-mixed-candidate.zip`에만 저장됩니다. 이 파일은
`human_reviewers` 전용 승격 도구의 대상이 아니며 운영 모델을 자동으로
덮어쓰지 않습니다. exporter는 eligible·제외 후기 수와 제외 사유를
`export_report.json`에 기록하고, 후보 학습기는 이 보고서와 실제 라벨
행 수가 일치할 때만 연속 0~4 후기 relevance를 반올림 없이 읽습니다.
