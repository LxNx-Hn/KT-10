# 최신 main 선택 병합 검증 보고

## 결과

최신 `origin/main` `d9f8392`를 fast-forward한 로컬 `main`에 PR #18의
Backend·AI·환경·계측·문서 패치를 선택 적용했다. 사용자의 최신 Frontend 보존
지시에 따라 `frontend/`는 `origin/main`과 Git diff 0이며, PR의 Frontend source
변경은 적용하지 않았다. 검증 완료 후 이 변경 전체를 `main`에 커밋하고
`origin/main`에 직접 게시했다. 비-main tip은 archive tag로 보존한 뒤 원격 branch를
삭제했다.

## 핵심 판정

| 항목 | 판정 | 근거 |
| --- | --- | --- |
| 최신 main 기준 | PASS | HEAD `d9f8392` |
| Frontend 불변 | PASS | `git diff --exit-code HEAD -- frontend` |
| shade KST 10:00~18:00 gate | PASS | Backend 전체·shade 회귀 테스트 |
| weather 유효성·미래 오용 차단 | PASS | 관측 TTL·timezone·departure 검증 |
| topN 3·5·7·10 | PASS | mock call matrix |
| 최초 ODsay 총 2회 계약 | PASS | search 1 + 최종 1위 loadLane 1 |
| 재선택 추가 loadLane 0 | PASS | cache test |
| route-set rescore provider 0회 | PASS | Backend 회귀 테스트 |
| route ID·score·snapshot 불변 | PASS | refinement 회귀 테스트 |
| AI 전체 | PASS | 231 passed, 2 skipped |
| Backend 전체 | PASS | 274 passed, 1 skipped |
| Frontend 전체·build | PASS | 108 passed, typecheck/build |
| 접근성 E2E | PASS | 5 passed, 1 desktop-only skipped |
| Docker Compose config | PASS | 임시 32자 이상 내부 토큰 사용 |
| Docker build·runtime | NOT MEASURED | Docker Desktop engine 미기동 |
| live provider·latency | NOT MEASURED | staging provider 실행 안 함 |

## 운영 전 필수

실제 secret 파일은 수정하지 않았다. production 기동 전
`AI_INTERNAL_SERVICE_TOKEN`을 Backend와 AI에 동일한 32자 이상 값으로 주입해야
한다. 현재 로컬 `.env.production`에는 이 신규 값이 없어, 값 없이 Compose config를
실행하면 명시적으로 실패한다.

Frontend 선택 refinement와 shade toggle 제거는 이번 선택 병합에서 의도적으로
적용하지 않았다. 이는 사용자의 “현재 main Frontend를 건드리지 말라”는 지시를
우선한 결과이며, Backend/AI API는 준비됐지만 기존 UI 동작은 그대로다.

## 브랜치 정리

로컬과 원격 branch는 모두 `main`만 남겼다. 삭제 전 비-main tip과 PR #18
재검토 working tree는 `archive/...-20260729` tag로 원격에 보존했다.
PR #18은 source branch 삭제에 따라 `CLOSED_UNMERGED` 상태다.
