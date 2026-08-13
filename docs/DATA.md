# 데이터 계약

`data/catalog.json`이 모델 입력·제외·수령 대기 데이터의 기계 판독 가능한 기준입니다.

제품 수준의 최신 계약은 `PRODUCT_DECISIONS.md`를 따릅니다. 데이터에서는
`경로 사실`, `경로 특성`, `프로필·조건 적합도`, `라벨 출처`를 서로 다른
필드로 보존합니다.

## 디렉터리 역할

- `data/ai/`: 프론트·백엔드 데모와 회귀 테스트용 JSON. 임의 OD 실경로가 아님
- `data/raw/`: AI 런타임이 읽는 정규화된 공간 입력
- `data/da/`: 데이터팀 원본·중간 산출물과 출처 확인 자료
- `ai/data/training/`: 실제 라벨과 해당 경로 피처 스냅샷
- `ai/data/cache/`: 재생성 가능한 레이어·OSM 캐시(Git 제외)

공간 원본은 EPSG:4326으로 읽고 거리 버퍼는 EPSG:5179에서 계산합니다. 부산 유효 범위 밖의 좌표는 제거합니다. 레이어 미수신·컬럼 미확인·주변 관측 없음은 상황에 따라 `null`로 남기며, “정보 없음”을 숫자 0으로 만들지 않습니다.

## 현재 활성 레이어

쉼터, CCTV, AED, 전동휠체어 충전기, 교통약자 이동지원센터, 장애인복지시설,
배리어프리 문화·관광지, 동백전 생활 인프라, 스마트 버스쉘터, 도시철도 접근성,
횡단보도 신호, 버스정류장을 사용합니다. 각 파일의 공식 URL·라이선스·검증일은
`data/catalog.json`에 기록합니다.

이동지원센터의 슬로프형 차량 대수와 관광지·시설의 편의정보는 시설 또는 목적지
정보입니다. 보행 경로의 경사로·계단·연석·폭 정보와 별도로 보존하며, 경로 단위
사실로 변환하지 않습니다.

부산교통공사 역사 편의시설 원본의 `외부경사로(지상역 출구)`는 역별 수량 집계다.
따라서 역에 외부경사로가 있다는 시설 사실에는 사용하지만, 출입구 좌표·선형이
없어 특정 보행 경로가 그 경사로를 지난다는 사실로 변환하지 않는다.
API에는 `stationExternalRampCount`, `stationWheelchairLiftCount`와 원본 출처를
역 단위 재고로만 제공한다. 출구별 geometry가 확보되기 전까지
`stationRampRouteMatch`는 `null`이며 `rampPoints` 또는 `rampReplacesStairs`로
승격하지 않는다.

한국사회보장정보원 장애인편의시설 상세 API의 기구표는 `주출입구 접근로`처럼
시설 접근성 항목을 반환한다. 물리 경사로의 좌표·선형·기울기를 반환하지 않으므로
이 항목을 경사로 존재 또는 경로 단위 `hasSlope`로 추론하지 않는다. 원본 조회에는
공공데이터포털 Decoding 키와 일 100회 개발계정 한도가 적용된다.

장애인복지시설 원본 243건 중 5건은 부산 유효 범위 밖 좌표여서 원본 파일에는
보존하고 지도 공간 레이어에서는 제외했습니다. 실제 지도 활용 행 수는 238건입니다.

사고다발지역 파일은 보존하되 2026-07-16 자문 결정에 따라 현재 서비스와 모델에서 제외합니다.

## 제공 예정 데이터의 경계

- 2023~2025 대중교통 만족도: 초기 기준과 외부 타당도 비교용이며 개별 경로 선택 Y가 아님.
  부산 조사에서 확인된 혼잡·환승정보·교통약자 시설 차원은 조사 점수를
  경로 가중치로 추론하지 않고, 실제 경로 이용 후기의 선택형 1~5 직접
  관측 항목을 설계하는 데만 사용함
- 2025년 4월 부산 교통카드: 첨두·시간대 수요 보조 피처이며 교통약자 개인 선호 Y가 아님
- DRT 운행지역: 이용 가능 권역·후보 확장용
- 역사 승강기·에스컬레이터 좌표/운영상태: 출구 기반 위치 가공과 시설 사실 확인용

## 라벨 스키마

`route_labels.csv`의 `group_id`는 같은 시점·조건에서 비교한 후보 집합이고
`holdout_group_id`는 시간·조건과 무관한 동일 방향 OD입니다. 학습/검증
분리는 `holdout_group_id` 단위로 수행해 같은 OD의 반복 수집본이 양쪽에
섞이지 않게 합니다. `route_id`는 좌표·구간·공급자 fingerprint입니다.
`route_features.jsonl`은 라벨을 받은 바로 그 후보의 피처를 보존합니다.
이후 실제 사용자 후기는 서버가 서명한 스냅샷과 연결되므로 클라이언트가
학습 피처를 임의 수정할 수 없습니다.

실제 후보 스냅샷은 `route-feature-snapshot-v2`이며 최소한 다음 계보를
가집니다.

- 실제 경로를 수집한 `captured_at`
- 그늘을 계산한 출발/평가 시각 `shade_evaluated_at`
- `group_id`, `holdout_group_id`, `route_id`
- 경로·건물 공급자와 geometry 품질
- 전체 모델 피처와 정규화된 `feature_snapshot_hash`

`captured_at`과 `shade_evaluated_at`은 의미가 다릅니다. 미래 출발 시각의
그늘을 계산해도 스냅샷 수집 시각을 미래로 바꾸지 않습니다.

기본 프로필은 `general`, `elderly`, `child`, `youth`, `disabled`,
`pregnant` 6개입니다. 짐 많음, 유아차, 계단 회피, 그늘 우선, 저상버스
우선, 환승 최소는 프로필 ID가 아니라 같은 평가 그룹의 상황 조건입니다.

## 두 단계 피처 계약

### 1단계: 경로 사실·특성

- 공급자 원문과 geometry fingerprint
- 총시간, 도보거리, 환승 수
- 계단·승강기·저상버스의 값과 확인 상태
- 부산 QGIS 90m DEM의 평균·최대 경사와 누적 오르막, 표본 사이 방향별 경사 구간
- 요청 시각의 건물 그늘 비율·거리와 건물 높이 커버리지
- 데이터 출처, 정확도, 관측시각과 미확인 필드
- 위 사실에서 생성한 특성 배지와 배지 생성 규칙 버전

부산 QGIS DEM은 90m 격자 지형 추정이며 보도 실측 구배가 아닙니다. 그늘은
건물만 포함하고 나무·지형 그늘은 포함하지 않습니다. 높이 결측·0,
geometry 결측, 야간 상태를 임의의 그늘 0%로 바꾸지 않습니다.
지도 경사 색상은 경로 전체 평균을 반복하지 않고 확인된 보행 geometry를
따라 만든 각 표본 구간의 절대 경사 등급을 사용합니다.

### 휠체어 보행 경로와 물리 경사로 계약

계단 회피 요청에서는 TMAP 보행자 경로 API에 공식
`searchOption=30`(최단거리+계단제외)을 보낸다. 휠체어 요청은 여기에 더해
OpenRouteService의 `wheelchair` profile을 필수로 호출한다. ORS 요청에는
`steps`, `ferries` 회피와 노면(`cobblestone:flattened`), track grade 1,
평탄도 `good`, 최대 낮춘 턱 6cm, 최대 경사 6%, 최소 폭 0.9m 제한을 보낸다.
6cm는 ORS 공식 wheelchair 기본값이며 일반 연석·계단 허용을 뜻하지 않는다.
ORS wheelchair profile의 `wheelchair` 접근 제한도 함께 적용한다. 반면
차단봉·문·게이트의 실제 개방 상태와 통과 폭은 공급자 결과만으로 확정하지
않고 데이터 한계로 공개한다.
ORS `extra_info`는 공식 응답 키 차이(`osmid` 요청은 `osmId` 응답,
`waytype`은 배포 버전에 따라 `waytype` 또는 `waytypes`)를 명시적으로
정규화한다. steepness·suitability·surface·waytype·osmid 각각의 `values`가
반환 geometry 전체 구간을 덮지 않으면 해당 휠체어 후보를 거부한다.
모든 실제 보행·환승 구간에 이 제약이 적용된 후보만 휠체어 추천에 남긴다.
ORS가 미설정·실패하면 TMAP 계단 회피 결과로 대체하지 않고 503을 반환한다.

TMAP 보행자 응답의 안내점 `turnType=128`(경사로 진입),
`turnType=129`(계단+경사로 진입)만 물리 경사로 근거로 사용한다. 해당 좌표가
있을 때만 `hasSlope=true`, `rampPoints`, `rampEvidenceSource`를 제공하고,
129일 때만 `rampReplacesStairs=true`로 표시한다. DEM 경사도는 지형 높이
변화 추정이며 물리 경사로의 존재나 계단 대체 가능성을 뜻하지 않는다.

TMAP 경사로 안내점과 ORS wheelchair 제약은 평균 12m·최대 25m 이내로
유사한 선형에서만 결합한다. 서로 다른 길의 경사로를 휠체어 경로 근거로
옮기지 않는다. ORS는 OpenStreetMap 태그를 사용하므로
`stairsExcludedByProvider=true`는 공급자가 지도에 기록된 계단을 회피해
탐색했다는 뜻이다. 이를 `stairsCount=0` 또는 `hasStairs=false`로 바꾸지 않으며,
별도 명시 계단 관측이 없으면 사용자 사실값은 `null`로 유지한다.
`wheelchairConstraintsApplied=true`는 공급자 제약이 적용됐다는 뜻이지 현장
전수 확인이나 통행 보장을 뜻하지 않는다. OSM 태그 누락과 공사·적치물·고장
같은 임시 장애물 한계를 API의 `wheelchairDataLimitations`와 추천 주의문에
항상 함께 제공한다.

### 도시철도·버스 휠체어 탑승 계약

`busan_subway_elevator_routes_20251231.csv`는 부산교통공사
2025-12-31 기준 엘리베이터 이동경로 448행이다. 같은 출구번호가 부여된
층간 이동 행과, 상세위치에서 해당 출구 방향을 명시한 승강장 행만 연결해
지상 1층부터 승강장까지 이어지는 출구를 계산한다. 역에 엘리베이터가 있다는
재고 값이나 층 번호만으로 서로 다른 대합실을 연결하지 않는다. 공식 원본은
3호선 수영역을 누락하고 2호선 서면역을 두 표기로 제공하므로, 누락은 다른
호선 값으로 채우지 않고 미확인으로 보존한다.

휠체어 후보의 도시철도 구간은 ODsay가 제공한 탑승·하차 출구번호가 위 공식
출구-승강장 이동경로와 모두 정확히 일치할 때만 통과한다. 미일치·출구번호
미제공·원본 누락은 `false`가 아니라 `null`이며, 휠체어 후보에서는 닫힌
방식으로 제외한다. 버스 구간도 모든 탑승 구간이 저상버스로 확인된 경우만
통과한다. 역 단위 외부경사로 수량은 출구 위치가 없어 이 판정에 사용하지
않는다.

`busan_subway_accessible_exit_coordinates_20260813.csv`는 위 공식 동선에서
확인된 출구번호에만 OpenStreetMap `railway=subway_entrance` 노드 좌표를
결합한 스냅샷이다. 공식 접근 가능 출구 56개 중 좌표가 일치한 53개를
55개 노드로 보존한다. 경성대부경대 3번과 국제금융센터부산은행 2·4번은
좌표가 없어 추정하지 않는다. 생성 스크립트는
`scripts/fetch_subway_accessible_exit_coordinates.py`이며 각 행에 OSM node
ID, 조회일, ODbL 1.0을 기록한다.

휠체어 도시철도 요청은 첫·마지막 역의 공식 접근 가능 출구 중 사용자
위치에 가장 가까운 좌표를 선택하고, 해당 지상 도보 구간을 ORS wheelchair
profile로 다시 탐색한다. 출구를 바꾼 뒤에는 ODsay의 기존 보행 수치를
재사용하지 않고 ORS가 반환한 실제 거리·시간으로 구간 및 전체 합계를
다시 계산한다. 좌표가 없거나 ORS 검증이 실패한 출구는 통행 가능하다고
표시하지 않는다. OpenStreetMap 좌표는 ODbL 1.0에 따른다:
https://www.openstreetmap.org/copyright

공식 계약:

- 보행자 경로 요청: https://tmap-skopenapi.readme.io/reference/%EB%B3%B4%ED%96%89%EC%9E%90-%EA%B2%BD%EB%A1%9C%EC%95%88%EB%82%B4
- 보행자 응답 코드: https://tmap-skopenapi.readme.io/reference/%EA%B2%BD%EB%A1%9C%EC%95%88%EB%82%B4-%EC%83%98%ED%94%8C%EC%98%88%EC%A0%9C
- ORS wheelchair routing options: https://giscience.github.io/openrouteservice/api-reference/endpoints/directions/routing-options
- ORS extra info: https://giscience.github.io/openrouteservice/api-reference/endpoints/directions/extra-info/
- ORS OSM tag filtering: https://giscience.github.io/openrouteservice/technical-details/tag-filtering
- OSM 물리 경사로 태그: https://wiki.openstreetmap.org/wiki/Key:ramp

### 2단계: 적합도

- 기본 프로필 ID
- 이번 이동 조건
- 필요한 장기 이동지원 설정
- 베이스라인 점수, 최종 점수와 순위
- 적용 모델 종류·버전·피처 스키마 버전
- 제외 또는 `확인 필요` 사유

점수는 안전도나 성공확률이 아니라 후보 간 상대 적합도입니다.

## 평가 라벨 출처

사람 평가 CSV는 평가자 ID, 그룹·경로 ID, 피처 스냅샷 해시, 6개 프로필,
0~4 정수 relevance와 메모를 보존합니다. 학습기는 모든 스냅샷과 라벨의
경로 집합, 해시, 프로필 행렬, 동일 평가자의 중복 라벨, 최소 평가자 수를
검증합니다.

초기 평가 JSONL은 이 계약에 더해 `evaluation_run_id`, `evaluation_source`,
`rubric_version`, `prompt_hash`, 실제 `evaluated_at`, 판단 근거를
필수로 보존합니다. LLM/Codex judge 라벨은 초기 베이스라인으로 사용할 수
있지만 사람 라벨과 합쳐 출처를 숨기지 않습니다.

모델은 실행 가능한 pickle이 아니라 checksum이 포함된 XGBoost JSON ZIP
아카이브로 저장합니다.

| 파일 | 라벨 출처와 역할 |
| --- | --- |
| `rankers.bootstrap-baseline.zip` | 프로필 평가 기반 비운영 비교선 |
| `rankers.human-candidate.zip` | 최소 9명 사람 평가 기반 수동 검토 후보 |
| `rankers.review-mixed-candidate.zip` | 동의 후기를 제한적으로 섞은 별도 후보, 자동 승격 금지 |
| `rankers.human-validated.zip` | 사람 후보의 SHA-256과 승인 근거를 확인해 관리자가 승격한 운영 파일 |

동의 후기 export는 `training_eligible=true`인
`live_route_candidate`만 포함하고 데모·과거 비적격 후기의 수와 사유를
`export_report.json`에 남깁니다. 실제 후기 relevance는 가중 피드백의
유한 연속 0~4 값이며 임의 반올림하지 않습니다. 사람 직접 평가 CSV의
0~4 정수 계약과는 별도 loader로 분리합니다.

후기의 `crowding_difficulty`, `transfer_information_difficulty`,
`accessibility_facility_difficulty`는 사용자가 실제 이용 후 선택적으로
남긴 1~5 직접 관측값입니다. 미응답은 `null`로 보존합니다. 현재 온라인
개인화 target과 전역 후보 relevance에는 이 값을 자동으로 섞지 않으며,
`training_consent=true`인 검증된 후기만 향후 관리자 수동 분석 대상으로
다룰 수 있습니다.

초기 배치는 백엔드의 보호된
`POST /api/routes/labeling-candidates`에서만 생성합니다. 요청에는 32자
이상의 `LABELING_API_TOKEN`을 `X-Labeling-Token`으로 보내며, 백엔드는
추천과 같은 실제 후보 수집→건물 그늘→피처 스냅샷 흐름을 사용합니다.
