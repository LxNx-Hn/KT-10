# 운영 배포 가이드

운영 배포는 `docker-compose.prod.yml` 하나로 PostgreSQL, 실제 경로 수집 AI, FastAPI 백엔드, Nginx 정적 PWA를 함께 실행합니다. 프론트와 API를 같은 origin으로 제공하므로 OAuth 세션 쿠키와 CORS 구성이 단순하고 안전합니다.

## 1. 서버 준비

- Docker Engine과 Docker Compose v2
- HTTPS가 적용된 도메인
- 영구 볼륨을 보존할 디스크
- 최소 2 CPU, 4 GB RAM 권장

방화벽에는 외부용 `PORT`만 열고 PostgreSQL, AI, 백엔드 포트는 공개하지 않습니다.

## 2. 키 등록

저장소 루트에서 기존 로컬 `.env` 값을 비밀 노출 없이 가져오고 내부 비밀값을 생성합니다.

```powershell
$env:PYTHONUTF8='1'
python scripts\prepare_deployment_env.py --import-existing
```

생성된 `.env.production`에서 다음 값을 채웁니다.

- `PUBLIC_ORIGIN`: 최종 HTTPS origin, 예: `https://route.example.kr`
- `VITE_KAKAO_MAP_KEY`: 카카오 JavaScript 키
- `KAKAO_REST_API_KEY`, `KAKAO_OAUTH_CLIENT_SECRET`: 장소 검색·로그인
- `ODSAY_API_KEY`: 실제 경로 후보와 geometry
- `VWORLD_API_KEY`: 건물 도형·높이와 그늘
- `OPENWEATHER_API_KEY`: 실시간 날씨·대기
- `BUS_SERVICE_KEY`: 부산 버스 도착 정보
- 선택: `TMAP_API_KEY`: 보행 상세 보강
- `RANKER_TIER`: 기본 `human_validated`, 비운영 비교 데모에서만
  `judge_baseline`

`POSTGRES_PASSWORD`, `SESSION_SECRET`, `TRAINING_ANONYMIZATION_SALT`,
`LABELING_API_TOKEN`은 준비 스크립트가 생성합니다.
`LABELING_API_TOKEN`은 비용이 큰 라벨링 후보 API에만 쓰는 32자 이상의
내부 토큰이며 브라우저에 전달하지 않습니다. 키 값과
`.env.production`은 Git에 커밋하지 않습니다.

## 3. 공급자 콘솔 설정

- Kakao Developers 웹 플랫폼 사이트 도메인에 `PUBLIC_ORIGIN`을 등록합니다.
- Kakao 로그인 Redirect URI에 `${PUBLIC_ORIGIN}/api/auth/kakao/callback`을 정확히 등록하고 Client secret을 활성화합니다.
- VWorld 키의 사용 도메인에 `PUBLIC_ORIGIN`을 등록합니다.
- ODsay Server Key 애플리케이션에는 **실제 API 요청이 나가는 서버/NAT의
  고정 egress 공인 IPv4**를 등록합니다.
- OpenWeather, 공공데이터포털 키가 활성 상태인지 확인합니다.

도메인 등록이 누락되면 키 문자열이 있어도 카카오 지도 401 또는 공급자 인증 오류가 발생합니다.

2026-07-24 현재 로컬 개발 요청 출발지 공인 IPv4는
`119.202.222.84`입니다. 로컬 smoke test에는 이 값을 ODsay Server 허용
IP로 등록합니다. `localhost`, `127.0.0.1`, `192.168.x.x`, Docker
`172.x.x.x` 또는 프론트 도메인은 백엔드 Server Key의 허용 IP가
아닙니다. 이 개발 IP는 바뀔 수 있으므로 운영 배포에서는 고정 egress IP를
확보해 별도 등록해야 합니다.

## 4. 정적 설정과 이미지 빌드 검증

```powershell
$env:PYTHONUTF8='1'
python scripts\prepare_deployment_env.py --check
docker compose --env-file .env.production -f docker-compose.prod.yml config --quiet
docker compose --env-file .env.production -f docker-compose.prod.yml build
```

`--check`는 비밀값을 출력하지 않으며 필수 키, 내부 비밀값, HTTPS origin만 검사합니다. 실제 키 유효성은 마지막 스모크 검증에서 확인합니다.

## 5. 실행

```powershell
docker compose --env-file .env.production -f docker-compose.prod.yml up -d
docker compose --env-file .env.production -f docker-compose.prod.yml ps
```

마이그레이션은 백엔드 시작 시 Alembic head까지 자동 적용됩니다. 최초 실행 후 모든 컨테이너가 `healthy`인지 확인합니다.

## 6. 실제 데이터 종단 검증

```powershell
$env:PYTHONUTF8='1'
python scripts\verify_deployment.py --base https://route.example.kr
```

이 검증은 단순 healthcheck가 아니라 다음을 실제로 호출합니다.

- PWA manifest, service worker, Nginx 보안 헤더
- 운영 readiness와 필수 설정
- Kakao 장소 검색
- 실시간 날씨와 부산 버스
- 부산역→서면역 실제 후보 geometry
- 90m DEM 경사도 상태
- VWorld 건물 기반 주간 그늘 계산

모든 항목이 통과하기 전에는 실제 서비스 완료로 간주하지 않습니다. 공급자 오류 때 데모나 0값으로 자동 대체하지 않습니다.

추가로 6개 프로필과 짐 많음·유아차·계단 회피·그늘 우선·저상버스 우선·
환승 최소 조건이 동일 API 계약으로 처리되는지, 지도와 수평 경로 카드의
선택 상태가 동기화되는지 확인합니다. 점수는 `베이스라인 적합 점수`로
표시하고 안전도·성공확률이 아니라는 설명을 포함해야 합니다.

## 7. 운영 점검

```powershell
docker compose --env-file .env.production -f docker-compose.prod.yml logs --tail 200 backend ai frontend
docker compose --env-file .env.production -f docker-compose.prod.yml exec backend alembic -c backend/alembic.ini current
```

PostgreSQL `postgres-data` 볼륨은 별도 주기로 백업합니다. 전역 학습은 자동 갱신하지 않으며, 관리자가 동의 후기 데이터를 검토·가공한 뒤 승인된 절차로만 모델을 교체합니다.

운영 기본 `ROUTE_MODE=live`는 학습 모델 없이도 실제 후보를 규칙으로
비교합니다. `ROUTE_MODE=ai`로 배포하려면 선택한 tier의 모델을 이미지
빌드 전에 `ai/data/`에 준비해야 합니다.

| `RANKER_TIER` | 필요한 파일 | 운영 의미 |
| --- | --- | --- |
| `human_validated` | `rankers.human-validated.zip` | 관리자 승인 사람 모델 |
| `judge_baseline` | `rankers.judge-baseline.zip` | LLM judge 비교 데모, 실사용자 검증 아님 |

아카이브에는 프로필별 XGBoost JSON, 피처 스키마, 라벨 출처, 검증 지표와
각 모델의 SHA-256이 들어갑니다. 실행 가능한 pickle은 읽지 않습니다.
`rankers.human-candidate.zip`과
`rankers.review-mixed-candidate.zip`은 운영 파일이 아니며 파일명을
바꾸는 방식으로 승격하지 않습니다.

사람 평가 후보의 수동 승격은 검토한 원본 SHA-256을 명시해 실행합니다.

```powershell
$env:PYTHONPATH='ai'
$candidate = 'ai/data/rankers.human-candidate.zip'
$sha = (Get-FileHash $candidate -Algorithm SHA256).Hash.ToLowerInvariant()
.\.venv\Scripts\python.exe -m labeling.promote_human_candidate `
  --source $candidate `
  --output ai/data/rankers.human-validated.zip `
  --expected-source-sha256 $sha `
  --approved-by '<관리자 식별자>' `
  --approval-note '<검토 근거>'
```

위 명령은 `label_origin=human_reviewers`인 사람 후보만 허용합니다. 동의
후기가 섞인 후보와 judge 모델은 이 절차로 승격되지 않습니다.
