# 경사·그늘 규칙 데모 검증 보고서

검증일: 2026-07-23 (Asia/Seoul)

2026-07-24 추가: 이 문서는 당시 실행 증거를 보존합니다. 이후 확정된
6개 프로필, 6개 상황 조건, judge 베이스라인, 점수·스와이프 UI 기준은
`PRODUCT_DECISIONS.md`를 따릅니다. 아래의 `rankers.pkl`과 테스트 수치는
2026-07-23 당시 기록이며 현재 모델 계약은 안전한
`rankers.*.zip`, 최신 검증 상태는
`CURRENT_STATUS_AND_FOLLOW_UP_REPORT.md`를 기준으로 합니다.

## 결론

`main` 브랜치의 부산진구청→서면역 고정 OD에서 경사·태양 위치·합성 건물 높이 기반 그늘 계산과 규칙 기반 경로 비교가 실행됩니다. API, 프론트 상호작용, 폴백 약도 오버레이까지 확인했습니다.

실제 ODsay 경로, 실제 Kakao 지도, VWorld 공공 건물 실응답, Kakao 로그인은
외부 키 또는 애플리케이션 설정이 준비되지 않아 완료로 판단하지 않습니다.
PostgreSQL을 사용한 추천→노출 기록→후기→사용자별 상태 갱신은 별도 E2E로
검증했습니다.

## 확인된 데모 결과

2026-07-23 14:00 KST, 폭염 시나리오 요청에서 다음 3개 대표 경로가 반환됐습니다.

| 경로 | 대표 특성 | 그늘 | 지형 | 규칙 베이스라인 점수 |
|---|---|---:|---|---:|
| r1-overpass | 제일 빠른 길 | 10% | GLO-90 추정 | 76.1 |
| r2-subway | 경사도 적은 길 | 0% | GLO-90 추정 | 89.6 |
| r4-regularbus | 그늘 많은 길 | 16% | GLO-90 추정 | 85.9 |

그늘 값은 합성 건물 높이를 사용한 기능 검증값입니다. API와 UI에서
`demo`/`데모 건물 높이`를 함께 표시합니다. 이 표의 점수는 후보 비교를
위한 데모 적합도이며 안전도·접근 가능 확률이 아닙니다. 운영 UI는 순위를
크게 표시하고 점수는 `베이스라인 적합 점수`로 보조 표시합니다.

## 환경변수 점검

다운로드 파일의 값은 출력하지 않고 키 존재·인증 결과만 확인했습니다.

| 항목 | 결과 |
|---|---|
| ODsay | 당시 값 존재, 스모크 테스트 `ApiKeyAuthFailed`; 당시 개발 Server 허용 IP 등록 필요 |
| Kakao JavaScript | 값 존재, 로컬 도메인 Referer를 포함한 SDK 요청 HTTP 401 |
| 부산버스 | 값 존재, 백엔드 검색 API HTTP 200 |
| TAGO 지하철 | 값 존재, 현재 앱에서 소비하는 설정/수집기 없음 |
| Kakao REST | 없음, 장소검색은 mock |
| OpenWeather | 없음, 날씨는 mock |
| PostgreSQL | Docker PostgreSQL 16 정상, Alembic 최신, 실제 후기 E2E 통과 |
| VWorld 건물 WFS | 공급자 구현 완료, API 키 없음으로 실제 부산 응답 미검증 |
| Kakao 로그인 | REST/OAuth/세션 비밀키 구성 미완료 |
| 전역 XGBRanker | `rankers.pkl` 없음, 라벨·피처 데이터 0행 |

기본 경로 모드는 `ROUTE_MODE=demo`로 고정했습니다. 키가 존재해도 자동으로 live/ai 모드가 되지 않으며, 선택한 공급자가 준비되지 않으면 503/502로 명시적으로 실패합니다.

2026-07-24 실행 중인 개발 환경의 `/api/readiness`는 `ready=false`이고
장소·날씨 `mock`, 버스 `live`, 경로 `verified-demo`, 건물
`synthetic-demo`, AI 파이프라인 `inactive`를 보고했습니다. AI의
`route_features.jsonl`은 0바이트, `route_labels.csv`는 헤더만 있으며
`/model/status`는 `ready=false`입니다.

## 개인화 정책

- 실제 로그인 사용자별 온라인 상태를 후기 저장 직후 갱신
- 초기 데모 설정: 학습률 0.25, 정규화 0.02
- 개인 예측 최대 영향 35%, 사전 후기 5건
- 후기 보상: 이용 가능 45%, 만족도 35%, 재이용 20%
- 미확인 피처는 0과 구분
- 전역 후보 모델은 관리자가 동의 후기 검토 후 수동 생성
- 후보 모델은 운영 모델을 자동 덮어쓰지 않음

초기 파일럿 정책은 2026-07-23 승인됐습니다. PostgreSQL에 테스트 사용자를
만들고 추천→서명 토큰→노출 기록→후기 저장→개인화 상태 1회 갱신을 실제
트랜잭션으로 확인한 뒤 테스트 데이터는 삭제했습니다. Kakao 계정 로그인
자체는 REST/OAuth/세션 비밀키가 없어 검증하지 못했습니다.

## 공공 건물 데이터 점검

부산광역시 건물 CSV 실파일은 포털 표시 64,999행과 달리 292,069행이었고
좌표·도형·건물 ID가 없었습니다. 높이 0은 136,897행, 300m 초과는 6행,
최대값은 19,860,821m였으므로 VWorld footprint와 추정 조인하지 않습니다.

대신 footprint와 `height`를 동일 피처로 제공하는 VWorld
`LT_C_BLDGINFO` WFS 공급자를 구현했습니다. 높이 결측·0은 0m로 대체하지
않고 그림자 계산에서 제외하며, 높이 커버리지를 응답에 남깁니다. 자세한
근거는 `docs/BUILDING_DATA_AUDIT_2026-07-23.md`에 기록했습니다.

## 검증 결과

| 검증 | 결과 |
|---|---|
| backend pytest | 68 passed, PostgreSQL E2E 1 skipped by default |
| PostgreSQL opt-in E2E | 1 passed |
| AI pytest | 32 passed, 1 skipped |
| frontend Vitest | 32 passed |
| TypeScript/Vite PWA build | passed |
| Python compileall | passed |
| UTF-8/JSON 계약 | passed |
| Docker Compose config | passed |
| Docker image build | AI/backend/frontend passed |
| Docker runtime health | PostgreSQL/AI/backend/frontend healthy |
| Alembic upgrade/check | latest, no new operations |
| pip check | passed |
| npm audit | 0 vulnerabilities |
| 실제 브라우저 경로 검색 | passed |
| 그늘 오버레이 보기/숨기기 | passed |

AI 테스트는 캐시 없는 전국 버스정류장·CCTV 공간 레이어 로딩을 포함해
확인했습니다. 기본 묶음의 ODsay 라이브 모듈은 명시 실행이 아니어서
스킵됐고, `RUN_LIVE_TESTS=1`로 별도 실행한 3개 테스트는 모두
`ApiKeyAuthFailed`로 실패해 당시 설정에서 키 인증이 되지 않음을
재확인했습니다.

## 당시 남아 있던 외부 작업

1. 당시 ODsay 애플리케이션의 Server 허용 IP에 개발 공인 IPv4
   `119.202.222.84` 등록 후 인증 재검증
2. Kakao JavaScript 키와 `http://127.0.0.1:5173`/운영 도메인 등록 확인
3. Kakao REST/OAuth client secret, 세션 비밀키, 후기 익명화 salt 설정
4. VWorld API 키 발급 후 부산 응답의 좌표계·높이 단위·결측률 표본 검증
5. 실제 보행 geometry에 대한 시간대별 현장 그늘 오차 측정
6. 동결 경로 사실의 LLM/Codex judge 베이스라인을 생성하고 사람 라벨
   후보와 분리해 비교
7. 실제 사용자 라벨 후보 검증 후 관리자가 운영 모델 교체 승인
