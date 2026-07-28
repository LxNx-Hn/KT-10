# 선택 병합 성능·검증 결과

- 기준: `origin/main` / `d9f8392f7f39ea8518098ea6c49488ff254e3899`
- 상태: `main`의 미커밋 working tree
- 생성시각: 2026-07-29 06:04 KST
- Frontend: `origin/main`과 Git diff 0
- worker: Backend 1, AI 1
- route-set TTL: 1,800초

## 실제 실행 결과

| 검증 | 결과 |
| --- | --- |
| AI 전체 | PASS — 231 passed, 2 skipped |
| Backend 전체 | PASS — 274 passed, 1 skipped |
| Frontend 전체 | PASS — 108 passed |
| 접근성 E2E | PASS — 5 passed, 1 skipped |
| TypeScript / Vite production build | PASS |
| compileall / CI Ruff / Bandit | PASS |
| pip check / pip-audit / npm audit | PASS |
| production Compose config | PASS — 임시 검증용 내부 토큰 주입 |
| Docker image build·runtime | NOT MEASURED — 로컬 Docker 엔진 미기동 |

## 성능 판정

이번 통합에서는 실제 공급자 staging 호출을 수행하지 않았다. 따라서 cold/warm
p50·p95와 refinement latency는 `NOT MEASURED`다. mock transport는 호출 계약을
검증하는 수단이며 latency 실측으로 사용하지 않았다.

후보 3·5·7·10의 mock 호출 계약은 모두 최초 `search=1`,
최종 1위 `loadLane=1`, 총 ODsay 2회로 통과했다.
