# FastAPI 백엔드

백엔드는 프론트 계약, Kakao OAuth, PostgreSQL 영속화, 후기 서명·개인화와 AI 서버 어댑터를 담당합니다.

## 주요 API

- `GET /api/health`, `/api/places/search`, `/api/weather`
- `GET /api/bus/stops`, `/api/bus/arrivals/{stopId}`
- `POST /api/routes/recommend`
- `GET /api/auth/kakao/login`, callback, `/api/auth/me`, logout
- `PUT /api/me/preferences`
- `POST /api/route-impressions`, `/api/route-reviews`
- `POST /api/facility-reports`
- 관리자: 시설 신고 목록·검토 상태 변경

실공급자가 설정된 상태에서 호출이 실패하면 mock으로 위장하지 않고 502를 반환합니다. 키가 아예 없는 개발 모드의 장소·날씨·버스·기존 점수 엔진은 명시적인 데모 픽스처입니다. 운영 경로는 `AI_SERVER_URL`을 사용해야 합니다.

## PostgreSQL

`DATABASE_URL=postgresql+psycopg://...`만 허용합니다. 앱 시작 시 Alembic head로 마이그레이션합니다. 로컬 Docker Compose는 PostgreSQL 16과 healthcheck를 포함합니다.

## 카카오 로그인

등록 Redirect URI는 `http://localhost:8002/api/auth/kakao/callback`입니다. REST API 키, 활성화된 Client secret, 무작위 `SESSION_SECRET`, PostgreSQL이 모두 있어야 로그인 API가 활성화됩니다. OAuth `state`는 10분 HttpOnly 쿠키로 검증하며 서비스 세션은 14일 HttpOnly SameSite=Lax 쿠키입니다.

## 후기 보안

추천 응답의 `feedbackToken`은 서버가 route ID, model version, raw feature snapshot을 서명한 값입니다. 로그인 사용자는 먼저 impression을 기록하고 그 ID로 리뷰를 제출해야 합니다. 클라이언트가 임의로 보낸 피처는 학습에 사용하지 않습니다.
