# PR #18 병합 게이트 판정

- PR: #18 `Implement lazy transit refinement`
- branch: `feature/lazy-transit-refinement`
- 작업 전 HEAD: `5d60a3b75853074dc5f5cb3cd662feaa745cee39`
- `origin/main`: `d9f8392f7f39ea8518098ea6c49488ff254e3899` (ahead 1 / behind 3)
- 실행 환경: macOS darwin 25.2.0, Python 3.12.2, Node 22 / vitest
- worker 수: Backend 1 · AI 1 (단일 uvicorn process)
- 실제 외부 network 호출: **0회** (전부 mock transport)
- 생성시각: 2026-07-28 18:12 KST

판정은 `PASS` · `FAIL` · `NOT MEASURED` 중 하나만 사용한다.

## 차단 항목

| 항목 | 판정 | 근거 |
| --- | --- | --- |
| 후보 5개에서 6번째 `_build_candidate` 불필요 실행 없음 | PASS | 수정 전 6회 → 후 5회. 3·5·7·10 전부 요청 수와 일치 |
| profile 변경 `/recommend` 호출 0 | PASS | store가 `adapters.routes.rescore` 사용 |
| option 변경 `/recommend` 호출 0 | PASS | 동일 경로 |
| rescore ODsay 0 | PASS | `get_route_candidates`·`get_ai_pipeline_candidates` 호출 시 즉시 실패하도록 감시 |
| rescore TMAP 0 | PASS | 후보 재수집 자체가 없음 |
| stale 이전 검색 refinement patch 0 | PASS | generation + route-set token + route ID 4중 검증 |
| focus만으로 loadLane 0 | PASS | `onFocus={onSelect}` 제거, Enter·Space만 선택 |
| 빠른 carousel 이동에서 최종 후보만 refinement | PASS | 200ms debounce, 2→3→4에서 1회 |
| failed 후보 즉시 반복 호출 없음 | PASS | 오류 분류별 cooldown(429/409), 6개 분류 검증 |
| invalid token lock 누수 없음 | PASS | 임의 token 200건 → lock map 증가 0 |
| AI private endpoint 인증 적용 | PASS | 토큰 없음·오답 403, 정답 통과, health/ready 공개 유지 |
| actual network counter 정확 | PASS | attempted/completed/failed를 transport 직전·직후 기록 |
| route-set replace 실패 시 새 token 생성 0 | PASS | `_replace_cached_route_set` 409, entry 증가 0 |
| 미계산 shade public 필드 없음 | PASS | 응답 조립 단계에서 `None` 정규화 |
| route ID 충돌 테스트 통과 | PASS | lane ID·승하차·wayCode를 fingerprint에 포함 |

**차단 항목 FAIL 0건.**

## 기존 기능 회귀

| 항목 | 판정 | 근거 |
| --- | --- | --- |
| 최초 후보 3·5·7·10 ODsay 총 2회 | PASS | search 1 + 1위 loadLane 1 |
| 동일 후보 single-flight | PASS | 동시 10요청 → 1회 |
| ODsay semaphore | PASS | 상한 2에서 peak 2 |
| route ID refinement 전후 동일 | PASS | 정밀 path를 fingerprint에서 제외 |
| refinement 후 score·rank 불변 | PASS | 응답이 geometry 필드만 반환 |
| refinement 후 snapshot·feedback token 불변 | PASS | patch 대상에 미포함 |
| profile rescore 후 새 score·rank 정상 반영 | PASS | rescore는 재순위화 계약 |
| exact 보행만 terrain 분석 | PASS | 기존 `_analysis_route_parts` 유지, 변경 없음 |
| 부산 QGIS 90m DEM 유지 | PASS | 관련 코드 미변경 |
| 경사 기준 2·5·8% 유지 | PASS | `SLOPE_COLOR_RAMP` 미변경 |
| 경사선 z-index 유지 | PASS | KakaoMap z-index 미변경 |
| 버스·지하철 경사색 없음 | PASS | 기존 walk 전용 분기 유지 |
| 그늘 토글 없음 | PASS | 기존 제거 상태 유지 |
| 카드·지도 기존 레이아웃 유지 | PASS | `aria-busy` 속성만 추가 |

## 테스트 결과

| 스위트 | 결과 |
| --- | --- |
| AI pytest (`ai/tests`, 호출 matrix 9건 포함) | **224 passed, 2 skipped** |
| Backend pytest (`backend/tests`) | **256 passed, 1 skipped** |
| Frontend vitest | **123 passed** (18 files) |
| TypeScript (`tsc --noEmit`) | PASS |
| Vite production + PWA build | PASS (sw.js, workbox 생성) |
| Python `compileall` | PASS |
| Ruff (CI 규칙 `E4,E7,E9,F`) | PASS (ai / backend+scripts 모두) |
| Bandit | High 0 · Medium 0 (LOW만, 아래 참고) |
| `pip check` | PASS |
| `pip-audit` | 취약점 0건 |
| `npm audit` | 취약점 0건 |
| Docker backend image build | PASS (524MB) |
| Docker AI image build | PASS (1.26GB) |
| Docker frontend image build | PASS (81.4MB) |
| Docker prod/dev compose config | PASS |
| AI port 외부 노출 | PASS — prod 미publish, dev `127.0.0.1:8001`만 |

### Bandit LOW 지적

| 위치 | 내용 | 판단 |
| --- | --- | --- |
| `ai/api/router.py:52`, `backend/app/providers/ai_pipeline.py:155` | B105 "hardcoded password: 'X-KT10-Internal-Token'" | 오탐. HTTP **헤더 이름** 상수이며 비밀값이 아님 |
| `backend/app/shade.py:533-536` | B101 assert 사용 | 이번 변경과 무관한 기존 코드 |

## NOT MEASURED

| 항목 | 사유 | 미검증 영향 |
| --- | --- | --- |
| 실제 ODsay live 호출 수·latency | 유효 ODsay 키·staging 환경 없음 | 실제 quota 소모량과 응답시간은 배포 후 관측 필요 |
| cold/warm p50·p95 | 위와 동일. mock 결과를 live 수치로 쓰지 않음 | 성능 회귀 여부 미확인 |
| refinement p50·p95 | 위와 동일 | 사용자 체감 지연 미확인 |
| VWorld 실제 HTTP 호출·pagination | 유효 VWorld 키 없음 | corridor 호출량 미확인 |
| production compose 기동·healthcheck·API smoke | 전체 비밀값(Postgres·Kakao·OpenWeather 등) 미보유 | 런타임 통합 미확인 |

## 남은 운영 위험

1. **route-set in-memory 한계** — Backend·AI 모두 단일 uvicorn process다. 재시작·
   rolling deploy 시 route-set이 사라지고 refinement·rescore가 409를 반환한다.
   수평 확장 시 sticky routing이 없으면 다른 worker에서 token miss가 발생한다.
   (이번 작업 범위에서 Redis 도입 금지 — 후속 과제)
2. **client cooldown과 server cooldown 이중화** — 실패 시 프론트가 60초 자체
   cooldown을 걸고 서버도 429를 반환한다. 서버 `Retry-After`가 더 길면 프론트가
   먼저 재시도해 429를 받는다. 사용자에게는 조용히 무시되지만 불필요한 왕복이다.
3. **AI 내부 토큰이 개발 환경에서 선택적** — `APP_ENV != production`이고 토큰이
   비어 있으면 인증을 요구하지 않는다. dev compose는 `127.0.0.1` 바인드로 막았으나
   토큰을 반드시 설정하는 편이 안전하다.
4. **`personalize_and_sign` 그늘 기준시각** — 그늘이 하나도 계산되지 않으면 출발
   시각을 기준시각으로 쓴다. 이는 그늘 **계산시각이 아니며** 그늘 비율을 만들지
   않는다. 학습 스냅샷 해석 시 이 구분이 필요하다.
