"""VWorld 공공 건축물정보 WFS에서 footprint와 높이를 함께 조회한다."""
from __future__ import annotations

import math
from typing import Any

import httpx

from ..models import RouteCandidate
from ..settings import settings

VWORLD_DATA_URL = "https://api.vworld.kr/req/data"
VWORLD_LAYER = "LT_C_BLDGINFO"
QUERY_BUFFER_M = 250.0
PAGE_SIZE = 1000
MAX_FEATURES = 10_000


def _route_bbox(routes: list[RouteCandidate]) -> tuple[float, float, float, float]:
    points = [
        point
        for route in routes
        for point in (route.path or [])
    ]
    if not points:
        raise RuntimeError("건물 조회에 필요한 경로 geometry가 없습니다.")
    mean_lat = sum(point.lat for point in points) / len(points)
    lat_buffer = QUERY_BUFFER_M / 110_540
    lng_buffer = QUERY_BUFFER_M / (
        111_320 * math.cos(math.radians(mean_lat))
    )
    return (
        min(point.lng for point in points) - lng_buffer,
        min(point.lat for point in points) - lat_buffer,
        max(point.lng for point in points) + lng_buffer,
        max(point.lat for point in points) + lat_buffer,
    )


def _feature_collection(payload: dict[str, Any]) -> tuple[list[dict], int]:
    response = payload.get("response", payload)
    status = response.get("status")
    if isinstance(status, str) and status not in {"OK", "NOT_FOUND"}:
        error = response.get("error") or {}
        message = error.get("text") or error.get("message") or "VWorld building request failed."
        safe_message = str(message)
        if settings.vworld_api_key:
            safe_message = safe_message.replace(settings.vworld_api_key, "[REDACTED]")
        raise RuntimeError(safe_message)
    if status == "NOT_FOUND":
        return [], 0
    result = response.get("result") or {}
    collection = result.get("featureCollection") or result
    features = collection.get("features") if isinstance(collection, dict) else None
    if features is None and isinstance(payload.get("features"), list):
        features = payload["features"]
    if not isinstance(features, list):
        raise RuntimeError("VWorld 건물 응답의 GeoJSON features를 확인할 수 없습니다.")
    record = response.get("record") or {}
    try:
        total = int(record.get("total", len(features)))
    except (TypeError, ValueError):
        total = len(features)
    return features, total


def _polygon_parts(geometry: dict | None) -> list[dict[str, list]]:
    if not geometry:
        return []
    coordinates = geometry.get("coordinates")
    if geometry.get("type") == "Polygon" and isinstance(coordinates, list):
        return (
            [{"outer": coordinates[0], "holes": coordinates[1:]}]
            if coordinates else []
        )
    if geometry.get("type") == "MultiPolygon" and isinstance(coordinates, list):
        return [
            {"outer": polygon[0], "holes": polygon[1:]}
            for polygon in coordinates
            if isinstance(polygon, list) and polygon
        ]
    return []


def _validated_ring(ring: list) -> list[dict[str, float]]:
    try:
        points = [
            {"lng": float(point[0]), "lat": float(point[1])}
            for point in ring
            if isinstance(point, list) and len(point) >= 2
        ]
    except (TypeError, ValueError) as exc:
        raise RuntimeError("VWorld 건물 geometry 좌표가 숫자가 아닙니다.") from exc
    if len(points) < 4:
        return []
    if any(
        not math.isfinite(point["lng"])
        or not math.isfinite(point["lat"])
        or not -180 <= point["lng"] <= 180
        or not -90 <= point["lat"] <= 90
        for point in points
    ):
        raise RuntimeError("VWorld 건물 geometry 좌표 범위가 올바르지 않습니다.")
    if points[0] != points[-1]:
        raise RuntimeError("VWorld 건물 footprint가 폐합되지 않았습니다.")
    return points


def _building_rows(features: list[dict]) -> list[dict]:
    buildings: list[dict] = []
    for feature_index, feature in enumerate(features):
        properties = feature.get("properties") or {}
        raw_height = properties.get("height")
        try:
            height = float(raw_height) if raw_height not in (None, "") else None
        except (TypeError, ValueError):
            height = None
        if height is not None and (not math.isfinite(height) or height <= 0):
            height = None
        building_id = (
            properties.get("ufid")
            or properties.get("bldrgst_pk")
            or properties.get("bd_mgt_sn")
            or feature.get("id")
            or f"feature-{feature_index}"
        )
        for part, polygon in enumerate(_polygon_parts(feature.get("geometry"))):
            footprint = _validated_ring(polygon["outer"])
            if len(footprint) < 4:
                continue
            holes = [
                validated
                for ring in polygon["holes"]
                if len(validated := _validated_ring(ring)) >= 4
            ]
            buildings.append({
                "id": f"{building_id}-{part}",
                "buildingId": str(building_id),
                "heightM": height,
                "footprint": footprint,
                "holes": holes,
            })
    return buildings


async def get_vworld_buildings(
    routes: list[RouteCandidate],
    *,
    transport: httpx.AsyncBaseTransport | None = None,
) -> dict:
    if not settings.vworld_api_key:
        raise RuntimeError("BUILDING_SOURCE=vworld requires VWORLD_API_KEY.")
    min_lng, min_lat, max_lng, max_lat = _route_bbox(routes)
    base_params = {
        "service": "data",
        "version": "2.0",
        "request": "GetFeature",
        "key": settings.vworld_api_key,
        "format": "json",
        "errorFormat": "json",
        "size": PAGE_SIZE,
        "data": VWORLD_LAYER,
        "geomFilter": f"BOX({min_lng},{min_lat},{max_lng},{max_lat})",
        "columns": "ufid,height,bldrgst_pk,pnu,bd_mgt_sn",
        "geometry": "true",
        "attribute": "true",
        "crs": "EPSG:4326",
    }
    if settings.vworld_api_domain:
        base_params["domain"] = settings.vworld_api_domain

    all_features: list[dict] = []
    page = 1
    total = 0
    try:
        async with httpx.AsyncClient(
            timeout=settings.request_timeout * 3,
            transport=transport,
        ) as client:
            while True:
                response = await client.get(
                    VWORLD_DATA_URL,
                    params={**base_params, "page": page},
                )
                response.raise_for_status()
                try:
                    features, total = _feature_collection(response.json())
                except ValueError as exc:
                    raise RuntimeError("VWorld 건물 응답이 JSON이 아닙니다.") from exc
                if total > MAX_FEATURES:
                    raise RuntimeError(
                        f"경로 주변 건물이 {total}건으로 안전 조회 한도 "
                        f"{MAX_FEATURES}건을 초과했습니다."
                    )
                all_features.extend(features)
                if not features or len(all_features) >= total:
                    break
                page += 1
    except httpx.HTTPStatusError as exc:
        raise RuntimeError(
            f"VWorld 건물 API가 HTTP {exc.response.status_code}를 반환했습니다."
        ) from exc
    except httpx.HTTPError as exc:
        raise RuntimeError("VWorld 건물 API 연결에 실패했습니다.") from exc

    buildings = _building_rows(all_features)
    if not buildings:
        raise RuntimeError("VWorld에서 경로 주변 건물 footprint를 찾지 못했습니다.")
    return {
        "schemaVersion": 1,
        "source": "VWorld LT_C_BLDGINFO WFS",
        "dataQuality": "public",
        "queryBufferM": QUERY_BUFFER_M,
        "featureCount": len(all_features),
        "buildings": buildings,
    }
