"""
ODsay 대중교통 경로 수집기 (메인 소스).

ODsay Lab API로 대중교통 경로 후보를 수집한다.
버스·지하철 환승 정보, 정류장 좌표를 세그먼트 단위로 제공.
API 키 미설정 시 플레이스홀더 반환.

API 문서: https://lab.odsay.com/guide/service
"""
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

        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get(self.BASE_URL, params={
                    "SX": origin.lng, "SY": origin.lat,
                    "EX": destination.lng, "EY": destination.lat,
                    "apiKey": settings.ODSAY_API_KEY,
                }, timeout=10.0)
            data = resp.json()

            candidates = []
            for path in data.get("result", {}).get("path", [])[:3]:
                coords = []
                for sub in path.get("subPath", []):
                    for st in sub.get("passStopList", {}).get("stations", []):
                        coords.append(Coordinate(lat=float(st["y"]), lng=float(st["x"])))
                if not coords:
                    coords = [origin, destination]
                candidates.append(RouteCandidate(
                    source=self.source_name, path=coords,
                    duration_min=path.get("info", {}).get("totalTime", 0),
                    distance_m=path.get("info", {}).get("totalDistance", 0),
                    raw_response=path,
                ))
            return candidates
        except Exception:
            return []
