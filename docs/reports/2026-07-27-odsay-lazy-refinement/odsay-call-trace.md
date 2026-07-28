# ODsay 호출 추적 보고서 (2026-07-27)

기준 SHA `5e201c0c` + 미커밋 작업 변경분. 키·원본 좌표·전체 mapObj·토큰은 기록하지 않는다.

## 변경 전 호출 구조 (코드 분석)

`ai/collectors/odsay_collector.py` (구 버전):

| 순서 | endpoint | 발생 위치 | 조건 |
| --- | --- | --- | --- |
| 1 | searchPubTransPathT | `_collect_live_or_cached` | OD당 1회 (파일 캐시 miss 시) |
| 2..N | loadLane | `_build_candidate` inline | **후보별 1회**, 3개 고정 배치 동시 실행 |

후보 5개 요청의 최악 경로: 배치1(후보1·2·3) + 배치2(후보4·5·6 동시 시작 후 5개 절단)
→ loadLane 6회 + search 1회 = **7회**. 7번째 호출 발생 지점은 배치2에서 초과 조립된
6번 후보의 `_build_candidate` → `_load_lane`이다.

## 변경 후 호출 구조

| 단계 | endpoint | network 호출 | 위치 |
| --- | --- | ---: | --- |
| A. 후보 수집 | searchPubTransPathT | 1 | `collect()` — single-flight + 파일 캐시 + semaphore |
| B~F. base 후보·feature·ranking | (없음) | 0 | 정류장 관측 좌표 기반 estimated 표시 선형만 사용 |
| G1. 최종 1위 정밀화 | loadLane | 1 | backend `_refine_top_ranked_transit` → AI `/routes/refine-transit` |
| G2. 사용자 카드 선택 | loadLane | 신규 후보당 1 | backend `/api/routes/refine-transit` (재선택 0회) |

## 계측 필드 (ai/collectors/odsay_instrumentation.py)

로그 라인 `odsay_call`에 포함: correlation id, endpoint, 비식별 identity hash(sha256 12자),
cache hit/miss, single-flight leader/follower, 실제 network 여부, retry 번호(현재 0 고정),
HTTP 상태, 소요시간(ms), outcome, 논리적 호출 위치(call_site).
프로세스 counter: 논리 호출·network 호출·cache 절감·single-flight 절감·semaphore 대기시간.
retry는 정상 기본 호출 수와 분리된 필드로 집계된다(현 구현은 자동 retry 없음 → 항상 0).

## mock transport 실측 (ai/tests/test_odsay_lazy_refinement.py)

| 시나리오 | 기대 | 실측 |
| --- | --- | --- |
| collect() 1회 | search net 1, loadLane 0 | PASS |
| 동일 OD 동시 10 collect | search net 1 (follower 9) | PASS |
| 동일 후보 동시 10 refine | loadLane net 1 | PASS |
| 서로 다른 후보 10 refine, semaphore=2 | 동시 HTTP ≤ 2 | PASS |
| leader 오류 | 전체 대기자에 오류 전파 + in-flight 제거 | PASS |
| 상한 초과 후보 요청 | 명시적 오류(silent clamp 없음) | PASS |

## 세션 누적 기대값 (설계 계약, backend 테스트로 개별 검증)

후보 5개: 1위만 확인 2회 / 다른 후보 1개 +1 / 5개 전부 확인 6회 / 재선택 +0.
후보 7개: 1위만 확인 2회 / 7개 전부 확인 8회 / 재선택 +0.
총 ODsay = search 1 + 실제 정밀화된 고유 후보 수 + 명시적 retry(현재 0).

## Live 시도

실제 ODsay 네트워크 호출 2회 시도(예산 50회) — 두 로컬 키 모두 `[ApiKeyAuthFailed]`.
오류 비은폐·오류 미캐시·일일 counter 기록(2회, 잔여 998 추정)을 확인.
일일 counter는 `odsay-daily-counter-YYYYMMDD.json`(영속 cache 디렉터리)에 원자적으로 기록되며
70/80/90/100% 경고는 단위테스트로 검증(100% 경고 로그 확인). 계정 전체 quota가 아니라
`observed_service_calls_today` / `estimated_remaining_service_budget` 표현만 사용한다.

생성시각: 2026-07-26T15:36Z (UTC)
