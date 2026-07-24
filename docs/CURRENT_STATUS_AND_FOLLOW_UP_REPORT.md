# 교통약자 맞춤형 경로 추천 서비스 현재 상태 및 후속 요구사항

기준일: 2026-07-24 (Asia/Seoul)

## 1. 이 문서의 기준

이 문서는 현재 `main` 작업본의 제품·데이터·모델·배포 상태를 설명합니다.
제품 의사결정의 단일 기준은 `PRODUCT_DECISIONS.md`이고, 이 문서는 구현
완료와 외부 입력 대기를 구분하는 상태 보고서입니다.

아래 검증 수치는 이 문서를 최신화하기 직전 동일 작업본에서 다시 실행한
결과입니다. 기능 변경은 작업 단위별로 `main`에 커밋·푸시했으며 최종
문서 커밋까지 푸시한 뒤 최신 GitHub Actions 결과를 인계 시점에 다시
확인합니다.

## 2. 종합 결론

현재 작업본에는 다음 배포 후보 기능이 구현되어 있습니다.

- `feature/frontend-map-first-v2` 디자인을 프로덕션 진입점으로 사용한
  Kakao 지도 중심 PWA와 모바일 바텀시트·상세 drawer
- 일반·고령자·아동·청소년·장애인·임산부 6개 기본 프로필
- 짐 많음·유아차·계단 회피·그늘 우선·저상버스 우선·환승 최소 조건
- 실제 경로 후보 수집, GLO-90 지형 추정, 시간별 건물 그늘
- 경로 사실 특성 라벨과 프로필·조건 적합도 순위의 분리
- 지도 그늘 오버레이와 점수순 수평 경로 카드의 양방향 선택 동기화
- 로그인 사용자 후기의 즉시 개인화와 관리자 수동 전역 모델 절차
- 출처가 분리된 judge/사람/후기혼합/운영 모델 아티팩트
- 제공 만족도 원본 감사와 설문 기반 직접 후기 관측 항목
- PostgreSQL, PWA, 운영 Compose, readiness와 배포 검증 스크립트

하지만 아직 **모든 실데이터까지 검증된 운영 완료 상태는 아닙니다**.
Kakao JavaScript Places와 ODsay 실제 후보·`loadLane`, 규칙 기반 `live`
추천의 로컬 종단은 통과했습니다. GLO-90 계산과 건물 그늘 알고리즘은
데모·계약 테스트를 통과했지만, 현재 live 구성에는 실제 보행 geometry와
VWorld 키가 없습니다. 따라서 추정 직선 연결선으로 경사·주변 시설을
계산하지 않고, 합성 데이터 범위 밖 그늘도 0%로 만들지 않습니다.
OpenWeather, Kakao 로그인, 실제 평가 데이터와 운영 모델도 외부 입력이
남아 있습니다.

## 3. 현재 구현 계약

### 3.1 추천 흐름

정식 흐름은 다음과 같습니다.

1. 백엔드가 AI 서버에서 ODsay/TMAP 실제 후보와 기본 피처를 수집합니다.
2. 백엔드가 VWorld 건물 도형·높이와 출발시각 태양 위치로 그늘을
   계산합니다.
3. AI 서버가 그늘까지 포함한 불변 피처 스냅샷과 사실 특성 라벨을
   생성합니다.
4. `ROUTE_MODE=live`는 규칙 점수, `ROUTE_MODE=ai`는 선택한 ranker
   tier로 후보를 점수순 정렬합니다.
5. 로그인 사용자의 후기 상태를 허용 범위에서 혼합하고, 지도와 카드가
   동일한 선택 경로를 표시합니다.

AI 서버의 직접 `POST /recommend`는 건물 그늘 결합을 우회하므로 409로
비활성화되어 있습니다. 사용자 추천 진입점은 백엔드
`POST /api/routes/recommend`입니다.

### 3.2 사실 라벨과 점수

경로에는 `제일 빠른 길`, `도보가 짧은 길`, `환승이 적은 길`,
`경사가 완만한 길`, `그늘 많은 길`, 확인된 `계단 없는 길` 같은
결정적 사실 라벨을 붙입니다. `그늘 많은 길`의 ID는 `most_shade`입니다.
모든 후보의 그늘이 0이거나 미확인이면 이 라벨을 만들지 않습니다.

경로 순서는 프로필·조건 적합 점수순입니다. 모델의 표시 숫자는 후보군
내 상대 적합 지수이지 안전도, 성공확률 또는 사고확률이 아닙니다.
특성 배지를 노출하려고 낮은 점수 경로를 강제로 올리지 않습니다.

### 3.3 시간과 계보

`route-feature-snapshot-v2`는 다음 시간을 분리합니다.

- `captured_at`: 실제 후보와 피처를 수집한 시각
- `shade_evaluated_at`: 요청 출발시각에 맞춰 그늘을 계산한 시각

미래 출발시각의 그늘을 계산해도 수집 시각을 미래로 기록하지 않습니다.
`group_id`는 한 번의 비교 후보군, `holdout_group_id`는 시간·조건과
무관한 동일 방향 OD이며, 학습/검증은 후자를 기준으로 분리합니다.

### 3.4 미확인 값

계단, 승강기, 저상버스, 혼잡, 건물 높이, geometry와 공급자 실패를
숫자 0 또는 `없음`으로 바꾸지 않습니다. 확인되지 않은 값은
`null`/미확인으로 남기고 UI에는 `확인 필요`로 표시합니다.
ODsay 역·정류장 양 끝점을 이은 추정 직선은 지도 연결선으로만 사용하며
GLO-90 경사, CCTV·시설 밀도와 건물 그늘의 분석 geometry로 사용하지
않습니다.

## 4. 모델·라벨 상태

현재 실제 확인 상태는 다음과 같습니다.

| 산출물 | 현재 상태 |
| --- | --- |
| `ai/data/training/route_features.jsonl` | 실제 후보 0건 |
| `ai/data/training/route_labels.csv` | 헤더만 존재 |
| Judge 완성 평가 JSONL | 없음 |
| `rankers.judge-baseline.zip` | 없음 |
| `rankers.human-candidate.zip` | 없음 |
| `rankers.review-mixed-candidate.zip` | 없음 |
| `rankers.human-validated.zip` | 없음 |
| AI `/model/status` | 모델 준비 전에는 `ready=false` |

모델 파일은 실행 가능한 pickle이 아니라 checksum manifest와 프로필별
XGBoost JSON을 담은 ZIP입니다.

| 파일 | 용도 | 자동 운영 승격 |
| --- | --- | --- |
| `rankers.judge-baseline.zip` | 외부 LLM judge 기반 비교선 | 금지 |
| `rankers.human-candidate.zip` | 최소 9명 사람 평가 기반 후보 | 금지 |
| `rankers.review-mixed-candidate.zip` | 동의 후기를 제한적으로 섞은 후보 | 금지 |
| `rankers.human-validated.zip` | SHA-256과 승인 근거를 확인한 운영 모델 | 해당 없음, 관리자 수동 생성 |

Judge 템플릿·검증·학습 코드는 구현되어 있지만 LLM을 실제로 호출해
평가행을 채우는 실행기는 없습니다. 실제 후보를 먼저 동결하고 외부 LLM
평가 결과의 `evaluated_at`, 0~4 relevance와 rationale을 받아야 judge
모델을 만들 수 있습니다. 이를 사람 검증 모델로 표현하면 안 됩니다.

## 5. 라벨링·개인화 상태

초기 사람/Judge 배치는 백엔드의 보호된
`POST /api/routes/labeling-candidates`로 생성합니다. 요청에는 32자 이상의
`LABELING_API_TOKEN`을 `X-Labeling-Token`으로 보내며, 추천과 동일한 실제
후보 수집→건물 그늘→동결 스냅샷 흐름을 사용합니다.

사람 라벨 학습기는 다음을 검사합니다.

- 6개 프로필 전체와 최소 9명 평가자
- 라벨·스냅샷 경로 집합의 정확한 일치
- 동일 평가자의 중복 라벨
- 피처 스냅샷 해시와 시간·출처 계보
- 동일 방향 OD가 train/validation에 함께 들어가지 않는 holdout

로그인 사용자의 리뷰는 저장 직후 개인 상태에 반영합니다. 초기 정책은
첫 5건 동안 베이스라인 우선, 개인 영향 최대 35%입니다. 동일 사용자가
같은 impression에 중복 리뷰를 남길 수 없도록 API와 DB 제약을 둡니다.
전역 학습에는 명시적으로 동의한 후기만 익명화해 별도 후보를 만들고,
운영 파일은 관리자가 수동 승인합니다. 데모·과거 비적격 후기는
`export_report.json`에 제외 수와 사유를 남기며, 실제 후기의 연속 0~4
relevance를 사람 직접 평가의 정수 라벨 계약과 구분합니다.

제공된 2023~2025 대중교통 만족도 압축파일은 161개 시군의 지역·집단별
평균으로 감사했습니다. OD, 후보 경로, 좌표, 실제 선택 순위가 없어
XGBRanker relevance나 프로필 가중치로 변환하지 않았습니다. 대신 앱
후기에 혼잡, 환승 안내·정보, 교통약자 시설 이용 불편의 nullable 1~5
직접 관측 항목을 추가했습니다. 이 항목은 현재 개인화·전역 relevance를
자동 변경하지 않으며 상세 근거는
`TRANSIT_SATISFACTION_DATA_AUDIT_2026-07-24.md`와
`data/audits/public_transport_satisfaction_2023_2025.audit.json`에
보존합니다.

## 6. 경사·그늘의 사실성 경계

- GLO-90은 약 90m 격자의 실제 DEM 기반 지형 추정이며 보도 실측 구배가
  아닙니다.
- GLO-90과 주변 시설 계산은 공급자가 확인한 실제 보행 geometry에만
  적용합니다. 지도용 추정 직선은 분석에서 제외합니다.
- 서비스의 `그늘`은 현재 건물 그늘입니다. 나무 그늘과 지형 그림자는
  신뢰할 수 있는 입력·검증자료가 없어 계산하지 않습니다.
- 합성 건물은 `estimated_demo`, VWorld 공공 건물은
  `estimated_public`으로 구분합니다.
- 건물 높이 결측·0은 0m 건물로 바꾸지 않습니다. 일부 높이만 있으면
  `lower_bound`, 확인된 높이가 없으면 `unavailable`입니다.
- 야간과 geometry 미확인은 그늘 0%로 표시하지 않습니다.
- 지도 폴리곤과 경로 구간 색상은 계산 결과의 시각화이며 현장 그늘을
  보장하지 않습니다.

## 7. 외부 환경 차단사항

2026-07-24 ODsay Server Key에 개발 egress IP를 등록한 뒤
`searchPubTransPathT`와 `loadLane` 실호출이 모두 통과했습니다.
`북구청→부산역`은 원시 후보 20개, 상위 후보 3개를 반환했고 최종
collector는 약 1.2초였습니다. 대중교통 geometry는 `exact`, TMAP 키가
없는 도보 연결선은 `estimated`, 전체는 `mixed`입니다. 이 연결선은
지도 표시에는 남지만 경사·공간 피처에는 들어가지 않습니다.

운영에서는 배포 서버/NAT의 별도 고정 egress 공인 IP를 ODsay Server
허용 IP에 등록해야 합니다. `localhost`, 사설 IP, Docker 내부 IP 또는
프론트 도메인은 등록 대상이 아닙니다.

현재 운영 환경파일에서 추가로 필요한 외부 값은 다음과 같습니다.

- `KAKAO_REST_API_KEY`
- `KAKAO_OAUTH_CLIENT_SECRET`
- `VWORLD_API_KEY`
- `OPENWEATHER_API_KEY`
- `TMAP_API_KEY` 또는 명시적인
  `OSMNX_WALK_GEOMETRY_ENABLED=true`

`LABELING_API_TOKEN`은 준비 스크립트가 생성하도록 추가되어 있으므로 기존
`.env.production`은 스크립트를 다시 실행한 뒤 `--check`해야 합니다.
Kakao JavaScript 도메인·OAuth Redirect URI, VWorld 사용 도메인도 운영
origin에 맞춰 콘솔에서 등록해야 합니다. 현재 로컬 HTTP
`PUBLIC_ORIGIN`은 실제 운영 HTTPS origin으로 교체해야 합니다.
운영 Compose는 앱 포트를 기본 `127.0.0.1`에만 열며, Caddy/Nginx 또는
관리형 Load Balancer가 TLS를 종료하고 `Host`와
`X-Forwarded-Proto=https`를 덮어써야 합니다.

## 8. 이번 작업본에서 완료된 코드 범위

- 6개 프로필과 이동 조건의 FE/BE/AI 계약 통일
- 미확인 공간·시설 값을 0으로 오인하지 않는 점수·표시
- 결정적 사실 특성 라벨과 해시 계보
- 건물 그늘을 포함한 추천·라벨링 공통 피처 경로
- `captured_at`/`shade_evaluated_at`, query group/holdout OD 분리
- 모델 상대 적합 지수와 선택확률의 의미 분리
- 안전한 JSON ZIP 모델 포맷과 사람 후보의 checksum 기반 수동 승격
- Judge/사람/동의 후기 라벨 출처 분리
- 후기 중복 방지 DB migration과 API 충돌 처리
- 수평 카드, 지도 선택 동기화, 버튼·키보드·스크린리더 대체 조작
- v2 지도 중심 UI의 Kakao Places 검색, 실제 추천, 프로필·이동 조건,
  음성·후기·신고·설정 기능 연결과 가짜 초기 경로 제거
- 느린 이전 검색·재채점 응답이 최신 결과를 덮지 않는 요청 세대 제어
- 라벨링 후보 API 내부 토큰 보호
- Kakao JavaScript Places 기반 `북구청`·`부산역` 실제 검색과
  공급자 출처가 확인되지 않은 demo 응답 차단
- ODsay 축약 `mapObj`의 `loadLane` 정규화와 보행 geometry 공급자
  지연 제어
- 추정 직선 보행선의 DEM·공간 피처 제외와 CCTV `카메라대수` 합산
- 만족도 원본 감사, 기계 판독 감사 JSON, 선택형 직접 후기 관측값
- 공급자 입력·페이지 무결성·모델 아티팩트·OD holdout 계약 강화
- AI·백엔드·프론트 비루트·capability 제거·no-new-privileges, 백엔드
  read-only root filesystem과 HTTPS handoff
- 게스트 로그인 상태 조회의 정상 204 계약과 실제 브라우저 E2E

## 9. 아직 완료되지 않은 범위

### 외부 입력이 있어야 가능한 항목

1. Kakao REST/OAuth, VWorld, OpenWeather 키와 콘솔 설정
2. TMAP 키 또는 운영에서 허용할 OSMnx 실제 보행 geometry
3. 부산 층화 OD의 실제 VWorld 그늘 스냅샷 생성
4. 외부 LLM judge 평가 또는 최소 9명 사람 평가
5. VWorld 높이 단위·결측률과 현장 건물 그늘 오차 표본 검증
6. 운영 HTTPS origin과 고정 egress IP 확정·등록

### 최종 로컬 검증 결과

병렬 수정이 끝난 뒤 합쳐진 동일 작업본에서 전체 명령을 다시 실행했습니다.

| 검증 | 최종 상태 |
| --- | --- |
| Backend pytest | `173 passed, 1 skipped` |
| PostgreSQL opt-in E2E | `1 passed`; 중복후기 409 포함 |
| AI pytest | `144 passed, 2 skipped` |
| Frontend Vitest | `90 passed` (14 files) |
| 만족도 실제 원본 감사 | `5 passed`; archive checksum·3개 workbook·감사 JSON 재현 |
| Playwright 접근성 | `5 passed, 1 expected desktop skip` |
| TypeScript/Vite PWA build | 통과; service worker·manifest 생성 |
| Python compileall / Ruff / Bandit / pip check | 모두 통과 / broken requirement 0건 |
| Alembic PostgreSQL | `20260724_0003 (head)`; `check` 통과 |
| UTF-8/JSON 계약 | 통과 |
| npm audit | 취약점 0건 |
| Production Compose / Docker runtime | 비밀 아닌 smoke 값으로 4개 서비스 healthy; AI·백엔드·프론트 비루트 UID·capability 0·no-new-privileges, 백엔드 read-only root 확인 |
| AI 운영 이미지 | 약 1.01GB→250MB; CPU XGBoost import와 9개 공간 레이어 로드 통과 |
| 현재 `.env.production --check` | 외부 키 4개와 exact walking geometry 누락을 정상 차단 |
| 실제 브라우저 QA | v2 모바일·데스크톱에서 Kakao `북구청`·`부산역`, ODsay 경로 3개, 2순위 카드·지도 선택, 상세 4탭·프로필 6종 확인; live Playwright `1 passed`, 콘솔 오류·경고 0건 |
| ODsay live E2E | 개발 IP 인증, search/loadLane, 부산진구청·북구청 OD 통과 |
| Kakao Places live E2E | 등록 origin `http://localhost:5173`에서 두 검색어 통과; `127.0.0.1`은 별도 도메인 등록 전 명시적 실패 |
| 다른 실제 공급자 E2E | Kakao REST·OAuth, VWorld, OpenWeather 외부 키 대기 |
| 원격 CI | v2 기능·문서 HEAD `dd2c2a6`의 5개 job 전체 성공; production 이미지와 hardened runtime 포함 ([run 30086352908](https://github.com/LxNx-Hn/KT-10/actions/runs/30086352908)) |

## 10. 배포 완료 기준

- [x] 6개 프로필·상황 조건 계약
- [x] 경로 사실 특성과 사용자 적합도 분리
- [x] 점수순 정렬과 비안전·비확률 설명
- [x] 지도-스와이프 카드 양방향 동기화와 대체 조작
- [x] 건물 그늘 오버레이와 미확인 값 보존
- [x] 사용자별 즉시 개인화와 관리자 수동 전역 모델 절차
- [x] 모델 tier·label origin·checksum 승격 분리
- [x] ODsay 개발 egress IP 등록과 실호출 통과
- [ ] ODsay 운영 서버의 고정 egress IP 등록
- [ ] 운영 exact walking geometry용 TMAP 또는 OSMnx 결정·설정
- [ ] VWorld 건물 높이·좌표·결측률 실응답 검증
- [ ] Kakao Local/OAuth, OpenWeather 운영 설정
- [ ] 운영 도메인 TLS 종료와 외부 443·내부 loopback handoff
- [ ] 실제 후보와 Judge 또는 사람 평가 데이터
- [ ] 선택한 tier의 검증 모델과 오프라인 비교 보고서
- [x] 최종 전체 로컬 테스트·생산 빌드·Docker 이미지 빌드
- [x] 모바일·데스크톱 브라우저 지도-카드 동기화 검증
- [x] 작업 단위별 커밋·푸시
- [x] v2 기능·문서 통합 `main` 원격 CI 5개 job 통과

모든 미완료 항목을 통과하기 전에는 “키만 넣으면 배포 완료” 또는
“실사용자 검증 AI”라고 표현하지 않습니다. 외부 모델 없이도 동작하는
규칙 기반 `live` 서비스와 모델 기반 `ai` 서비스의 완료 상태를 따로
보고합니다.
