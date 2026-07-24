# FastAPI 백엔드

백엔드는 프론트 계약, Kakao OAuth, PostgreSQL 영속화, 후기 서명·개인화와 AI 서버 어댑터를 담당합니다.

프로필·조건·점수의 최신 계약은 `PRODUCT_DECISIONS.md`를 따릅니다. 기본
프로필은 일반·고령자·아동·청소년·장애인·임산부 6개이며, 짐 많음·유아차·
계단 회피·그늘 우선·저상버스 우선·환승 최소는 매 검색의 상황 조건으로
분리합니다.

## 주요 API

- `GET /api/health`, `/api/readiness`, `/api/places/search`, `/api/weather`
- `GET /api/bus/stops`, `/api/bus/arrivals/{stopId}`
- `POST /api/routes/recommend`
- 내부 라벨링: `POST /api/routes/labeling-candidates`
- `GET /api/auth/kakao/login`, callback, `/api/auth/me`, logout
- `PUT /api/me/preferences`
- `POST /api/route-impressions`, `/api/route-reviews`
- `POST /api/facility-reports`
- 관리자: 시설 신고 목록·검토 상태 변경

경로 공급자는 `ROUTE_MODE=demo|live|ai`로 명시합니다. `live`는
`AI_SERVER_URL`의 실제 후보 수집 API를 사용하고 백엔드에서 건물 그늘,
동결 피처 스냅샷, 규칙 특성·개인화를 적용합니다. `ai`는 동일한
수집→그늘→enriched snapshot 흐름 뒤 AI 서버의 `/rank/candidates`로
명시한 모델 tier를 적용합니다. AI 서버의 직접 `/recommend`는 그늘 결합을
우회하므로 409로 비활성화되어 있습니다. 필요한 서버 URL이나 키가 없으면
503, 선택한 공급자 호출이 실패하면 502를 반환하며 데모로 바꾸지
않습니다. 장소·날씨·버스는 개발 환경에서 각 키가 없는 경우 상태에
표시된 데모 픽스처를 사용하지만, 운영 Compose는 해당 키를 모두 필수로
검사합니다.

초기 사람/Judge 배치는 `POST /api/routes/labeling-candidates`로만
생성합니다. 이 API는 추천과 같은 실제 후보·건물 그늘 피처를 동결하며
32자 이상의 `LABELING_API_TOKEN`을 `X-Labeling-Token` 헤더로 요구합니다.
토큰은 내부 작업자만 사용하고 프론트엔드에 노출하지 않습니다.

추천 응답은 경로 사실·특성과 사용자 적합도를 분리해야 합니다.

- 사실: 시간, 도보거리, 환승, 계단·승강기·저상버스 확인 상태, 경사,
  그늘과 데이터 품질
- 특성 배지: 빠른 길, 완만한 길, 그늘 많은 길, 환승이 단순한 길 등
- 적합도: 프로필·상황 조건·장기 이동지원 설정을 적용한 베이스라인 점수와
  순위
- 필수조건: 확인된 위반만 제외하고 미확인은 `확인 필요`로 유지

경로 카드와 지도는 같은 `routeId` 선택 상태를 사용합니다. 경로 순서는
적합 점수순이며 특정 특성 배지를 보여 주기 위한 강제 재정렬은 하지
않습니다.

`GET /api/readiness`는 키 값 없이 운영 필수 설정의 충족 여부와 누락 항목을 반환합니다. 공급자 키의 실제 유효성은 `scripts/verify_deployment.py`로 종단 검증합니다.

그늘 건물 공급자는 `BUILDING_SOURCE=demo|vworld`로 별도 선택합니다.
`vworld`에는 `VWORLD_API_KEY`가 필요하며 `LT_C_BLDGINFO`의 도형과 높이를
같은 피처에서 조회합니다. 높이 결측·0은 0m 건물로 바꾸지 않고 그림자
계산에서 제외합니다.

피처 계보는 실제 후보 수집시각 `captured_at`과 요청 출발시각의 그늘
계산시각 `shade_evaluated_at`을 분리합니다. 같은 비교 후보는 하나의
`group_id`를 공유하고, 시간·조건과 무관한 동일 방향 OD는
`holdout_group_id`를 공유합니다.

## PostgreSQL

`DATABASE_URL=postgresql+psycopg://...`만 허용합니다. 앱 시작 시 Alembic
head로 마이그레이션합니다. `20260724_0002` migration은 동일
사용자·동일 route impression의 중복 후기를 DB에서도 차단합니다. 로컬
Docker Compose는 PostgreSQL 16과 healthcheck를 포함합니다.

## 카카오 로그인

등록 Redirect URI는 `http://localhost:8002/api/auth/kakao/callback`입니다. REST API 키, 활성화된 Client secret, 무작위 `SESSION_SECRET`, PostgreSQL이 모두 있어야 로그인 API가 활성화됩니다. OAuth `state`는 10분 HttpOnly 쿠키로 검증하며 서비스 세션은 14일 HttpOnly SameSite=Lax 쿠키입니다.

## 후기 보안

추천 응답의 `feedbackToken`은 서버가 route ID, model version, raw feature snapshot을 서명한 값입니다. 로그인 사용자는 먼저 impression을 기록하고 그 ID로 리뷰를 제출해야 합니다. 클라이언트가 임의로 보낸 피처는 학습에 사용하지 않습니다.

사용자별 온라인 개인화는 첫 5건 동안 베이스라인을 우선하며 최대 영향은
35%입니다. 게스트는 개인화 상태를 저장하지 않습니다. 전역 후보 학습은
동의 후기만 익명화·검토한 뒤 관리자가 수동으로 수행하고 운영 모델을
자동 교체하지 않습니다.

합성 데모 경로의 서명에는 `demo_route_candidate`와
`training_eligible=false`를 기록합니다. 전역 exporter는 검증된
`live_route_candidate`와 `training_eligible=true`만 허용하고 원본
스냅샷 해시·출처·두 시간 필드를 다시 검증합니다. 동의 후기를 섞은
산출물은 `rankers.review-mixed-candidate.zip`으로 분리되며 사람 전용
운영 승격 절차를 통과할 수 없습니다. exporter는 eligible·제외 후기 수와
제외 사유를 `export_report.json`에 기록하며, 후보 학습기는 이 보고서와
라벨 행 수를 대조합니다.

## ODsay 인증

ODsay는 프론트 Web Key가 아니라 AI/백엔드에서 Server Key로 호출합니다.
2026-07-24 개발 요청 출발지 공인 IPv4 등록 후 실제
`searchPubTransPathT`·`loadLane` 호출이 통과했습니다.
ODsay 애플리케이션의 Server 허용 IP에는 API 요청을 보내는 공인 IP를 등록하며
`localhost`, `127.0.0.1`, 사설 IP나 Docker 내부 IP를 등록하지 않습니다.
배포 환경에서는 운영 서버/NAT의 고정 egress 공인 IP를 별도로
등록합니다.
