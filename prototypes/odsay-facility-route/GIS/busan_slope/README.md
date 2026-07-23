# ODsay Walking Slope Analysis

> **ODsay 대중교통 경로의 도보 구간을 DEM(수치표고모델)과 비교하여 경사도를 계산하고, QGIS에서 시각적으로 확인하는 프로젝트입니다.**

---

# 프로젝트 소개

대중교통 길찾기 서비스는 버스, 지하철, 도보를 모두 포함한 경로를 제공합니다.

하지만 실제 보행약자에게는 단순히 가장 빠른 경로보다

- 얼마나 많이 걷는지
- 얼마나 가파른 길인지
- 환승 시 이동 부담이 큰지

와 같은 정보가 더욱 중요할 수 있습니다.

이 프로젝트는 **ODsay가 추천한 대중교통 경로 중 도보 구간만 추출**하여 부산 DEM(Digital Elevation Model)과 비교하고, 경사도를 계산합니다.

버스와 지하철 구간은 전체 이동 흐름을 이해하기 위한 참고용으로만 사용하며, 경사도 계산에는 도보 이동 구간만 사용됩니다.

---

# 전체 분석 흐름

```text
출발지 · 목적지 선택

↓

카카오 장소 검색

↓

ODsay 대중교통 경로 조회

↓

ODsay 도보 궤적 조회

↓

도보 구간을 약 10m 단위로 분할

↓

부산 DEM에서 시작점·종료점 고도 추출

↓

선분별 경사 계산

↓

경로별 통계 생성

↓

GeoPackage 저장

↓

QGIS 프로젝트 자동 갱신
```

---

# 경사 계산 원리

도보 선분의 시작점과 끝점의 고도를 이용하여 경사율을 계산합니다.

```text
grade_pct =
(종료 고도 - 시작 고도)
────────────────────── × 100
      수평거리
```

|값|의미|
|---|---|
|양수|오르막|
|음수|내리막|
|abs_grade|방향을 제거한 절대 경사|

AI 점수화에서는 일반적으로 **abs_grade** 사용을 권장합니다.

---

# Quick Start

처음 사용하는 경우 아래 순서대로 진행하면 됩니다.

### 1. 필요한 프로그램 설치

- Windows
- QGIS 3.44 LTR
- Node.js

### 2. 필요한 API 준비

- ODsay API
- 카카오 JavaScript API
- 부산 버스 공공데이터 API

### 3. `.env` 생성

```
.env.example
```

파일을 복사하여

```
.env
```

를 만든 뒤 API Key를 입력합니다.

### 4. ODsay 서버 실행

```powershell
cd ODsay

node --env-file=.env server.mjs
```

### 5. 브라우저 접속

```
http://localhost:8080
```

### 6. 출발지와 목적지 선택

카카오 검색 결과에서 원하는 장소를 선택합니다.

### 7. 분석 실행

웹에서

```
현재 장소로 QGIS 경사도 분석
```

버튼을 클릭합니다.

### 8. 결과 확인

분석이 완료되면

```
qgis_project/busan_slope.qgz
```

를 열어 결과를 확인합니다.

> **QGIS가 실행 중이면 GeoPackage 갱신이 실패할 수 있으므로 반드시 QGIS를 종료한 뒤 분석을 실행하는 것을 권장합니다.**

---

# 프로젝트 구조

프로젝트는 아래와 같은 구조를 사용합니다.

```text
DA_jeewonlee/

├── ODsay/
│   ├── server.mjs
│   ├── public/
│   ├── data/
│   └── .env
│
└── GIS/
    └── busan_slope/
        ├── qgis_project/
        ├── 02_processed/
        ├── 04_output/
        └── scripts/
```

---

# 주요 파일

|경로|설명|
|---|---|
|`qgis_project/busan_slope.qgz`|QGIS 프로젝트|
|`04_output/current_odsay_analysis.gpkg`|최신 분석 결과|
|`02_processed/dem/busan_dem_clipped_90m.tif`|경사 계산에 사용한 DEM|
|`scripts/odsay_walking_slope_analysis.py`|전체 분석 스크립트|

---

# 분석 결과 확인

QGIS에서

```
01 경로별 전체 이동 경로
```

를 펼치면

```
경로 01
경로 02
경로 03
...
```

처럼 경로별 그룹이 생성됩니다.

각 그룹에는

- 도보 경사도
- 대중교통 경로

두 개의 레이어가 포함됩니다.

기본적으로 첫 번째 경로만 표시됩니다.

---

# GeoPackage 구성

분석 결과는

```
current_odsay_analysis.gpkg
```

에 저장됩니다.

|레이어|설명|
|---|---|
|current_slope_segments|약 10m 단위 도보 경사|
|current_transit_lines|버스·지하철 경로|
|current_route_summary|경로별 통계|

---

# current_slope_segments

도보 선분별 경사 계산 결과입니다.

## 주요 필드

|필드|설명|
|---|---|
|route_no|ODsay 추천 경로 번호|
|walk_role|출발 접근 / 환승 / 도착 접근|
|length_m|선분 길이|
|grade_pct|진행 방향을 고려한 경사율|
|abs_grade|절대 경사율|
|grade_class|경사 등급|
|geom_quality|도보 형상 품질|

---

## walk_role

|값|설명|
|---|---|
|origin_access|출발지 → 첫 승차|
|transfer|환승 도보|
|destination_access|마지막 하차 → 목적지|

---

## grade_class

|등급|절대경사|
|---|---|
|gentle_0_2|0~2%|
|moderate_2_5|2~5%|
|steep_5_8|5~8%|
|very_steep_over_8|8% 초과|

---

## geom_quality

|값|설명|
|---|---|
|odsay_walk_path|ODsay 도보 API 결과|
|straight_line_fallback|직선 대체 경로|

`straight_line_fallback`은 실제 보행로가 아니므로 모델 학습 시 별도 처리하는 것을 권장합니다.

---

# current_route_summary

경로당 한 행씩 저장됩니다.

## 주요 필드

|필드|설명|
|---|---|
|walk_len_m|총 도보 거리|
|mean_abs|평균 절대경사|
|p95_abs|95백분위 절대경사|
|max_abs|최대 절대경사|
|over5_ratio|5% 초과 비율|
|over8_ratio|8% 초과 비율|
|origin_mean|출발 접근 평균 경사|
|transfer_mean|환승 평균 경사|
|dest_mean|도착 접근 평균 경사|

예를 들어

```
over5_ratio = 0.32
```

는 전체 도보 거리의 약 **32%가 절대경사 5%를 초과**한다는 의미입니다.

---

# 새로운 경로 분석하기

1. QGIS를 종료합니다.

2. ODsay 서버를 실행합니다.

```powershell
cd ODsay

node --env-file=.env server.mjs
```

3. 브라우저에서

```
http://localhost:8080
```

접속합니다.

4. 출발지와 목적지를 검색합니다.

5. 원하는 장소를 선택합니다.

6. **현재 장소로 QGIS 경사도 분석** 버튼을 클릭합니다.

7. 분석이 완료되면 QGIS 프로젝트를 다시 엽니다.

새 분석이 완료되면

- GeoPackage가 최신 결과로 교체
- 기존 경로 그룹 제거
- 최신 경로 그룹 생성
- 첫 번째 경로만 기본 표시

가 자동으로 수행됩니다.

---

# AI 점수화 활용 예시

단일 최대 경사만 사용하는 것보다 여러 지표를 함께 사용하는 것을 권장합니다.

사용 가능한 주요 Feature

- walk_len_m
- mean_abs
- p95_abs
- over5_ratio
- over8_ratio
- origin_mean
- transfer_mean
- dest_mean
- geom_quality

예시

### 휠체어 사용자

- over8_ratio 높은 패널티
- transfer_mean 높은 패널티

### 고령자

- walk_len_m
- mean_abs
- max_abs

함께 고려

### 폭염 취약자

향후

- 그늘
- 무더위 쉼터
- 스마트 버스쉘터

등과 함께 사용할 예정입니다.

---

# 한계점

현재 프로젝트는 **약 90m 해상도의 DEM**을 사용합니다.

따라서 아래 항목은 직접 표현하지 못할 수 있습니다.

- 계단
- 보도 턱
- 지하도
- 육교
- 건물 내부
- 지하철 역사 내부
- 짧은 급경사

즉, 현재 결과는 **실측 경사가 아니라 지형 기반 추정 경사**입니다.

또한

```
interval_m = 10
```

은 계산 간격일 뿐 DEM의 실제 해상도가 10m라는 의미는 아닙니다.

---

# 향후 개발 계획

- 고해상도 DEM 적용
- 건물 기반 예상 그늘 분석
- 쉼터·AED·스마트 버스쉘터 접근성 결합
- 보도·횡단보도·계단 데이터 적용
- 사용자 프로필 기반 점수 함수 개발

---

# 데이터 출처와 파생 관계

| 데이터 | 제공기관/서비스 | 출처 |
|---|---|---|
| 대중교통 추천 경로, 대중교통 형상, 도보 궤적 | 아로정보기술 ODsay API | [ODsay LAB](https://lab.odsay.com/) · [API 가이드](https://lab.odsay.com/guide/guide) |
| 부산 DEM 원자료 | 국토교통부 국토지리정보원 공개 DEM | [공공데이터포털 DEM](https://www.data.go.kr/tcs/dss/selectFileDataDetailView.do?publicDataPk=15059920) · [국토정보플랫폼](http://map.ngii.go.kr/ms/map/NlipMap.do?tabGb=total) |
| QGIS 배경지도 | OpenStreetMap contributors | [OpenStreetMap](https://www.openstreetmap.org/) · [저작권 및 표시 기준](https://www.openstreetmap.org/copyright) |

## 프로젝트 파일의 파생 관계

```text
국토지리정보원 공개 DEM 원본 타일
→ 부산 영역 모자이크 및 잘라내기
→ 02_processed/dem/busan_dem_clipped_90m.tif

ODsay 대중교통·도보 API 응답
+ busan_dem_clipped_90m.tif
→ scripts/odsay_walking_slope_analysis.py
→ 04_output/current_odsay_analysis.gpkg
→ qgis_project/busan_slope.qgz
```

`current_odsay_analysis.gpkg`는 원본 공공데이터가 아니라 현재 선택한 출발지·목적지와 호출 시점의 ODsay 결과를 DEM과 결합해 만든 파생 분석 결과입니다.

현재 저장소에는 시스템 운용에 필요한 잘라낸 DEM만 포함합니다. 원본 DEM 타일과 중간 모자이크는 과거 실험자료 정리 과정에서 제거했으므로, DEM 제작 과정을 처음부터 재현하려면 국토정보플랫폼에서 원자료를 다시 받아야 합니다.

## 이용 및 표시 주의사항

- ODsay API의 이용약관, 호출 한도와 표시 의무를 확인합니다.
- OpenStreetMap을 배경지도로 사용할 때는 기여자 표시와 저작권 고지를 유지합니다.
- 국토지리정보원 DEM의 이용조건은 원 제공 페이지를 확인합니다.
- 90m DEM 기반 경사는 실제 보도·계단·경사로의 측량값이 아니라 주변 지형을 이용한 추정값입니다.
- 분석 결과를 외부에 전달할 때 원본 출처, DEM 해상도, 분석 시각, 출발지·목적지와 전처리 사실을 함께 기록합니다.
