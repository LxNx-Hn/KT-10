# 정직성·하드코딩 감사

| 항목 | 근거 | 판정 |
| --- | --- | --- |
| 후보 기본값 | Backend `ROUTE_DEFAULT_TOP_N=5`, 요청 1~10 검증 | PASS |
| 상한 초과 | clamp 없이 422 | PASS |
| 후보 부족 | 합성 후보 보충 없음 | PASS |
| estimated transit | exact로 승격하지 않고 refinement 전 estimated 유지 | PASS |
| 누락 shade | 0%가 아니라 `None` 및 public 응답 생략 | PASS |
| 높이 coverage | 99%에서 shade 생략 테스트 | PASS |
| weather 유효성 | 관측시각·timezone·TTL·출발시각 차이 gate | PASS |
| 그늘 시간 | KST 10:00 이상, 18:00 미만만 계산 | PASS |
| 운영 demo 혼입 | live 공급자 실패를 demo 경로로 바꾸지 않음 | PASS |
| Frontend source | 사용자 지시에 따라 `origin/main` 그대로 유지 | PASS |
| 기존 shade toggle | `origin/main`에 존재하며 이번 선택 병합에서 의도적으로 미수정 | 보고 |

`demo`, `mock`, fixture는 기존 명시적 demo 경로와 테스트 안에 남아 있다. live
공급자 오류를 정상 경로, 빈 정상 배열, 임의 0 또는 가짜 직선으로 바꾸는 신규
fallback은 추가하지 않았다.
