# 경로 지연 정밀화 성능·검증 보고서 (2026-07-27)

- 기준 SHA: `5e201c0c1567bc93b89a4f98b605f21814edc08c` (`origin/main`, 작업 변경분은 미커밋)
- 비교 SHA: v1.0.0 `f56f414c`, v1.0.1 `eb77e3fd` (태그 아님 — 커밋 메시지 기준, git log로 재검증)
- 실행 환경: macOS 26.2 (Darwin 25.2.0), Python 3.12.2 scratchpad venv, Node/Vite 로컬
  - repo 고정 `xgboost-cpu==2.1.1`은 macOS 배포판이 없어 테스트 환경만 `xgboost==2.1.1`로 대체 (repo 파일 변경 없음)
- Uvicorn worker 수: backend 1, ai 1 (docker-compose.prod.yml 단일 프로세스)
- route-set TTL: 30분(in-memory), ODsay cache TTL: 30분(파일)

## 테스트 결과 (실측)

| 스위트 | 명령 | 결과 |
| --- | --- | --- |
| AI | `pytest ai/tests -q` (repo 루트) | 197 passed, 2 skipped |
| Backend | `pytest tests -q` (backend/) | 231 passed, 1 skipped |
| Frontend | `npx vitest run` | 115 passed |
| TypeScript | `npm run typecheck` | pass |
| Production PWA build | `npm run build` | pass |
| compileall | `python -m compileall ai backend/app scripts` | pass |
| ruff (변경 파일) | `ruff check <changed files>` | 신규 지적 0건 (저장소 기존 지적 224건은 보고만) |
| bandit (신규 파일) | `bandit -r <new files>` | 0건 |
| pip check / pip-audit | venv 기준 | broken 0 / 알려진 취약점 0 |
| npm audit | prod+dev | 0 vulnerabilities |

## ODsay 호출 매트릭스 (mock transport 실측)

정상 cold cache miss 기준, 후보 수와 무관:

| 요청 후보 수 | search | 최초 loadLane(1위) | 총 ODsay |
| ---: | ---: | ---: | ---: |
| 3 | 1 | 1 | 2 |
| 5 | 1 | 1 | 2 |
| 7 | 1 | 1 | 2 |
| 10 | 1 | 1 | 2 |

- 변경 전(코드 분석): search 1회 + 후보별 inline loadLane. 후보 5개 요청은 3개 고정 배치의
  overfetch로 **최대 7회**(2번째 배치가 4·5·6번 후보 loadLane을 모두 시작 후 5개 절단).
- 후보 선택: 신규 후보 1건당 loadLane 1회, 재선택 0회, 선택으로 인한 search/전체 recommend 0회
  (backend/tests/test_transit_refinement.py 실측).
- single-flight: 동일 OD 동시 10요청 → search network 1회, 동일 후보 동시 10요청 → loadLane 1회.
- 전역 semaphore(기본 3, 테스트에서 2로 설정) 상한 준수 실측.

## Live ODsay 시도 (예산 50회 중 2회 사용)

- 로컬 `ai/.env`·`backend/.env`의 두 ODsay 키 모두 `[ApiKeyAuthFailed]` 반환(IP 허용 목록 제한 추정).
- 오류는 명시적으로 전파되었고(가짜 성공 없음), 오류 응답은 캐시되지 않았으며,
  일일 counter에 search 2회가 기록되어 예산 계측이 동작함을 확인.
- 따라서 live 응답시간·후보 수별 비용은 **NOT MEASURED**.

## 응답시간

| 항목 | 값 | 판정 |
| --- | --- | --- |
| 과거 기준선(후보5) cold p50/p95 | 2.232s / 5.418s | 참고(과거 측정, docs/performance/route-candidate-benchmark-2026-07-26.json) |
| 과거 기준선(후보5) warm p50/p95 | 0.404s / 0.783s | 참고 |
| 변경 후 cold/warm p50·p95 | — | **NOT MEASURED** (유효 ODsay·TMAP·VWorld·OpenWeather 키와 운영 스택 필요) |
| refinement p50/p95 | — | **NOT MEASURED** |
| cache 재선택 ≤200ms | — | **NOT MEASURED** (설계상 서버 캐시 반환이며 외부 호출 0회는 테스트로 검증) |

배포 후 `scripts/benchmark_route_candidate_counts.py --candidate-counts 3,5,7,10`으로 측정해야 하며,
ODsay 2회/요청 감소를 전체 응답시간 감소 비율로 환산하지 않는다. Backend↔AI refinement 왕복이
1회 추가되므로 초기 응답에는 loadLane 1회 + 내부 HTTP 1회의 순 지연이 남는다.

## cache schema version

| cache | version | 비고 |
| --- | ---: | --- |
| ODsay search/lane 파일 | 1 | payload 형식 불변 |
| route feature 파일 | 2→**3** | 지연 정밀화 서술자·semantic route ID 도입, 이전 schema는 miss 처리 후 재생성 |
| elevation 파일 | 3 | 불변 |
| shade 파일 | 4 | 불변 |
| route-set(in-memory) | **2** | 후보 수 metadata·revision·정밀화 상태 추가. in-memory라 migration 불필요(재시작 시 소멸) |

## NOT MEASURED 목록

- live cold/warm p50·p95, refinement latency, cache 재선택 시간
- 후보 3·5·7·10 비용 매트릭스(TMAP·terrain·shade·VWorld·payload·memory)
- VWorld corridor 호출·pagination·건물 수 매트릭스
- Docker production image build, compose 기동, healthcheck·readiness·smoke (로컬 Docker 데몬 미기동 + 필수 키 부재)

생성시각: 2026-07-26T15:36Z (UTC) / 2026-07-27 00:36 KST
