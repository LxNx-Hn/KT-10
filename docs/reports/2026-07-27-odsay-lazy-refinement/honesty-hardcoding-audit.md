# 정직성·하드코딩 감사 (2026-07-27)

기준 SHA `5e201c0c` (작업 전 최신 main). "수정 필요"로 판정된 항목은 이번 작업에서 수정 완료했고,
그 외는 보고만 한다. 검색: demo/mock/synthetic/fixture/fallback/sample/default, 하드코딩 수치,
반복 외부 호출, showShade/showSlope, 임의 0 대체 등.

| 항목 | 파일·줄(작업 전) | 현재 동작 | 운영 영향 | live/test | 수정 필요 | 정확성 영향 | 근거·조치 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 후보 수 5 하드코딩(frontend) | frontend/src/adapters/live.ts:95,104 `topN = 5` | 항상 topN 5 전송 → 서버 기본값 무효화 | 운영 기본값 변경 불가 | live | 수정 | 중간 | 제거, 미지정 시 서버 기본값 사용(테스트 추가) |
| 후보 수 5 하드코딩(backend) | backend/app/models.py:353,360 `default=5` | 요청 생략 시 5 고정 | 운영 기본값 변경 불가 | live | 수정 | 중간 | `None` 기본 + `ROUTE_DEFAULT_TOP_N` 단일 권위 |
| 후보 상한 silent clamp | ai/collectors/odsay_collector.py 구 `min(max_candidates, MAX)` | 초과 요청을 조용히 절단 | 요청자가 7 요청 후 5 수신을 인지 불가 | live | 수정 | 중간 | 초과 시 CollectorError/422 명시 |
| loadLane 후보별 inline 호출 | ai/collectors/odsay_collector.py 구 `_build_candidate` | 후보 5개에 최대 7회 호출(배치 overfetch) | quota 낭비 | live | 수정 | 낮음(정확성 무관) | 지연 정밀화로 전환 |
| 경사 범례 3/6/10% | frontend/src/v2/MapFirstApp.tsx:1461-1464 | 지도 색상(2/5/8)과 범례 불일치 | 사용자 오해 | live | 수정 | **높음** | `SLOPE_COLOR_RAMP` 단일 상수 공유로 수정 |
| 5/10/20/30s 전체 재추천 타이머 | frontend/src/v2/MapFirstApp.tsx:1049-1083 | enrichment 미완료 시 전체 /recommend 최대 4회 재실행 | 외부 호출 증폭 | live | 수정 | 낮음 | 제거(§20) |
| 그늘 토글 상태·버튼 | MapFirstApp.tsx:959,1414-1451 / MapView.tsx | showShade 토글·aria-pressed | 제품 요구와 불일치 | live | 수정 | 낮음 | 제거, shade 자동 표시 |
| 경사 live network fallback | ai/features/elevation.py `_ensure_dem_tile`/Open-Meteo 분기 | 지역 DEM 누락 시 원격 COG 다운로드·Open-Meteo 호출 가능 | 부산 live 0회 계약 위반 가능 | live | 수정 | 중간 | `ELEVATION_NETWORK_FALLBACK_ENABLED`(기본 false)로 격리 |
| 그늘 lower_bound 표시 | backend/app/shade.py `estimate_kind="lower_bound"` | 높이 불완전 시 부분 그림자를 최소치로 표시 | "높이 완전" 요구와 불일치 | live | 수정 | 중간 | coverage<100%면 shade unavailable(비율·폴리곤 미생성) |
| shade 없음=오류 계약 | backend/app/providers/ai_pipeline.py 구 enrich | 후보 중 shade None이 있으면 502 | 정상 미계산 상태 처리 불가 | live | 수정 | 중간 | all-None·부분-None 정상 지원(§24) |
| 데모 고정 OD·시나리오 날씨 | backend/app/data/*, rule_demo.py | ROUTE_MODE=demo 전용 | live 혼입 없음(모드 스위치로 격리) | test/demo | 유지 | 없음 | 명시적 데모 모드 — 삭제 금지 대상 |
| Kakao 장소검색 demo 헤더 | backend places `X-Place-Search-Source` | demo 결과를 헤더로 구분 | live 혼입 차단 장치 | live | 유지 | 없음 | frontend가 demo 출처 거부 |
| OSMnx fallback | ai/collectors/osmnx_collector.py | 명시적 opt-in(기본 off) | 없음 | opt-in | 유지 | 없음 | estimated 표기 유지 확인 |
| 개인화 파라미터 기본 None | backend/app/settings.py | 미설정 시 개인화 비활성(503) | 없음 | live | 유지 | 없음 | 임의 기본값 없음 — 양호 |
| Busan 좌표 범위 상수 | ai/api/router.py Field(ge/le) | 서비스 지역 검증 | 없음 | live | 유지 | 없음 | 서비스 정의 값 |
| 데모 건물 DEMO_BUILDING_DATA | backend/app/shade.py | demo 건물 그늘 | BUILDING_SOURCE=vworld에서 미사용 | demo | 유지 | 없음 | 라벨 명시(estimated_demo) |
| bandit 지적(assert, B310 등) | scripts/, tests/ | 기존 코드 패턴 | 낮음 | — | 보고만 | 없음 | 이번 범위 밖 — 미수정 |
| ruff 기존 지적 224건 | 저장소 전반 | import 정렬·타입 표기 등 | 없음 | — | 보고만 | 없음 | 이번 변경분은 신규 지적 0건 유지 |
| 저장소 pin `xgboost-cpu==2.1.1` | ai/requirements.txt | 현 PyPI에 해당 버전 없음(3.0.0+만 존재) | 신규 환경 구축 실패 가능 | 배포 | 보고만 | 없음 | 관련 없는 dependency 변경 금지 원칙에 따라 미수정 |

## 검증된 부정 사례 없음 항목

- live 응답에 demo/mock/synthetic 혼입: 0건 (모드 스위치·헤더·명시 라벨로 격리, 테스트 존재)
- 누락값 임의 0 대체: 0건 (shade/terrain/stairs 모두 None 유지 계약 테스트 존재)
- estimated를 exact로 표시: 0건 (정류장 연결선은 항상 estimated, 점선 렌더 유지)
- 공급자 오류의 정상 경로 변환: 0건 (auth 실패 live 시도에서 명시적 오류 전파 확인)
- 오류 응답 캐시: 0건 (live 시도 후 캐시 디렉터리 빈 상태 확인)

생성시각: 2026-07-26T15:36Z (UTC)
