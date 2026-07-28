# ODsay 호출 추적

- 실행 SHA: `d9f8392f7f39ea8518098ea6c49488ff254e3899` + 미커밋 diff
- 명령: `python -m pytest ai/tests/test_pr18_call_matrix.py ai/tests/test_odsay_lazy_refinement.py -q`
- 결과: 16 passed
- transport: mock HTTP
- 실제 provider network: 0회

| 시나리오 | search | loadLane | 판정 |
| --- | ---: | ---: | --- |
| 최초 topN 3 | 1 | 최종 1위 1 | PASS |
| 최초 topN 5 | 1 | 최종 1위 1 | PASS |
| 최초 topN 7 | 1 | 최종 1위 1 | PASS |
| 최초 topN 10 | 1 | 최종 1위 1 | PASS |
| 새 후보 최초 refinement | 0 | 1 | PASS |
| 같은 후보 재선택 | 0 | 추가 0 | PASS |
| 동일 OD 동시 10건 | 1 | 0 | PASS |
| 동일 mapObj 동시 10건 | 0 | 1 | PASS |

계측 로그에는 correlation ID, endpoint, call site, 비식별 route ID hash,
후보 index, mapObj+bounds hash, cache, single-flight, semaphore wait,
network started, HTTP status, duration과 outcome을 기록한다. API key, 원본 좌표,
원본 mapObj, route-set token과 내부 token은 기록하지 않는다.

실제 ODsay 호출과 quota·latency는 이번 실행에서 `NOT MEASURED`다.
