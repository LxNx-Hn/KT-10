# ODsay single-flight / cache handoff race 수정

- 작업일: 2026-08-14
- 기준: 최신 `main` (`540f538`)
- 증상: AI CI에서 간헐적으로 ODsay search network 호출이 1회 기대인데 2회 발생
- 변경 파일: `ai/collectors/odsay_collector.py`, `ai/tests/test_odsay_lazy_refinement.py`

---

## 0. 무엇이 문제였나

### 겉으로 드러난 증상

AI CI가 **간헐적으로** 실패했다. 같은 커밋을 다시 돌리면 통과하기도 했다.

```
expected ODsay searchPubTransPathT network call == 1
actual   2
```

동일 OD에 대한 동시 요청은 single-flight로 묶여 **공급자 호출 1회**여야
하는데, 가끔 2회가 나갔다.

### 코드의 어느 부분이 문제였나

수정 전 `_collect_live_or_cached()`의 순서다. `_load_lane()`도 동일했다.

```python
data, follower = await single_flight(          # ① leader 실행, 끝나면 flight 제거
    f"search:{identity_hash}",
    _fetch_search,                             #    안에서 하는 일: cache 재확인 → network
)
outcome = "network" if network else "single-flight"

if not isinstance(data, dict):                 # ② 응답 검증
    raise CollectorError(...)
...
if network:
    await _store_payload("search", ...)        # ③ 캐시 저장 — leader 밖이다
```

leader factory `_fetch_search`가 하는 일은 **network 호출까지**였고, `②` 검증과
`③` 캐시 저장은 `single_flight()`가 반환된 **뒤**에 있었다.

그런데 `single_flight()`는 leader task가 끝나는 즉시 in-flight 항목을 지운다.

```python
entry.task.add_done_callback(
    lambda finished, flight_key=key, flight=entry: (
        flights.pop(flight_key, None) ...      # task 완료 = 즉시 제거
    )
)
```

즉 **`①`이 끝나는 순간 key는 사라지는데, 캐시는 `③`에서야 채워진다.**
`①`과 `③` 사이가 무주공산이다.

### 왜 두 번 호출되는가

그 사이에 같은 key 요청이 들어오면 이렇게 흐른다.

```
요청 A                                  요청 B
──────────────────────────────────────────────────────────
network 완료
leader task 종료
flight 제거              ←─────────── 이 시점 이후 B 진입
                                       _cached_payload() → None   (아직 저장 전)
                                       _flights() 조회   → 없음   (방금 지워짐)
                                       ⇒ 자기가 새 leader
검증                                    network 호출 ★ 2회째
_store_payload()  ← 여기서야 캐시 생김
```

B가 보는 상태가 지시서에서 금지한 세 번째 상태다.

```
flight 없음 + cache 없음
```

B는 follower가 될 수도 없고(합류할 flight가 없다) 캐시를 읽을 수도 없어서
(아직 안 써졌다), **남은 선택지가 새 leader가 되는 것뿐**이다. 그래서 성공
경로인데도 network 호출이 한 번 더 나간다.

창이 좁아서 어쩌다 걸리는 것도 아니다. `_store_payload()`는
`asyncio.to_thread`로 파일을 쓰므로([odsay_collector.py:245](../../../ai/collectors/odsay_collector.py))
스레드 홉만큼 실제 시간이 걸린다. `②` 검증까지 더하면 이벤트 루프가 다른
코루틴을 실행할 기회가 여러 번 생긴다.

### 무엇이 문제가 아니었나

- **single-flight 구현 자체는 정상이다.** `single_flight()`는 leader/follower
  합류, 취소 전파, 오류 전달을 모두 올바르게 처리한다.
- **캐시 구현도 정상이다.** 원자적 교체로 부분 기록을 노출하지 않는다.
- 문제는 **둘을 이어 붙인 순서**였다. 각각은 맞는데 경계에서 틈이 생겼다.

그래서 고칠 지점도 두 컴포넌트 내부가 아니라 **소유권 경계**였다. leader가
언제까지 key를 붙들고 있어야 하는가의 문제다.

---

## 1. Root cause

한 줄로 요약하면, `_collect_live_or_cached()`와 `_load_lane()` 둘 다
**persistent cache 쓰기가 single-flight leader 밖에** 있었다. leader task가
끝나는 즉시 in-flight 항목이 제거되는데 캐시는 그 뒤에 채워지므로, 그 사이에
`flight 없음 + cache 없음` 창이 열린다. 구체적인 코드와 호출 흐름은 0장에
정리했다.

관련 위치는 다음과 같다.

| 위치 | 내용 |
| --- | --- |
| [odsay_instrumentation.py:372](../../../ai/collectors/odsay_instrumentation.py) | `add_done_callback`이 task 완료 즉시 flight 제거 |
| `odsay_collector.py` `_collect_live_or_cached()` | `single_flight()` 반환 후 `_store_payload("search", ...)` |
| `odsay_collector.py` `_load_lane()` | `single_flight()` 반환 후 `_store_payload("lane", ...)` |

### 기존 테스트가 잡지 못한 이유

`ai/tests/test_odsay_lazy_refinement.py`의 autouse fixture가
`ODSAY_CACHE_DIR=""`로 캐시를 꺼 두었다. 캐시가 없으면 "network 완료 ~ cache
commit" 구간 자체가 존재하지 않으므로, 동시 요청 테스트가 있어도 이 race를
검증할 수 없었다.

### PR #44 / #45와는 무관하다

| PR | 실제 변경 범위 |
| --- | --- |
| #44 (`789d6fd`) | frontend 6개 파일 — `MapView.tsx`, `map-first.css`, `MapControls.tsx` 등 |
| #45 (`44a2ccb`) | backend auth/identity — `identities.py`, `auth.py`, 마이그레이션 `0009` |

둘 다 ODsay collector·single-flight를 건드리지 않았다. 해당 코드를 마지막으로
수정한 커밋은 `76de909 feat(routes): optimize ODsay calls and shade gating`이다.
**기존 race가 merge 후 CI timing에서 노출된 것**이며, #44/#45의 기능 변경이
원인이 아니다.

## 2. Search 수정

leader factory `_fetch_search` 안에서 **검증과 cache commit까지 끝내고**
반환하도록 소유 범위를 넓혔다.

```
double-check cache
→ network request
→ _validated_search_paths()      # cacheable 여부 확인
→ _store_payload()               # persistent cache commit
→ return                         # 여기서 비로소 task 완료 → flight 제거
```

바깥의 `if network: await _store_payload(...)`는 제거했다. 바깥 검증은 cache
hit·follower 경로에도 필요하므로 `_validated_search_paths()` 호출로 유지했다.

이제 두 번째 요청은 반드시 둘 중 하나다.

1. leader 실행 중 → follower
2. leader 완료 → 이미 커밋된 cache를 읽음

`_write_cache()`가 임시 파일 작성 후 `Path.replace()`로 원자적 교체를 하므로,
동시 reader가 부분 기록을 보는 경우도 없다.

## 3. loadLane 수정

동일한 invariant로 맞췄다. `_fetch` 안에서 `_validated_lane_paths()` 통과 후
`_store_payload()`까지 완료하고 반환한다. search만 고치고 loadLane을 남겨두지
않았다.

### 추출한 helper 2개

검증 로직을 두 곳에서 쓰게 되어 classmethod 두 개로만 뽑았다. 그 이상의
abstraction은 만들지 않았다.

| helper | 캐시 거부 조건 |
| --- | --- |
| `_validated_search_paths(data)` | JSON 객체 아님 / ODsay error / `result` 비객체 / `result.path` 타입 오류 |
| `_validated_lane_paths(data, map_object)` | JSON 객체 아님 / provider error / 유효 lane geometry 없음(`empty_geometry`) |

기존 오류 메시지와 `CollectorError` code를 그대로 옮겼다. **검증을 건너뛰고
raw payload를 저장하는 경로는 없다.**

### 보존한 semantics

- follower 취소 시 남은 대기자를 위해 leader 계속 실행
- 마지막 대기자까지 취소되면 실행 취소
- leader 오류가 followers에게 동일 전달 (검증 실패도 leader에서 발생 → 동일)
- 실패한 flight 제거 → 이후 정상 retry
- provider error 미캐시
- ODsay concurrency semaphore
- `record_network_call`, `network_attempted/completed/failed`, daily counter

`single_flight()` 자체와 계측 코드는 한 줄도 바꾸지 않았다.

## 4. Shade / VWorld 검증 — 문제 없음, 코드 미수정

### VWorld buildings

`_download_missing_query_box()`가 query-box lock 안에서 cache 재확인 후
`_download_query_box()`를 호출하고, `_write_cached_features()`는 그 함수
**내부 반환 직전**([vworld_buildings.py:371](../../../backend/app/providers/vworld_buildings.py))에
있다.

```
lock 획득 → cache 재확인 → network → _write_cached_features() → lock 반환
```

cache 쓰기가 lock 해제보다 먼저라 handoff 창이 없다.

### shade result cache

`get_or_compute()`도 동일하다
([shade_cache.py:150-160](../../../backend/app/shade_cache.py)).

```
read miss → per-key compute lock → cache re-check → compute() → write() → lock release
```

### 근거 테스트

지시서가 지목한 두 테스트가 이미 존재하고 통과한다.

- `test_vworld_provider_singleflights_shared_query_boxes`
- `test_shade_cache_singleflights_same_route_and_time`

**따라서 그늘/VWorld 쪽은 코드도 테스트도 추가하지 않았다.**

## 5. Regression tests

[test_odsay_lazy_refinement.py](../../../ai/tests/test_odsay_lazy_refinement.py)에
3건 추가. `_BlockingStore`가 `asyncio.Event`로 `_store_payload` 진입 시점을
붙잡아 race window를 **강제로** 연다. sleep 타이밍에 기대지 않는다.

| 테스트 | 검증 |
| --- | --- |
| `test_search_cache_commit_keeps_single_flight_ownership` | cache commit 전 도착한 동일 OD 요청이 network를 재호출하지 않음 → `search_calls == 1` |
| `test_load_lane_cache_commit_keeps_single_flight_ownership` | 동일 mapObj 동시 요청 → `lane_calls == 1` |
| `test_sequential_request_after_leader_reuses_cache` | leader 완료 후 재호출은 cache hit, network 증가 없음 |

앞의 두 테스트는 `tmp_path`를 `ODSAY_CACHE_DIR`로 써서 기존 fixture의
캐시 비활성 문제를 우회한다.

**수정 전 실패를 먼저 확인했다.**

```
FAILED test_search_cache_commit_keeps_single_flight_ownership   assert 2 == 1
FAILED test_load_lane_cache_commit_keeps_single_flight_ownership assert 2 == 1
2 failed, 1 passed
```

수정 후 10 passed.

## 6. External-call contract

| 흐름 | searchPubTransPathT | loadLane |
| --- | --- | --- |
| 동일 OD 동시 최초 검색 | 1 | 0 |
| 같은 OD cache 재요청 | 0 | 0 |
| 동일 후보 동시 refine | 0 | 1 |
| 이미 refine된 후보 재선택 | 0 | 0 |
| rescore | 0 | 0 |
| shade refresh | 0 | 0 |

`test_pr18_call_matrix.py` 33건 통과로 유지를 확인했다. initial recommendation
에서 loadLane을 eager 호출하거나 search를 여러 번 호출하는 우회는 하지 않았다.

### 계측

동일 OD 동시 요청 2건이 합쳐졌을 때 의미는 그대로다.

```
logical calls = 2
actual network search = 1
single-flight follower = 1
```

counter를 조작해 호출 수를 감추지 않았다. **실제 mock transport
(`_CountingClient`)의 호출 수가 1**임을 단언한다.

## 7. Test result

| 명령 | 결과 |
| --- | --- |
| `pytest ai/tests/test_odsay_lazy_refinement.py -q` | **10 passed** |
| `pytest ai/tests/test_pr18_call_matrix.py ai/tests/test_pr18_regressions.py -q` | 33 passed |
| `pytest backend/tests/test_vworld_buildings.py backend/tests/test_shade_cache.py -q` | 21 passed |
| `pytest backend/tests -k singleflight -v` | 3 passed |
| `pytest ai/tests -q` | **295 passed**, 2 skipped |
| `pytest backend/tests -q` | **499 passed**, 1 skipped |
| ODsay lazy refinement 20회 반복 | **실패 0회** |
| `ruff check ai` / `ruff check backend scripts` (E4,E7,E9,F) | 통과 |
| `bandit -ll -r ai -x ai/tests` | 통과 |
| `compileall ai backend` | 통과 |

반복 실행 통과는 보조 근거일 뿐이며, 위 deterministic race test가 실제 계약을
보장한다.

## 8. 범위 밖으로 남긴 것

지시서의 금지 항목을 지켰다. 인증/DB 구조, frontend shade legend, route
scoring, ODsay quota 정책, API key/logging 정책은 건드리지 않았다. error를
캐시해 호출 수만 줄이거나 sleep으로 테스트를 안정화하지도 않았다.

### 작업 중 만난 로컬 환경 문제

`backend/tests/test_apple_oauth.py`가 `ModuleNotFoundError: No module named
'jwt'`로 수집 실패했다. PR #48이 추가한 의존성이 로컬 venv에만 없던 것이라
`backend/requirements.txt`의 고정 버전(`PyJWT[crypto]==2.13.0`)을 설치해
해결했다. **저장소 코드 변경은 아니다.**
