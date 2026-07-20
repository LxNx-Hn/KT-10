"""
ODsay 대중교통 경로 수집기 (메인 소스).

ODsay Lab API(searchPubTransPathT)로 대중교통 경로 후보를 최대 3개 수집한다.
버스·지하철 환승 정보, 정류장 좌표를 세그먼트 단위로 제공.
API 키 미설정 시 플레이스홀더 반환.

주의:
  - apiKey는 URL 인코딩 후 쿼리 파라미터로 전달 (+, /, = 등 특수문자 대비)
  - SX=경도(lng), SY=위도(lat) 순서 (우리 내부 Coordinate는 lat, lng 순서라 반대)
  - trafficType: 1=지하철, 2=버스, 3=도보
  - 저상버스: lane[].type == 11 또는 busNo에 "저상" 포함

API 문서: https://lab.odsay.com/guide/releaseReference#searchPubTransPathT
"""
from urllib.parse import quote

import httpx

from collectors.base import BaseRouteCollector, RouteCandidate, Coordinate
from config import settings


class OdsayRouteCollector(BaseRouteCollector):
    source_name = "odsay"
    BASE_URL = "https://api.odsay.com/v1/api/searchPubTransPathT"

    async def collect(self, origin: Coordinate, destination: Coordinate) -> list:
        if not settings.ODSAY_API_KEY or settings.ODSAY_API_KEY.startswith("YOUR_"):
            return [RouteCandidate(
                source=self.source_name,
                path=[origin, destination],
                duration_min=0, distance_m=0,
                raw_response={"note": "ODSAY_API_KEY not configured — placeholder"},
            )]

        encoded_key = quote(settings.ODSAY_API_KEY, safe="")
        url = (
            f"{self.BASE_URL}"
            f"?SX={origin.lng}&SY={origin.lat}"
            f"&EX={destination.lng}&EY={destination.lat}"
            f"&OPT=0&SearchType=0&SearchPathType=0"
            f"&apiKey={encoded_key}"
        )

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(url)

            if resp.status_code != 200:
                print(f"[ODsay] HTTP {resp.status_code}")
                return []

            data = resp.json()

            if "error" in data:
                error = data["error"][0] if data["error"] else {}
                print(f"[ODsay] 에러 {error.get('code')}: {error.get('message')}")
                return []

            paths = data.get("result", {}).get("path", [])
            if not paths:
                return []

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
    """ODsay path 응답 하나를 RouteCandidate로 변환한다."""
    info = path_data.get("info", {})
    if not info:
        return None

    coords: list[Coordinate] = []
    for sub in path_data.get("subPath", []):
        for st in sub.get("passStopList", {}).get("stations", []):
            try:
                coords.append(Coordinate(lat=float(st["y"]), lng=float(st["x"])))
            except (KeyError, ValueError, TypeError):
                continue

    if not coords:
        coords = [origin, destination]

    return RouteCandidate(
        source="odsay",
        path=coords,
        duration_min=float(info.get("totalTime", 0)),
        distance_m=float(info.get("totalDistance", 0)),
        raw_response=path_data,
    )
