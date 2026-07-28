# PR #18 호출 계약 matrix (mock transport 검증)

- PR branch: `feature/lazy-transit-refinement`
- branch HEAD (작업 전): `5d60a3b75853074dc5f5cb3cd662feaa745cee39`
- `origin/main`: `d9f8392f7f39ea8518098ea6c49488ff254e3899`
- merge-base: `5e201c0c1567bc93b89a4f98b605f21814edc08c`
- 실행 환경: macOS (darwin 25.2.0), Python 3.12.2 venv, Node/vitest
- 실행 명령
  - `python -m pytest ai/tests/test_pr18_call_matrix.py -q`
  - `python -m pytest backend/tests/test_pr18_regressions.py -q`
  - `npx vitest run`
- worker 수: Backend 1 · AI 1 (단일 uvicorn process, `--workers` 없음)
- 실제 network 호출: **0회** (전부 mock transport)
- 생성시각: 2026-07-28 18:12 KST

## 검증 방식

`httpx.AsyncClient`를 endpoint별 호출 수를 세는 mock으로 교체해 실제 요청 수를
직접 집계했다. 추정값이 아니라 mock transport가 실제로 받은 요청 수다.

## Matrix

| 시나리오 | ODsay search | loadLane | TMAP | 근거 테스트 |
| --- | ---: | ---: | ---: | --- |
| 최초 후보 3개 | 1 | 0 | 유효 후보만 | `test_initial_collection_uses_one_search_and_no_load_lane[3]` |
| 최초 후보 5개 | 1 | 0 | 유효 후보만 | 동 `[5]` |
| 최초 후보 7개 | 1 | 0 | 유효 후보만 | 동 `[7]` |
| 최초 후보 10개 | 1 | 0 | 유효 후보만 | 동 `[10]` |
| 최종 1위 정밀화 | 0 | 1 | 0 | `test_first_refinement_uses_exactly_one_load_lane` |
| 2위 첫 선택 | 0 | 1 | 0 | 동일 경로(Backend `refine-transit`) |
| 2위 재선택 | 0 | **0** | 0 | `test_reselecting_same_candidate_adds_no_load_lane` |
| profile 변경 | 0 | 0 | 0 | `test_rescore_reuses_route_set_without_provider_calls` |
| option 변경 | 0 | 0 | 0 | 동일 (`avoidStairs`) |
| departure time 변경 | 0 | 0 | 0 | `test_time_refresh_reuses_server_candidates_without_route_collection` |
| 빠른 2→3→4 선택 | 0 | 최대 1 | 0 | `2→3→4 빠른 이동에서 마지막 후보만 refinement해야 한다` |
| focus 이동 | 0 | **0** | 0 | `Tab focus 이동은 loadLane refinement를 유발하지 않아야 한다` |
| cooldown 중 재선택 | 0 | **0** | 0 | `test_failed_refinement_blocks_immediate_retry` (6개 오류 분류) |
| 만료 token | 0 | 0 | 0 | `test_rescore_with_expired_token_returns_409_without_new_token` |
| stale 이전 검색 응답 | — | — | — | store patch **0건** (`검색 A 응답이 검색 B의 …`) |

`최초 총 ODsay = search 1 + 최종 1위 loadLane 1 = 2`는 Backend가 순위 확정 후
`_refine_top_ranked_transit`으로 1위만 정밀화하므로 성립한다. 후보 수(3·5·7·10)와
무관하다.

## Single-flight·동시성

| 항목 | 결과 | 근거 |
| --- | --- | --- |
| 동일 OD 동시 10요청 | search **1회** | `test_same_origin_destination_search_is_single_flight` |
| 동일 mapObj 동시 10요청 | loadLane **1회** | `test_same_map_object_refinement_is_single_flight` |
| 동일 후보 Backend 동시 10요청 | AI refine **1회** | `test_concurrent_requests_for_same_candidate_call_provider_once` |
| semaphore 상한 준수 | peak ≤ 2 (`ODSAY_MAX_CONCURRENT_REQUESTS=2`) | `test_concurrency_limit_is_respected` |
| follower 취소 → leader 유지 | 유지 | `single_flight` 대기자 수 기반 취소 |
| 마지막 대기자 취소 → 실행 취소 | network 0 | `test_cancelled_while_waiting_for_semaphore_is_not_counted_as_network` |

## Retry 집계

retry는 정상 호출 수와 분리해 `OdsayCallCounters.retries`에 기록한다. 이번 검증
시나리오에서 발생한 retry는 **0건**이며, 위 표의 수치에 retry는 포함되지 않는다.

## 계측 정확성

`network_attempted` / `network_completed` / `network_failed`를 실제 transport
직전·직후에 기록한다. 다음은 attempted에 포함되지 않는다.

- cache hit (`test_cache_hit_is_not_counted_as_network_attempt`)
- single-flight follower
- semaphore 대기 중 취소·timeout
- 요청 coroutine 생성 전 실패

## 미측정 항목

| 항목 | 상태 | 사유 |
| --- | --- | --- |
| 실제 ODsay live 호출 수 | `NOT MEASURED` | 유효 ODsay 키·staging 환경 없음 |
| 실제 latency (cold/warm p50·p95) | `NOT MEASURED` | 위와 동일. mock 결과와 혼합하지 않음 |
| VWorld 실제 HTTP 호출 수 | `NOT MEASURED` | 유효 VWorld 키 없음 |
