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

- 일반·고령자·아동·청소년·장애인·임산부 6개 기본 프로필
- 짐 많음·유아차·계단 회피·그늘 우선·저상버스 우선·환승 최소 조건
- 실제 경로 후보 수집, GLO-90 지형 추정, 시간별 건물 그늘
- 경로 사실 특성 라벨과 프로필·조건 적합도 순위의 분리
- 지도 그늘 오버레이와 점수순 수평 경로 카드의 양방향 선택 동기화
- 로그인 사용자 후기의 즉시 개인화와 관리자 수동 전역 모델 절차
- 출처가 분리된 judge/사람/후기혼합/운영 모델 아티팩트
- PostgreSQL, PWA, 운영 Compose, readiness와 배포 검증 스크립트

하지만 아직 **실데이터까지 검증된 운영 완료 상태는 아닙니다**. 로컬
코드·DB·PWA·컨테이너 회귀는 통과했지만 외부 공급자 인증, 실제
후보·평가 데이터와 운영 모델이 남아 있습니다. 따라서 현재 검증 완료
범위는 고정 데모와 모델 없이 동작하는 규칙 기반 코드이며, 실제 `live`
종단 성공은 ODsay·VWorld 등 외부 설정 뒤 별도 확인해야 합니다.

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

## 6. 경사·그늘의 사실성 경계

- GLO-90은 약 90m 격자의 실제 DEM 기반 지형 추정이며 보도 실측 구배가
  아닙니다.
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

2026-07-24 현재 ODsay Server Key 실호출은 다음 오류로 실패했습니다.

```text
[ApiKeyAuthFailed] ApiKey authentication failed.
```

개발 요청의 공인 egress IPv4는 `119.202.222.84`입니다. ODsay
애플리케이션 Server 허용 IP에 이 값을 등록해야 합니다. 운영에서는
배포 서버/NAT의 별도 고정 egress 공인 IP를 등록해야 하며
`localhost`, 사설 IP, Docker 내부 IP 또는 프론트 도메인을 등록하지
않습니다.

현재 운영 환경파일에서 추가로 필요한 외부 값은 다음과 같습니다.

- `KAKAO_REST_API_KEY`
- `KAKAO_OAUTH_CLIENT_SECRET`
- `VWORLD_API_KEY`
- `OPENWEATHER_API_KEY`

`LABELING_API_TOKEN`은 준비 스크립트가 생성하도록 추가되어 있으므로 기존
`.env.production`은 스크립트를 다시 실행한 뒤 `--check`해야 합니다.
Kakao JavaScript 도메인·OAuth Redirect URI, VWorld 사용 도메인도 운영
origin에 맞춰 콘솔에서 등록해야 합니다. 현재 로컬 HTTP
`PUBLIC_ORIGIN`은 실제 운영 HTTPS origin으로 교체해야 합니다.

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
- 느린 이전 검색·재채점 응답이 최신 결과를 덮지 않는 요청 세대 제어
- 라벨링 후보 API 내부 토큰 보호

## 9. 아직 완료되지 않은 범위

### 외부 입력이 있어야 가능한 항목

1. ODsay 허용 IP 등록과 실제 `searchPubTransPathT`·`loadLane` 성공
2. Kakao Local/OAuth, VWorld, OpenWeather 키와 콘솔 설정
3. 부산 층화 OD의 실제 후보·그늘 스냅샷 생성
4. 외부 LLM judge 평가 또는 최소 9명 사람 평가
5. VWorld 높이 단위·결측률과 현장 건물 그늘 오차 표본 검증
6. 운영 HTTPS origin과 고정 egress IP 확정

### 최종 로컬 검증 결과

병렬 수정이 끝난 뒤 합쳐진 동일 작업본에서 전체 명령을 다시 실행했습니다.

| 검증 | 최종 상태 |
| --- | --- |
| Backend pytest | `100 passed, 1 skipped` |
| PostgreSQL opt-in E2E | `1 passed`; 중복후기 409 포함 |
| AI pytest | `59 passed, 1 skipped` |
| Frontend Vitest | `49 passed` |
| TypeScript/Vite PWA build | 통과; service worker·manifest 생성 |
| Python compileall / pip check | 통과 / broken requirement 0건 |
| Alembic PostgreSQL | `20260724_0002 (head)`; `check` 통과 |
| UTF-8/JSON 계약 | 통과 |
| npm audit | 취약점 0건 |
| Production Compose / Docker build | config 통과; AI·백엔드·프론트 이미지 빌드 통과 |
| 실제 브라우저 QA | 430px/1280px 통과; 3번째 지도-카드 동기화 유지; 콘솔 오류·경고 0건 |
| ODsay live E2E | 3건 모두 `ApiKeyAuthFailed`; 허용 IP 등록 대기 |
| 다른 실제 공급자 E2E | Kakao·VWorld·OpenWeather 외부 키 대기 |
| 원격 CI | 기능·문서 head `99494e5`의 5개 job 전체 성공; 최신 상태는 README CI 배지 참조 |

## 10. 배포 완료 기준

- [x] 6개 프로필·상황 조건 계약
- [x] 경로 사실 특성과 사용자 적합도 분리
- [x] 점수순 정렬과 비안전·비확률 설명
- [x] 지도-스와이프 카드 양방향 동기화와 대체 조작
- [x] 건물 그늘 오버레이와 미확인 값 보존
- [x] 사용자별 즉시 개인화와 관리자 수동 전역 모델 절차
- [x] 모델 tier·label origin·checksum 승격 분리
- [ ] ODsay 개발/운영 egress IP 등록과 실호출 통과
- [ ] VWorld 건물 높이·좌표·결측률 실응답 검증
- [ ] Kakao Local/OAuth, OpenWeather 운영 설정
- [ ] 실제 후보와 Judge 또는 사람 평가 데이터
- [ ] 선택한 tier의 검증 모델과 오프라인 비교 보고서
- [x] 최종 전체 로컬 테스트·생산 빌드·Docker 이미지 빌드
- [x] 모바일·데스크톱 브라우저 지도-카드 동기화 검증
- [x] 작업 단위별 커밋·푸시
- [x] 기능·문서 통합 `main` 원격 CI 5개 job 통과

모든 미완료 항목을 통과하기 전에는 “키만 넣으면 배포 완료” 또는
“실사용자 검증 AI”라고 표현하지 않습니다. 외부 모델 없이도 동작하는
규칙 기반 `live` 서비스와 모델 기반 `ai` 서비스의 완료 상태를 따로
보고합니다.
