# cache · single-flight · route-set 동시성 보고서 (2026-07-27)

기준 SHA `5e201c0c` + 미커밋 작업 변경분.

## cache 구조

| cache | 키 | schema | TTL | 오류 캐시 |
| --- | --- | ---: | --- | --- |
| ODsay search(파일) | OD 좌표 5자리 반올림 | 1 | 30분 | 금지(공급자 오류·malformed는 예외 전파, 미저장 — live 시도로 실증) |
| ODsay lane(파일) | 정규화 mapObject + bounds 5자리 | 1 | 30분 | 금지(성공 검증 후에만 저장하도록 순서 변경: 검증→저장) |
| route feature(파일) | OD + geometry profile | **3** | 30분 | 이전 schema는 miss 처리(폐기 후 재생성 정책, migration 없음) |
| elevation(파일) | 표본 좌표 | 3 | 30일 | estimated_90m 성공만 저장 |
| shade(파일) | route_id + 30분 departure bucket | 4 | 24h | estimated_public 성공만 저장 |
| route-set(in-memory) | 랜덤 토큰 | **2** | 30분 | 프로세스 재시작 시 소멸 |

- search cache 키는 후보 수와 분리되어 있다(응답 자체가 전체 후보를 담으므로 절단 정책은 읽기 시점 적용).
- route feature cache는 "보행 exact + 90m 경사 완성"이면 저장하며, 대중교통 표시 선형이
  estimated라는 이유만으로 저장을 막지 않는다(§17.3, 테스트 존재).

## single-flight · semaphore

- 대상: 동일 OD search, 동일 mapObj+bounds loadLane (이번 구현), 동일 TMAP·VWorld·shade는
  기존 구현의 request lock·30분 버킷 캐시 유지.
- 구현: 이벤트 루프별 `dict[key, asyncio.Task]` + `asyncio.shield`. leader는 독립 Task로 실행되어
  follower 취소가 leader를 취소하지 않고, 완료 콜백에서 in-flight를 제거하며 오류는 전 대기자에 전파.
- 전역 semaphore `ODSAY_MAX_CONCURRENT_REQUESTS`(기본 3, 1~10)가 search·loadLane HTTP를 모두 제한.
  대기시간은 counter의 `semaphore_wait_seconds`로 계측.
- 실측: 동시 10 search → net 1(follower 9), 동시 10 loadLane → net 1, cap=2에서 max 동시 HTTP 2,
  leader 실패 전파+재시도 가능(전부 ai/tests/test_odsay_lazy_refinement.py).

## route-set 동시 갱신 보호

구현(복합): 토큰별 asyncio lock + revision CAS + 원자적 `update_candidate`.

| 위험 시나리오 | 보호 | 검증 |
| --- | --- | --- |
| refinement ↔ shade refresh 상호 덮어쓰기 | 두 endpoint 모두 token lock으로 직렬화, refinement는 update_candidate로 해당 후보만 수정 | test_transit_refinement.py(동시 refinement) + refresh 409 계약 |
| stale revision 저장 | `replace(expected_revision=...)` 불일치 시 `StaleRouteSetRevision` → 409 | test_route_set_stale_revision_replace_is_rejected |
| 2위·3위 동시 refinement | lock 직렬화 + 후보별 patch | test_concurrent_refinements_of_two_candidates_are_both_preserved |
| 후보 순서 변경 | update_candidate는 순서·다른 후보 불변 | test_refine_transit_patches_only_selected_candidate |
| 만료 직전 refinement | update_candidate가 None 반환 시 409 | endpoint 분기 + 토큰 만료 테스트 |
| deep copy 정합성 | get/put/update 모두 deep copy 유지 | 기존 계약 유지 |
| TTL 갱신 정책 | put/replace는 시각 갱신, update_candidate는 **기존 생성시각 유지**(정밀화가 만료를 연장하지 않음) | 코드 명시 |

## frontend stale response 정책

- 카드 선택 즉시 selectedRouteId 반영, 후보별 in-flight Set으로 중복 요청 차단.
- 응답은 route ID가 일치하는 후보의 저장 geometry만 patch — 늦은 응답이 현재 선택(지도 표시)을
  바꾸지 않으며, 시작된 호출 결과는 캐시로 활용된다(§19). zustand store는 컴포넌트 밖에 있어
  unmount 후 setState 문제가 없다.
- 실측: appStore.enrichment.test.ts 4개 시나리오(선택→patch, exact 재선택 0호출, 늦은 응답
  선택 유지, 중복 선택 단일 호출).

## 프로세스 cache 한계 (§29)

- production compose 기준 backend·ai 각 **단일 Uvicorn 프로세스**(worker 옵션 없음). sticky routing
  불필요(단일 인스턴스). 이는 단일 프로세스라는 사실이지 다중 worker 안전성 주장이 아니다.
- route-set·refinement 서술자는 in-memory이므로: 재시작 시 소실 → 이후 refinement/refresh는 409
  "다시 검색" (자동 재검색·몰래 search 없음, 테스트 존재), rolling deploy 중 동일, 수평 확장 시
  다른 worker에서 token miss → 409. Redis 등 외부 저장소 도입은 이번 범위에서 제외(후속 과제).
- refinement identity(서술자)는 route-set 내부에 저장되어 TTL이 route-set과 동일하며 별도로
  연장되지 않는다. 원본 mapObj는 `Field(exclude=True)`로 어떤 API 응답에도 직렬화되지 않는다.

생성시각: 2026-07-26T15:36Z (UTC)
