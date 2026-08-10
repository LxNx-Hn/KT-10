# 구현 명세

제품·모델·UI의 최종 계약은 `PRODUCT_DECISIONS.md`를 따릅니다.

## 런타임 흐름

현재 `ROUTE_MODE=demo`는 고정 후보에 90m 지형 추정과 합성 건물 높이
기반 그늘을 계산하는 기능 검증 흐름입니다. 운영 목표는 특정 대표 특성을
강제로 보존하는 방식이 아니라 아래 두 단계의 점수순 추천입니다.

1. 프론트가 Kakao Local 검색으로 부산 내 출발지·도착지를 선택한다.
2. 백엔드가 현재 날씨와 6개 기본 프로필 중 하나, 이번 이동 조건, 로그인
   사용자의 장기 설정을 모은다.
3. 백엔드는 AI 서버의 `POST /labeling/candidates`를 호출한다. AI 서버는
   ODsay와 TMAP 후보를 수집한다. OSMnx는
   `OSMNX_WALK_GEOMETRY_ENABLED=true`일 때만 ODsay 보행 geometry
   복구에 사용한다. 실패 공급자는 메타데이터에 남긴다.
4. AI 서버가 ODsay search 메타데이터와 TMAP exact 보행 geometry를
   결합해 EPSG:5179 공간 피처, 부산 QGIS 90m DEM 지형 피처, 실제
   수집시각 `captured_at`이 담긴 기본 스냅샷을 반환한다. 대중교통
   표시 선형은 이 단계에서 정류장 관측 좌표 기반 estimated이며,
   `loadLane` 정밀 선형은 최종 순위 확정 후 1위 후보에 1회, 그
   외 후보는 사용자가 해당 추천 카드를 선택했을 때
   `POST /api/routes/refine-transit` → AI `POST /routes/refine-transit`
   경유로만 조회한다(재선택은 캐시 재사용, 추가 호출 0회).
5. 백엔드가 요청 출발시각의 VWorld 건물 그늘을 계산한다. 합성 건물은
   명시적인 데모 모드에서만 사용한다. 그늘은 출발시각이 10~18시(KST),
   유효한 실측 날씨 관측(관측 age·출발시각이 `WEATHER_CACHE_TTL_SECONDS`
   유효기간 이내), 체감온도 25°C 이상, 태양 고도 양수, exact 실외 보행
   geometry, 회랑 건물 높이 100% 확인 조건을 모두 만족할 때만 계산하며,
   하나라도 불충족이면 VWorld 조회 없이 shade를 생략(None)한다.
   그늘 결과가 있으면 지도에 자동 표시되고 별도 토글은 없다.
6. 백엔드는 `captured_at`과 별도 `shade_evaluated_at`을 포함해 AI 서버의
   `POST /labeling/enriched-snapshots`를 호출한다. AI 서버는 checksum이
   포함된 동결 스냅샷과 `most_shade` 등의 사실 특성 라벨을 만든다.
7. `live` 모드는 같은 사실을 규칙 점수로 비교하고, `ai` 모드는
   `POST /rank/candidates`에서 명시적으로 선택한 모델 tier로 순위화한다.
   AI 서버의 직접 `POST /recommend`는 409를 반환하는 비활성
   호환 endpoint다.
8. 백엔드가 로그인 사용자의 후기 기반 온라인 상태를 최대 35% 범위에서
   혼합하고 상위 N개를 반환한다.
9. 프론트는 지도와 하단 시트 세로 경로 목록을 같은 선택 상태로
   표시하고 추정 geometry는 점선, 그늘·햇빛 구간은 구분 색상으로
   표시한다.

지도 공급자는 경로 생성자가 아닙니다. Kakao/Naver 지도 링크에서 대중교통 geometry를 역추출하지 않습니다.

### 그늘 시각 변경

최초 추천 응답에는 서버가 30분 동안 보관하는 후보군을 가리키는
`routeSetToken`이 포함됩니다. 사용자가 그늘 계산 시각을 바꾸면 프론트는
`POST /api/routes/refresh-shade`만 호출하며 Kakao 장소검색, ODsay·TMAP
후보 수집, OpenWeather 조회를 다시 실행하지 않습니다.

- 모든 후보는 건물 조회 전에 경로 위치의 태양 고도를 먼저 계산합니다.
- 태양 고도가 0도 이하면 `not_daylight`로 확정하고 VWorld 조회와 그림자
  폴리곤 계산을 생략합니다.
- 주간에는 최초 추천 때 저장된 경로와 디스크에 이미 있는 VWorld 건물
  캐시만 사용합니다. 누락 구간을 시간 변경 요청에서 외부 조회하거나
  백그라운드 보충하지 않습니다.
- 동일 후보군 안에서 변경된 그늘 사실을 반영해 순위만 다시 계산합니다.
  토큰이 만료됐거나 서버가 재시작되면 409를 반환하고 새 경로 검색을
  요청합니다.
- 현재 토큰 캐시는 단일 백엔드 프로세스 기준입니다. 여러 백엔드
  인스턴스로 확장할 때는 공유 TTL 저장소로 교체해야 합니다.

## 사실성 규칙

- 키 미설정·API 오류·빈 응답의 상태는 오류 메타데이터로 유지
- ODsay 구간 끝점을 이은 추정 직선은 지도 연결선으로만 사용하고
  지형·공간 피처·그늘 분석 geometry에서는 제외
- 계단·승강기·저상버스·혼잡의 미확인 상태는 `null`로 유지
- 혼잡은 교통카드 데이터 연결 상태에서 계산
- 부산 QGIS DEM 경사는 90m 표본 사이 방향별 경사 구간으로 표시하며,
  보도 실측 구배와 구분
- 합성 건물 높이의 그늘은 `estimated_demo`, VWorld 건물 도형·높이 기반
  그늘은 `estimated_public`으로 구분
- 높이 결측 건물은 `lower_bound` 계산 범위 밖으로 분류
- 건물 그늘은 오목한 footprint를 보존한 스윕 영역과 실외 도보 선의 교차
  길이로 계산하며, 높이 일부 결측 결과는 `lower_bound`로 명시
- 그늘 계산 범위는 건물이며 나무 그늘·지형 그림자는 제외 범위로 명시
- 사고다발지역은 모델 입력에서 제외
- 순위를 UI의 주 결과로 표시하고 숫자는 `베이스라인 적합 점수`로 보조
  표시할 수 있음
- 베이스라인 점수는 안전도, 접근 가능 확률, 사고 확률 또는 도착 성공
  확률로 표현하지 않음
- 추천 이유는 관측 사실만 사용하고 SHAP 값을 인과 설명으로 사용하지 않음

## 학습·개인화

사용자에게 노출되는 초기 배치 진입점은 백엔드
`POST /api/routes/labeling-candidates`입니다. 32자 이상의
`LABELING_API_TOKEN`을 `X-Labeling-Token` 헤더로 보내야 하며, 추천과
동일한 후보 수집→건물 그늘→동결 스냅샷 흐름을 실행합니다. AI 내부
`POST /labeling/candidates`는 건물 그늘 전 기본 후보 수집용입니다.

승인 운영 모델은 `ai/data/rankers.human-validated.zip`입니다. 모델이
없거나 6개 프로필 또는 피처 스키마가 맞지 않으면 `ROUTE_MODE=ai`의
백엔드 `POST /api/routes/recommend`는 준비되지 않은 상태를 명시적으로
반환합니다. `ROUTE_MODE=live`의 규칙 비교는 승인 모델 없이 동작합니다.

초기 평가 단계에는 동일 후보군의 확인 피처를 프로필 기준으로 비교해
베이스라인 모델을 만듭니다. 미확인 값은 0으로 대체하지 않고 비교에서
제외하며, 공급자 이름과 기존 순위를 근거로 사용하지 않습니다. 경로
사실·판단 근거·미확인 항목, 루브릭 해시와 모델 버전을 보존합니다.

- `rankers.bootstrap-baseline.zip`: 프로필 평가 라벨 기반 비운영 비교선
- `rankers.human-candidate.zip`: 실제 사용자·전문가 라벨 기반 후보
- `rankers.review-mixed-candidate.zip`: 동의 후기를 제한적으로 섞은
  별도 후보, 사람 후보로 가장하거나 자동 승격하지 않음
- `rankers.human-validated.zip`: 검토한 후보 SHA-256, 승인자와 근거를
  기록해 관리자가 수동 승격한 운영 모델

모든 모델은 checksum manifest와 프로필별 XGBoost JSON을 담은 ZIP이며
pickle을 역직렬화하지 않습니다. 현재 저장소의 초기 평가 모델은
380 OD·1,137개 실제 후보와 6,822개 프로필 평가로 학습됐습니다.
사람 검증 운영 모델은 별도 라벨과 관리자 수동 승격 없이는 생성되지
않습니다.

학습/검증은 동일 OD가 경계를 넘지 않는 그룹 holdout을 사용하고 NDCG@3,
후보쌍 선호 정확도와 프로필별 오류를 기록합니다.

후기 저장 전 서버가 route/model/feature snapshot을 서명합니다. 리뷰는 실제 표시된 impression과 일치해야 하며 만족도·이용 가능·재사용 의향으로 개인 온라인 상태를 즉시 갱신합니다. 2026-07-23 승인된 초기 파일럿 정책은 개인 점수의 최대 영향 35%, 사전 후기 5건으로 설정해 소량 후기의 급격한 순위 변화를 제한합니다. 전역 후보 학습은 자동 실행하지 않으며, 관리자가 동의 후기를 검토·익명화한 다음 명시한 50% 미만의 비중으로 후보 모델만 생성합니다. 운영 모델 교체는 별도 승인 단계입니다.

## 데이터베이스

PostgreSQL만 지원하며 SQLite 자동 대체는 없습니다. Alembic
`20260720_0001`이 사용자, 프로필, impression, 리뷰, 시설 신고 스키마를
생성하고 `20260724_0002`가 동일 사용자·동일 impression의 중복 후기를
차단합니다. `20260724_0003`은 혼잡·환승 안내·교통약자 시설의 nullable
1~5 직접 관측값과 범위 제약을 추가합니다. 시설 신고는 관리자 검토
상태만 바꾸고 원본 공간 데이터를 자동 수정하지 않습니다.

## UI

- 장소 검색: live PWA는 `VITE_KAKAO_MAP_KEY`의 Kakao JavaScript
  Places SDK와 부산 전역 bounds를 사용합니다. JavaScript 키가 없는
  서버형 구성은 `X-Place-Search-Source=kakao-rest`가 확인된 응답만
  사용하며 demo 목록을 실제 검색처럼 표시하지 않습니다.
- 검색 전: 장소 검색, 실제 현재 위치, 6개 기본 프로필, 짐 많음·유아차·
  계단 회피·그늘 우선·저상버스 우선·환승 최소, 음성
- 검색 후: 지도 중심 화면과 하단 결과 시트의 세로 경로 목록, 순위,
  베이스라인 적합 점수, 사실 특성 배지, 구간별 지도, 날씨 실측,
  저상버스 도착, 실제 이용 후기, 시설 신고. 시트는 collapsed /
  medium / expanded 3단계 snap을 사용하고, 목록 내부 세로 스크롤을
  시트 드래그보다 우선하며 시트 제스처는 배경 지도로 전파되지 않는다
  (PR #24 `e59bb227` 모바일 레이아웃·시트·지도 컨트롤 안정화 반영)
- 선택 동기화: 목록에서 카드를 선택하면 지도 활성 경로·그늘
  오버레이가 바뀌고, 지도에서 경로를 선택하면 해당 카드로 이동
- 접근성: 카드 클릭·키보드·스크린리더 대체 조작, 큰 글씨와 축약
  정보/상세 펼치기
- 로그인: 카카오 OAuth authorization-code + state + HttpOnly 서비스 세션
- 게스트: 경로 검색 가능, 프로필·후기 개인화 저장 불가

## 검증 명령

```powershell
$env:PYTHONUTF8='1'
$env:PYTHONPATH='ai'
.\.venv\Scripts\python.exe -m pytest ai\tests -q
$env:PYTHONPATH='backend'
.\.venv\Scripts\python.exe -m pytest backend\tests -q
.\.venv\Scripts\python.exe -m compileall -q ai backend
cd frontend
npm test -- --run
npm run build
```

외부 키가 없는 CI는 계약·실패경계·모델 학습·UI를 검증합니다. 실제
공급자 응답과 Kakao JavaScript Places 브라우저 E2E는 키가 적용된
서버·배포 origin이 먼저 필요하므로 [DEPLOYMENT.md](DEPLOYMENT.md)의
선행 조건과 명령으로 별도 실행합니다.
