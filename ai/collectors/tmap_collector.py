"""
TMAP 보행자 길찾기 수집기 (보조 소스).

보행자 특화 경로, 계단/엘리베이터 속성 세그먼트 단위 제공.
facilityType 필드: 계단/엘리베이터/에스컬레이터 직접 파악 가능.
키가 없거나 응답이 불완전하면 가짜 직선 경로를 만들지 않는다.
"""
from math import isfinite

import httpx

from collectors.base import BaseRouteCollector, CollectorError, CollectorNotConfigured, RouteCandidate, Coordinate
from config import settings


class TmapRouteCollector(BaseRouteCollector):
    source_name = "tmap"
    BASE_URL = "https://apis.openapi.sk.com/tmap/routes/pedestrian"

    @staticmethod
    def _positive_number(value, field: str) -> float:
        if value is None or isinstance(value, bool):
            raise CollectorError(f"TMAP 응답의 {field}가 비어 있습니다.")
        try:
            number = float(value)
        except (TypeError, ValueError) as exc:
            raise CollectorError(
                f"TMAP 응답의 {field}가 숫자가 아닙니다."
            ) from exc
        if not isfinite(number) or number <= 0:
            raise CollectorError(
                f"TMAP 응답의 {field}는 유한한 양수여야 합니다."
            )
        return number

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
            if not isinstance(data, dict):
                raise CollectorError("TMAP 응답 본문이 JSON 객체가 아닙니다.")

            features = data.get("features")
            if not isinstance(features, list):
                raise CollectorError("TMAP 응답의 features가 배열이 아닙니다.")
            coords = []
            for feat in features:
                if not isinstance(feat, dict):
                    raise CollectorError(
                        "TMAP 응답의 feature가 객체가 아닙니다."
                    )
                geom = feat.get("geometry", {})
                if not isinstance(geom, dict):
                    raise CollectorError(
                        "TMAP 응답의 geometry가 객체가 아닙니다."
                    )
                properties = feat.get("properties", {})
                if not isinstance(properties, dict):
                    raise CollectorError(
                        "TMAP 응답의 properties가 객체가 아닙니다."
                    )
                if geom.get("type") == "LineString":
                    geometry_coords = geom.get("coordinates")
                    if not isinstance(geometry_coords, list):
                        raise CollectorError(
                            "TMAP LineString의 coordinates가 배열이 아닙니다."
                        )
                    for lng, lat in geometry_coords:
                        point = Coordinate(lat=float(lat), lng=float(lng))
                        if not (
                            isfinite(point.lat)
                            and isfinite(point.lng)
                            and 33 <= point.lat <= 39
                            and 124 <= point.lng <= 132
                        ):
                            raise CollectorError(
                                "TMAP 응답에 대한민국 범위를 벗어난 좌표가 있습니다."
                            )
                        if not coords or coords[-1] != point:
                            coords.append(point)

            if len(coords) < 2:
                raise CollectorError("TMAP 응답에 유효한 경로 좌표가 없습니다.")

            props = next(
                (
                    feature["properties"]
                    for feature in features
                    if feature.get("properties", {}).get("totalTime") is not None
                ),
                {},
            )
            duration = self._positive_number(
                props.get("totalTime"),
                "totalTime",
            ) / 60
            distance = self._positive_number(
                props.get("totalDistance"),
                "totalDistance",
            )
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
