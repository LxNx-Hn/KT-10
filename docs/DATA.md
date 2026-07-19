# 데이터셋 (`data/ai/`)

프론트엔드와 백엔드가 **공유하는 단일 소스**. 검증된 앱 입력은 `data/ai/`에,
원시·공간분석 데이터는 `data/da/`에 분리한다. 부산진구 데모 데이터는 camelCase JSON 으로 보관한다.
- 프론트엔드: `@data` 별칭으로 import (`frontend/src/data/*.ts`)
- 백엔드: `app/data/_loader.py` 가 저장소 루트 `data/` 에서 로드

> **미확인(tristate)** 값은 `null` 이 아니라 **키 자체를 생략**한다 →
> 프론트엔드 `undefined`, 백엔드 `None` 으로 동일하게 "정보 없음"을 의미한다.
> (`isLowFloorBus`, `hasElevator` 등)

## 파일

### `places.json` — 장소
```jsonc
[{ "id": "seomyeon-stn", "name": "서면역", "lat": 35.1578, "lng": 129.0594,
   "category": "지하철역", "address": "부산진구 중앙대로 지하" }]
```

### `weather.json` — 날씨 시나리오 (키: normal/heatwave/coldwave/rain/dust)
```jsonc
{ "heatwave": { "label": "폭염", "tempC": 36, "feelsLikeC": 39, "precipitationMm": 0,
   "isHeatwave": true, "isColdwave": false, "windMs": 1, "pm10": 55,
   "sky": "clear", "air": "moderate" } }
```

### `bus_arrivals.json` — 정류장 도착 (키: stopId)
```jsonc
{ "stop-gu-office": { "stopId": "stop-gu-office", "stopName": "부산진구청 정류장",
   "arrivals": [{ "routeName": "81", "arrivalMin": 5, "isLowFloor": true, "remainingStops": 3 },
                { "routeName": "54", "arrivalMin": 9, "remainingStops": 6 }] } }
//                                  ↑ isLowFloor 생략 = 미확인
```

### `routes.demo.json` — 대표 경로 후보(부산진구청→서면역, 4개)
점수 검증의 기준이 되는 수동 검증 경로. `segments[]` 에 접근성 속성(계단/승강기/저상/경사/횡단/사고위험)을 부여.
```jsonc
[{ "id": "r2-subway", "summary": "지하철 1호선(승강기)", "origin": "부산진구청", "destination": "서면역",
   "segments": [ { "id": "r2-sub", "mode": "subway", "description": "1호선 부전→서면 (승강기 이용)",
     "durationMin": 4, "waitMin": 3, "stationName": "부전역·서면역",
     "hasElevator": true, "needsVerticalMove": true } ],
   "totalDurationMin": 14, "totalWalkM": 450, "transferCount": 0, "path": [ ... ] }]
```

## 갱신
`data/ai/*.json` 만 수정하면 프론트·백엔드 양쪽에 즉시 반영된다.
대표 경로를 바꾸면 점수 검증 표(프론트 `validation.test.ts`, 백엔드 `test_scoring_validation.py`)의
기대값도 함께 갱신해야 한다.

## 실데이터 전환
임의 OD 경로 합성, 실시간 장소검색/날씨는 코드의 프로바이더/어댑터(키 기반)가 담당한다.
`data/` 는 데모 고정 데이터 + 검증 기준으로 유지한다.
