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

키 값은 Git에 커밋하지 않습니다. `.env.production`은 `.gitignore`에 포함되어 있습니다.

## 3. 공급자 콘솔 설정

- Kakao Developers 웹 플랫폼 사이트 도메인에 `PUBLIC_ORIGIN`을 등록합니다.
- Kakao 로그인 Redirect URI에 `${PUBLIC_ORIGIN}/api/auth/kakao/callback`을 정확히 등록하고 Client secret을 활성화합니다.
- VWorld 키의 사용 도메인에 `PUBLIC_ORIGIN`을 등록합니다.
- ODsay, OpenWeather, 공공데이터포털 키가 활성 상태인지 확인합니다.

도메인 등록이 누락되면 키 문자열이 있어도 카카오 지도 401 또는 공급자 인증 오류가 발생합니다.

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

## 7. 운영 점검

```powershell
docker compose --env-file .env.production -f docker-compose.prod.yml logs --tail 200 backend ai frontend
docker compose --env-file .env.production -f docker-compose.prod.yml exec backend alembic -c backend/alembic.ini current
```

PostgreSQL `postgres-data` 볼륨은 별도 주기로 백업합니다. 전역 학습은 자동 갱신하지 않으며, 관리자가 동의 후기 데이터를 검토·가공한 뒤 승인된 절차로만 모델을 교체합니다.
