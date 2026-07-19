"""
TMAP 보행자 길찾기 수집기 (보조 소스).

보행자 특화 경로, 계단/엘리베이터 속성 세그먼트 단위 제공.
facilityType 필드: 계단/엘리베이터/에스컬레이터 직접 파악 가능.
API 키 미설정 시 플레이스홀더 반환.
"""
import httpx

from collectors.base import BaseRouteCollector, RouteCandidate, Coordinate
from config import settings


class TmapRouteCollector(BaseRouteCollector):
    source_name = "tmap"
    BASE_URL = "https://apis.openapi.sk.com/tmap/routes/pedestrian"

    async def collect(self, origin: Coordinate, destination: Coordinate) -> list:
        if not settings.TMAP_API_KEY or settings.TMAP_API_KEY.startswith("YOUR_"):
            return [RouteCandidate(
                source=self.source_name,
                path=[origin, destination],
                duration_min=0, distance_m=0,
                raw_response={"note": "TMAP_API_KEY not configured — placeholder"},
            )]

        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post(self.BASE_URL, json={
                    "startX": origin.lng, "startY": origin.lat,
                    "endX": destination.lng, "endY": destination.lat,
                    "startName": "출발지", "endName": "도착지",
                }, headers={"appKey": settings.TMAP_API_KEY}, timeout=10.0)
            data = resp.json()

            coords = []
            for feat in data.get("features", []):
                geom = feat.get("geometry", {})
                if geom.get("type") == "LineString":
                    for lng, lat in geom.get("coordinates", []):
                        coords.append(Coordinate(lat=lat, lng=lng))

            if not coords:
                return []

            props = data.get("features", [{}])[0].get("properties", {})
            return [RouteCandidate(
                source=self.source_name, path=coords,
                duration_min=props.get("totalTime", 0) / 60,
                distance_m=props.get("totalDistance", 0),
                raw_response=data,
            )]
        except Exception:
            return []
