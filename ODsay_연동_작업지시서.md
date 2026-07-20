# Claude Code 작업지시서 — ODsay API 실제 연동

> 이 문서를 전부 읽고 작업 전 아래 파일들을 먼저 읽으세요.
> - `ai/collectors/odsay_collector.py` (현재 코드)
> - `ai/api/router.py` (파이프라인 전체 흐름)
> - `ai/.env` (ODSAY_API_KEY 확인)

---

## 0. 현재 상태 및 목표

**현재 문제**: `odsay_collector.py` 가 아래 오류를 반환하며 대중교통 경로를 전혀 수집하지 못하고 있음

```json
{"error": [{"code": "500", "message": "[ApiKeyAuthFailed] ApiKey authentication failed."}]}
```

**원인**: ODsay API 키는 쿼리 파라미터로 전달할 때 반드시 **URL 인코딩**이 필요함.
현재 코드가 raw 키를 그대로 넣고 있어 특수문자가 포함된 키에서 인증 실패 발생.

**목표**: ODsay `searchPubTransPathT` API가 실제로 응답을 반환하고,
응답에서 `transfer_count`, `walk_distance_m`, `is_low_floor_bus`, `elevator_ratio`
피처가 정확하게 파싱되도록 수정.

---

## 1. ODsay API 스펙 (가이드 기반)

**대중교통 길찾기 엔드포인트**

```
GET https://api.odsay.com/v1/api/searchPubTransPathT
```

**필수 파라미터**

| 파라미터 | 설명 |
|---|---|
| `apiKey` | 발급된 키 — **반드시 URL 인코딩 필요** |
| `SX` | 출발지 경도 (x좌표) |
| `SY` | 출발지 위도 (y좌표) |
| `EX` | 도착지 경도 (x좌표) |
| `EY` | 도착지 위도 (y좌표) |

**선택 파라미터**

| 파라미터 | 설명 | 기본값 |
|---|---|---|
| `OPT` | 경로 정렬방식 (0: 추천, 1: 타입별) | 0 |
| `SearchType` | 0: 도시내, 1: 도시간 | 0 |
| `SearchPathType` | 0: 모두, 1: 지하철, 2: 버스 | 0 |

**⚠️ 좌표 순서 주의**: ODsay는 `SX=경도, SY=위도` 순서. 우리 내부는 `(lat, lng)` 순서라 변환 필수.

**⚠️ URL 인코딩**: apiKey에 `+`, `/`, `=` 같은 특수문자 포함 시 반드시 URL 인코딩.
Python에서는 `urllib.parse.quote(api_key, safe='')` 사용.

---

## 2. ODsay 응답 구조 (파싱 대상)

```json
{
  "result": {
    "path": [
      {
        "pathType": 1,
        "info": {
          "totalTime": 25,
          "totalWalk": 350,
          "transferCount": 1,
          "busTransitCount": 1,
          "subwayTransitCount": 0,
          "totalDistance": 4200,
          "payment": 1400,
          "firstStartStation": "부산진구청",
          "lastEndStation": "서면역"
        },
        "subPath": [
          {
            "trafficType": 3,
            "distance": 180,
            "sectionTime": 3,
            "startName": "부산진구청 앞",
            "endName": "부산진구청역",
            "passStopList": {
              "stations": [
                {"index": 0, "stationName": "부산진구청 앞", "x": 129.053, "y": 35.162}
              ]
            }
          },
          {
            "trafficType": 2,
            "distance": 3800,
            "sectionTime": 18,
            "lane": [
              {
                "busNo": "167",
                "type": 11,
                "busID": 12345,
                "busLocalBlID": "BUS_167"
              }
            ],
            "passStopList": {
              "stations": [
                {"index": 0, "stationName": "부산진구청역", "x": 129.054, "y": 35.163},
                {"index": 1, "stationName": "서면역", "x": 129.059, "y": 35.158}
              ]
            }
          }
        ]
      }
    ],
    "searchType": 0,
    "subwayCount": 0,
    "busCount": 3
  }
}
```

**trafficType 코드**

| 값 | 의미 |
|---|---|
| 1 | 지하철 |
| 2 | 버스 |
| 3 | 도보 |

**busNo에서 저상버스 판단 방법**
- `lane[].type` 값이 `11`이면 저상버스 (ODsay 내부 코드)
- 또는 `lane[].busNo`에 "저상" 문자열 포함 여부로 보조 확인

---

## 3. 수정할 파일: `ai/collectors/odsay_collector.py`

현재 파일을 읽고 아래 내용으로 교체하세요. 기존 구조를 유지하면서 아래 사항을 반영합니다.

**수정 사항 4가지**

1. `apiKey` URL 인코딩 추가
2. 좌표 순서 수정 (`SX=경도`, `SY=위도`)
3. 응답 파싱 로직 완성 (`_parse_path()`)
4. 저상버스 판단 로직 완성

```python
"""
ODsay 대중교통 경로 수집기.

ODsay Lab API(searchPubTransPathT)를 사용하여
출발지-도착지 간 대중교통 경로 후보를 최대 3개 수집한다.

주의:
  - apiKey는 반드시 URL 인코딩 후 쿼리 파라미터로 전달
  - SX=경도(lng), SY=위도(lat) 순서 (우리 내부와 반대)
  - trafficType: 1=지하철, 2=버스, 3=도보
  - 저상버스: lane[].type == 11

API 문서: https://lab.odsay.com/guide/releaseReference#searchPubTransPathT
"""
from urllib.parse import quote
import httpx

from ai.collectors.base import BaseRouteCollector, RouteCandidate, Coordinate
from ai.config import settings

BASE_URL = "https://api.odsay.com/v1/api/searchPubTransPathT"


class OdsayRouteCollector(BaseRouteCollector):
    source_name = "odsay"

    async def collect(
        self, origin: Coordinate, destination: Coordinate
    ) -> list[RouteCandidate]:
        """
        ODsay API로 대중교통 경로 후보를 수집한다.

        API 키 미설정 시 플레이스홀더 반환.
        실패 시 빈 리스트 반환 (예외 전파 금지).
        """
        if not settings.ODSAY_API_KEY or settings.ODSAY_API_KEY.startswith("YOUR_"):
            return [RouteCandidate(
                source=self.source_name,
                path=[origin, destination],
                duration_min=0,
                distance_m=0,
                raw_response={"note": "ODSAY_API_KEY not configured — placeholder"},
            )]

        # apiKey URL 인코딩 (특수문자 +, /, = 처리)
        encoded_key = quote(settings.ODSAY_API_KEY, safe="")

        # SX=경도(lng), SY=위도(lat) — ODsay 좌표 순서
        url = (
            f"{BASE_URL}"
            f"?SX={origin.lng}&SY={origin.lat}"
            f"&EX={destination.lng}&EY={destination.lat}"
            f"&OPT=0&SearchType=0&SearchPathType=0"
            f"&apiKey={encoded_key}"
        )

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(url)

            if resp.status_code != 200:
                return []

            data = resp.json()

            # 에러 응답 처리
            if "error" in data:
                error_code = data["error"][0].get("code", "")
                error_msg  = data["error"][0].get("message", "")
                print(f"[ODsay] 에러 {error_code}: {error_msg}")
                return []

            # 결과 없음 처리 (error code -99)
            result = data.get("result", {})
            paths  = result.get("path", [])
            if not paths:
                return []

            # 경로 후보 최대 3개 파싱
            candidates = []
            for path_data in paths[:3]:
                candidate = _parse_path(path_data, origin, destination)
                if candidate:
                    candidates.append(candidate)

            return candidates

        except Exception as e:
            print(f"[ODsay] 수집 실패: {e}")
            return []


def _parse_path(
    path_data: dict,
    origin: Coordinate,
    destination: Coordinate,
) -> RouteCandidate | None:
    """
    ODsay path 응답 하나를 RouteCandidate로 변환한다.

    추출하는 피처:
      - 경로 좌표 시퀀스 (passStopList.stations)
      - duration_min (info.totalTime)
      - distance_m (info.totalDistance)
    """
    info     = path_data.get("info", {})
    sub_paths = path_data.get("subPath", [])

    if not info:
        return None

    # 경로 좌표 시퀀스 추출
    coords: list[Coordinate] = []
    for sub in sub_paths:
        stations = sub.get("passStopList", {}).get("stations", [])
        for st in stations:
            # ODsay 좌표: x=경도, y=위도
            try:
                coords.append(Coordinate(lat=float(st["y"]), lng=float(st["x"])))
            except (KeyError, ValueError, TypeError):
                continue

    # 좌표가 없으면 출발/도착만 사용
    if not coords:
        coords = [origin, destination]

    return RouteCandidate(
        source="odsay",
        path=coords,
        duration_min=float(info.get("totalTime", 0)),
        distance_m=float(info.get("totalDistance", 0)),
        raw_response=path_data,
    )
```

---

## 4. 수정할 파일: `ai/api/router.py` — `_parse_api_features()` 함수

기존 `_parse_api_features()` 함수를 아래 내용으로 교체하세요.
ODsay 실응답 구조 기반으로 피처 파싱 로직을 완성합니다.

```python
def _parse_api_features(candidate) -> dict:
    """
    ODsay raw_response에서 접근성 피처를 파싱한다.

    trafficType: 1=지하철, 2=버스, 3=도보
    저상버스 판단: lane[].type == 11 (ODsay 내부 코드)
    엘리베이터: 도보 구간(trafficType=3)에서 stairInfo.elevatorYN == 'Y'

    raw_response 없거나 플레이스홀더이면 기본값(0) 반환.
    """
    raw = candidate.raw_response or {}

    # 플레이스홀더인 경우 기본값 반환
    if "note" in raw:
        return _default_api_features(candidate.duration_min)

    info      = raw.get("info", {})
    sub_paths = raw.get("subPath", [])

    # info에서 직접 추출 가능한 피처
    transfer_count  = int(info.get("transferCount", 0))
    walk_distance_m = float(info.get("totalWalk", 0))

    # subPath 순회로 추출하는 피처
    stair_count       = 0
    is_low_floor      = 0
    elevator_segments = 0
    walk_segments     = 0

    for sub in sub_paths:
        traffic_type = sub.get("trafficType", 0)

        # 버스 구간: 저상버스 확인
        if traffic_type == 2:
            for lane in sub.get("lane", []):
                # type == 11: 저상버스 (ODsay 내부 코드)
                if lane.get("type") == 11:
                    is_low_floor = 1
                # 버스 이름에 "저상" 포함 여부로 보조 확인
                if "저상" in str(lane.get("busNo", "")):
                    is_low_floor = 1

        # 도보 구간: 계단/엘리베이터 확인
        if traffic_type == 3:
            walk_segments += 1
            stair_info = sub.get("stairInfo", {})
            if stair_info.get("stairYN") == "Y":
                stair_count += 1
            if stair_info.get("elevatorYN") == "Y":
                elevator_segments += 1

    # 엘리베이터 접근 가능 비율 (도보 구간 기준)
    elevator_ratio = (
        elevator_segments / walk_segments if walk_segments > 0 else 0.0
    )

    return {
        "avg_slope_percent": 0.0,   # TODO: DEM 데이터 연동 후 채움
        "max_slope_percent": 0.0,
        "min_slope_percent": 0.0,
        "slope_iqr":         0.0,
        "stair_count":       stair_count,
        "elevator_ratio":    round(elevator_ratio, 4),
        "transfer_count":    transfer_count,
        "walk_distance_m":   walk_distance_m,
        "total_duration_min": candidate.duration_min,
        "is_low_floor_bus":  is_low_floor,
    }


def _default_api_features(duration_min: float) -> dict:
    """raw_response가 없을 때 반환할 기본값."""
    return {
        "avg_slope_percent": 0.0,
        "max_slope_percent": 0.0,
        "min_slope_percent": 0.0,
        "slope_iqr":         0.0,
        "stair_count":       0,
        "elevator_ratio":    0.0,
        "transfer_count":    0,
        "walk_distance_m":   0.0,
        "total_duration_min": duration_min,
        "is_low_floor_bus":  0,
    }
```

---

## 5. 동작 검증 방법

### 5-1. 단독 테스트 스크립트 (ai/tests/test_odsay_live.py)

이 파일을 새로 만들고 실행해서 ODsay 실응답을 확인하세요.

```python
"""
ODsay API 라이브 테스트.
실행: python -m pytest ai/tests/test_odsay_live.py -v -s
"""
import asyncio
import pytest
from ai.collectors.odsay_collector import OdsayRouteCollector
from ai.collectors.base import Coordinate

# 부산진구청 → 서면역 (부산 테스트 좌표)
ORIGIN = Coordinate(lat=35.1626, lng=129.0530)
DEST   = Coordinate(lat=35.1578, lng=129.0594)


@pytest.mark.asyncio
async def test_odsay_returns_candidates():
    """ODsay가 경로 후보를 최소 1개 이상 반환해야 한다."""
    collector  = OdsayRouteCollector()
    candidates = await collector.collect(ORIGIN, DEST)

    print(f"\n수집된 경로 수: {len(candidates)}")
    for i, c in enumerate(candidates):
        print(f"  경로 {i+1}: {len(c.path)}개 좌표, {c.duration_min}분, {c.distance_m}m")
        info = c.raw_response.get("info", {})
        print(f"    환승: {info.get('transferCount', 0)}회")
        print(f"    도보: {info.get('totalWalk', 0)}m")

    assert len(candidates) > 0, "ODsay 응답이 비어있음 — API 키 또는 네트워크 확인"
    assert len(candidates[0].path) >= 2, "경로 좌표가 2개 미만"


@pytest.mark.asyncio
async def test_odsay_no_auth_error():
    """응답에 ApiKeyAuthFailed 오류가 없어야 한다."""
    collector = OdsayRouteCollector()
    candidates = await collector.collect(ORIGIN, DEST)

    # collector가 에러 시 빈 리스트 반환하므로
    # 빈 리스트라면 콘솔 로그에서 에러 메시지 확인 필요
    if not candidates:
        pytest.fail(
            "경로 수집 실패 — "
            "콘솔에서 [ODsay] 에러 메시지 확인 (ApiKeyAuthFailed 또는 네트워크 오류)"
        )


@pytest.mark.asyncio
async def test_parse_api_features():
    """raw_response에서 피처가 올바르게 파싱되는지 확인한다."""
    from ai.api.router import _parse_api_features
    from ai.collectors.base import RouteCandidate

    collector  = OdsayRouteCollector()
    candidates = await collector.collect(ORIGIN, DEST)

    if not candidates:
        pytest.skip("ODsay 응답 없음 — 피처 파싱 테스트 건너뜀")

    feats = _parse_api_features(candidates[0])

    print(f"\n파싱된 피처:")
    for k, v in feats.items():
        print(f"  {k}: {v}")

    assert "transfer_count" in feats
    assert "walk_distance_m" in feats
    assert "is_low_floor_bus" in feats
    assert "elevator_ratio" in feats
    assert isinstance(feats["transfer_count"], int)
    assert feats["walk_distance_m"] >= 0
    assert feats["is_low_floor_bus"] in (0, 1)
    assert 0.0 <= feats["elevator_ratio"] <= 1.0
```

### 5-2. 전체 파이프라인 테스트

테스트 통과 후 실제 경로 추천 엔드포인트로 확인

```bash
# AI 서버 실행
uvicorn ai.main:app --host 0.0.0.0 --port 8001 --reload

# 별도 터미널에서 curl
curl -X POST http://localhost:8001/recommend \
  -H "Content-Type: application/json" \
  -d '{
    "origin_lat": 35.1626,
    "origin_lng": 129.0530,
    "origin_name": "부산진구청",
    "dest_lat": 35.1578,
    "dest_lng": 129.0594,
    "dest_name": "서면역",
    "profile": "elderly",
    "weather": "normal",
    "prioritize_weather_safety": false
  }'
```

**확인해야 할 것**
- `metadata.sources_succeeded` 에 `"odsay"` 포함됨
- `routes[0].features.transfer_count` 가 0 이상의 정수
- `routes[0].features.walk_distance_m` 이 0 이상의 값
- `routes[0].path` 에 좌표가 2개 이상

---

## 6. 작업 순서

1. `ai/.env` 에서 `ODSAY_API_KEY` 값 확인
2. `ai/collectors/odsay_collector.py` 를 섹션 3 코드로 교체
3. `ai/api/router.py` 의 `_parse_api_features()` 함수를 섹션 4 코드로 교체 (기존 함수 완전 대체)
4. `ai/tests/test_odsay_live.py` 생성
5. `pytest ai/tests/test_odsay_live.py -v -s` 실행
6. 테스트 통과 확인 후 전체 서버 재실행, curl 테스트

---

## 7. 최종 확인 체크리스트

- [ ] `test_odsay_returns_candidates` 통과 (경로 1개 이상 반환)
- [ ] `test_odsay_no_auth_error` 통과 (ApiKeyAuthFailed 오류 없음)
- [ ] `test_parse_api_features` 통과 (transfer_count, walk_distance_m, is_low_floor_bus, elevator_ratio 파싱 완료)
- [ ] curl POST `/recommend` 응답에서 `metadata.sources_succeeded` 에 `"odsay"` 포함
- [ ] `routes[0].features.transfer_count` 가 정수 (0 이상)
- [ ] `routes[0].features.walk_distance_m` 이 0 이상
- [ ] 콘솔에 `[ODsay] 에러` 로그 없음
