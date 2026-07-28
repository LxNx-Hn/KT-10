# v1.0.0 · v1.0.1 · 최신 main 비교 (2026-07-27)

- v1.0.0: `f56f414c89e8435797e86b420b926017cb91f979` (커밋 메시지 "v1.0.0" — 태그 아님)
- v1.0.1: `eb77e3fd321772f3aa360fef00b8d07f31863f93` (커밋 메시지 "v1.0.1" — 태그 아님)
- 최신 main: `5e201c0c1567bc93b89a4f98b605f21814edc08c` ("fix(v1.0.1): cache 90m slope and shared shade overlays")
- 저장소의 실제 태그는 `archive/ai-set-before-main-consolidation-20260723` 하나뿐이다.
- diff 규모: v1.0.0→v1.0.1 13파일(+155/−13), v1.0.1→main 50파일(+4,029/−310).

판정: 최신에서 이미 완료 / 최신에서 유지 필요 / 최신 회귀 / 이번 구현 대상 / 보고만 필요 / 관련 없음 / 확인 불가

| 항목 | v1.0.0 | v1.0.1 | 최신 main(작업 전) | 현재 작업과의 관계 | 판정 |
| --- | --- | --- | --- | --- | --- |
| 기본 후보 수 | 5 (모델·frontend·AI 각각 하드코딩) | 동일 | 동일 | ROUTE_DEFAULT_TOP_N 단일 권위로 대체 | 이번 구현 대상 |
| 후보 수 허용 범위 | 1~10 | 동일 | 동일 | 유지, 초과 시 422 명시화 | 최신에서 유지 필요 |
| 후보 배치 크기 | 3 고정 | 동일 | 동일 | 배치는 보행 조립용으로 유지, loadLane overfetch 제거 | 이번 구현 대상 |
| 후보 절단 시점 | 배치 조립 후(overfetch) | 동일 | 동일 | loadLane이 배치에서 분리되어 초과 호출 소멸 | 이번 구현 대상 |
| searchPubTransPathT | OD당 1회+파일캐시 | 동일 | 동일 | single-flight·계측 추가 | 최신에서 유지 필요 |
| loadLane | 후보별 inline 호출 | 동일 | 동일 | 최초 1위 1회 + 선택 시 지연 호출로 전환 | 이번 구현 대상 |
| 후보 조립 | search+loadLane 결합 | 동일 | 동일 | base(estimated transit)/refined 분리 | 이번 구현 대상 |
| 후보 병합 | geometry 유사도+transit 서명 | 동일 | 동일 | 유지(동일 수집 실행 내 비교라 estimated에도 안전) | 최신에서 유지 필요 |
| route ID | 전체 정밀 path 해시 기반 | 동일 | 동일 | semantic fingerprint(보행 path+노선·승하차)로 교체 | 이번 구현 대상 |
| route-set token | 랜덤 opaque 토큰 | 동일 | 동일 | 유지 | 최신에서 유지 필요 |
| route-set cache | in-memory TTL 30분 | 동일 | 동일 | metadata·revision·token lock·update_candidate 추가 | 이번 구현 대상 |
| ODsay cache | 파일, schema v1, TTL 30분 | 동일 | 동일 | 유지(+오류 미캐시 재확인) | 최신에서 유지 필요 |
| TMAP 보행 geometry | 있음 | 동일 | v1.0.1→main에서 계단 감지 강화·캐시 개선 | 유지(경사·그늘 분석 입력) | 최신에서 유지 필요 |
| GLO-90 경사 | Open-Meteo/원격 COG fallback 포함 | 동일 | main에서 부산 QGIS 지역 DEM 우선 | live fallback 차단 플래그 추가(기본 off) | 최신 회귀(부분)→이번 구현 대상 |
| QGIS 부산 DEM | 없음 | 없음 | 있음(`busan_dem_clipped_90m.tif`, EPSG:5179 90m) | 유지·회귀 방지 | 최신에서 이미 완료 |
| 90m slopeSegments | 없음 | KakaoMap 표시 도입 | 캐시 포함 완성 | 유지 | 최신에서 이미 완료 |
| 경사 cache | 없음 | 없음 | elevation 파일 캐시 v3 | 유지 | 최신에서 이미 완료 |
| 경사 등급 | 3/6/10% (frontend) | 지도 2/5/8 도입 | 지도 2/5/8 확립 | 범례가 여전히 3/6/10 → 지도 상수와 단일화 | 최신 회귀→이번 구현 대상 |
| 경사 색상 | 단일 walk색 | QGIS 램프 도입 | 유지 | 범례가 램프 상수를 직접 사용하도록 변경 | 최신에서 유지 필요 |
| VWorld 건물 조회 | corridor 250m·페이지네이션 | 동일 | main에서 corridor box·중복 feature 검증 강화 | gate 뒤에서만 호출되도록 변경 | 최신에서 유지 필요 |
| 그늘 계산 | 태양·exact 보행 gate만 | 동일 | main에서 공유 context·30분 버킷 캐시 | 시간창·체감온도·관측 유효성·높이 완전성 gate 추가 | 이번 구현 대상 |
| 그늘 cache | 없음 | 없음 | shade 파일 캐시 v4(30분 버킷) | 유지 | 최신에서 이미 완료 |
| 후보군 공유 건물 context | 없음 | 없음 | prepare_shade_context 공유 | 유지(+coverage 불완전 시 준비 생략) | 최신에서 이미 완료 |
| 출발시각 변경 | refresh-shade 재사용 | 동일 | 동일 | token lock·topN 상한 검증 추가 | 최신에서 유지 필요 |
| frontend enrichment retry | 5/10/20/30s 전체 재추천 | 동일 | 동일 | 제거(§20) | 최신 회귀→이번 구현 대상(제거) |
| 그늘 토글 | showShade FAB + aria-pressed | 동일 | 동일 | 제거, shade 자동 표시 | 이번 구현 대상(제거) |
| 지도 z-index | v1.0.1에서 경사선 z5 확립 | 확립 | 그늘1<대안2<그늘경로3<외곽선4<경사선5<시설6·마커7 | 목표 순서와 이미 일치 → 회귀 테스트 유지 | 최신에서 이미 완료 |
| 버스·지하철 색상 | mode 고정색 | 동일 | 동일 | 유지(경사색은 walk 전용) | 최신에서 유지 필요 |
| 후보 3·5·10 benchmark | 없음 | 없음 | 스크립트+2026-07-26 결과 JSON | 7 추가(3·5·7·10) | 이번 구현 대상 |

비고:
- 최신 경사 기준 2·5·8%는 의도된 변경으로 유지했고, 과거 3·6·10%는 범례에서 제거했다.
- v1.0.0/v1.0.1 구현을 최신 코드에 복원한 항목은 없다.

생성시각: 2026-07-26T15:36Z (UTC)
