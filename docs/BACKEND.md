# FastAPI 백엔드

백엔드는 프론트 계약, Kakao OAuth, PostgreSQL 영속화, 후기 서명·개인화와 AI 서버 어댑터를 담당합니다.

## 주요 API

- `GET /api/health`, `/api/readiness`, `/api/places/search`, `/api/weather`
- `GET /api/bus/stops`, `/api/bus/arrivals/{stopId}`
- `POST /api/routes/recommend`
- `GET /api/auth/kakao/login`, callback, `/api/auth/me`, logout
- `PUT /api/me/preferences`
- `POST /api/route-impressions`, `/api/route-reviews`
- `POST /api/facility-reports`
- 관리자: 시설 신고 목록·검토 상태 변경

경로 공급자는 `ROUTE_MODE=demo|live|ai`로 명시합니다. `live`는 `AI_SERVER_URL`의 실제 후보 수집 API를 사용하고 백엔드에서 그늘·규칙 특성·개인화를 적용합니다. `ai`는 같은 서버의 학습 모델 순위화를 사용합니다. 필요한 서버 URL이나 키가 없으면 503, 선택한 공급자 호출이 실패하면 502를 반환하며 데모로 바꾸지 않습니다. 장소·날씨·버스는 개발 환경에서 각 키가 없는 경우 상태에 표시된 데모 픽스처를 사용하지만, 운영 Compose는 해당 키를 모두 필수로 검사합니다.

`GET /api/readiness`는 키 값 없이 운영 필수 설정의 충족 여부와 누락 항목을 반환합니다. 공급자 키의 실제 유효성은 `scripts/verify_deployment.py`로 종단 검증합니다.

그늘 건물 공급자는 `BUILDING_SOURCE=demo|vworld`로 별도 선택합니다.
`vworld`에는 `VWORLD_API_KEY`가 필요하며 `LT_C_BLDGINFO`의 도형과 높이를
같은 피처에서 조회합니다. 높이 결측·0은 0m 건물로 바꾸지 않고 그림자
계산에서 제외합니다.

## PostgreSQL

`DATABASE_URL=postgresql+psycopg://...`만 허용합니다. 앱 시작 시 Alembic head로 마이그레이션합니다. 로컬 Docker Compose는 PostgreSQL 16과 healthcheck를 포함합니다.

## 카카오 로그인

등록 Redirect URI는 `http://localhost:8002/api/auth/kakao/callback`입니다. REST API 키, 활성화된 Client secret, 무작위 `SESSION_SECRET`, PostgreSQL이 모두 있어야 로그인 API가 활성화됩니다. OAuth `state`는 10분 HttpOnly 쿠키로 검증하며 서비스 세션은 14일 HttpOnly SameSite=Lax 쿠키입니다.

## 후기 보안

추천 응답의 `feedbackToken`은 서버가 route ID, model version, raw feature snapshot을 서명한 값입니다. 로그인 사용자는 먼저 impression을 기록하고 그 ID로 리뷰를 제출해야 합니다. 클라이언트가 임의로 보낸 피처는 학습에 사용하지 않습니다.
