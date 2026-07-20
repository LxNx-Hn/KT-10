"""
TMAP 보행자 길찾기 수집기 (보조 소스).

보행자 특화 경로, 계단/엘리베이터 속성 세그먼트 단위 제공.
facilityType 필드: 계단/엘리베이터/에스컬레이터 직접 파악 가능.
키가 없거나 응답이 불완전하면 가짜 직선 경로를 만들지 않는다.
"""
import httpx

from collectors.base import BaseRouteCollector, CollectorError, CollectorNotConfigured, RouteCandidate, Coordinate
from config import settings


class TmapRouteCollector(BaseRouteCollector):
    source_name = "tmap"
    BASE_URL = "https://apis.openapi.sk.com/tmap/routes/pedestrian"

    async def collect(self, origin: Coordinate, destination: Coordinate) -> list:
        if not settings.TMAP_API_KEY or settings.TMAP_API_KEY.startswith("YOUR_"):
            raise CollectorNotConfigured("TMAP_API_KEY가 설정되지 않았습니다.")

        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post(self.BASE_URL, json={
                    "startX": origin.lng, "startY": origin.lat,
                    "endX": destination.lng, "endY": destination.lat,
                    "startName": "출발지", "endName": "도착지",
                }, headers={"appKey": settings.TMAP_API_KEY}, timeout=10.0)
            resp.raise_for_status()
            data = resp.json()

            coords = []
            for feat in data.get("features", []):
                geom = feat.get("geometry", {})
                if geom.get("type") == "LineString":
                    for lng, lat in geom.get("coordinates", []):
                        coords.append(Coordinate(lat=lat, lng=lng))

            if not coords:
                return []

            props = next(
                (feature.get("properties", {}) for feature in data.get("features", [])
                 if feature.get("properties", {}).get("totalTime") is not None),
                {},
            )
            duration = float(props.get("totalTime") or 0) / 60
            distance = float(props.get("totalDistance") or 0)
            if duration <= 0 or distance <= 0:
                raise CollectorError("TMAP 응답에 유효한 시간 또는 거리가 없습니다.")
            return [RouteCandidate(
                source=self.source_name, path=coords,
                duration_min=duration,
                distance_m=distance,
                raw_response=data,
            )]
        except CollectorError:
            raise
        except (httpx.HTTPError, ValueError, TypeError) as exc:
            raise CollectorError(f"TMAP 호출 또는 응답 처리 실패: {type(exc).__name__}") from exc
