"""로컬 OSM에서 명시적으로 확인된 `steps + ramp=no` 휠체어 차단 검증."""
from __future__ import annotations

import json
from functools import lru_cache
from math import isfinite
from pathlib import Path

from pyproj import Transformer
from shapely.geometry import LineString
from shapely.ops import transform

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CATALOG = (
    ROOT / "data" / "raw" / "busan_osm_steps_ramp_no_20260724.geojson"
)
CATALOG_SCHEMA_VERSION = "busan-osm-unramped-steps-v1"
MAX_ROUTE_DISTANCE_M = 1.0
_TO_METRIC = Transformer.from_crs("EPSG:4326", "EPSG:5186", always_xy=True)


def _metric_line(raw_coordinates: object) -> LineString:
    if not isinstance(raw_coordinates, list) or len(raw_coordinates) < 2:
        raise ValueError("계단 차단 선형 좌표가 부족합니다.")
    coordinates: list[tuple[float, float]] = []
    for value in raw_coordinates:
        if not isinstance(value, (list, tuple)) or len(value) < 2:
            raise ValueError("계단 차단 좌표 계약이 올바르지 않습니다.")
        lng, lat = value[0], value[1]
        if (
            isinstance(lng, bool)
            or isinstance(lat, bool)
            or not isinstance(lng, (int, float))
            or not isinstance(lat, (int, float))
            or not isfinite(float(lng))
            or not isfinite(float(lat))
            or not 128.7 <= float(lng) <= 129.4
            or not 34.8 <= float(lat) <= 35.5
        ):
            raise ValueError("계단 차단 좌표가 부산 유효 범위를 벗어났습니다.")
        coordinates.append((float(lng), float(lat)))
    return transform(_TO_METRIC.transform, LineString(coordinates))


@lru_cache(maxsize=4)
def _load_catalog(path_value: str) -> tuple[tuple[int, LineString], ...]:
    path = Path(path_value)
    if not path.is_file():
        return ()
    payload = json.loads(path.read_text(encoding="utf-8"))
    if (
        payload.get("schemaVersion") != CATALOG_SCHEMA_VERSION
        or payload.get("type") != "FeatureCollection"
        or not isinstance(payload.get("features"), list)
    ):
        raise ValueError("계단 차단 카탈로그 계약이 올바르지 않습니다.")
    blockers: list[tuple[int, LineString]] = []
    for feature in payload["features"]:
        if not isinstance(feature, dict):
            raise ValueError("계단 차단 feature가 객체가 아닙니다.")
        properties = feature.get("properties")
        geometry = feature.get("geometry")
        if (
            not isinstance(properties, dict)
            or properties.get("highway") != "steps"
            or properties.get("ramp") != "no"
            or not isinstance(properties.get("osmWayId"), int)
            or not isinstance(geometry, dict)
            or geometry.get("type") != "LineString"
        ):
            raise ValueError("계단 차단 feature 근거가 명시적 steps+ramp=no가 아닙니다.")
        blockers.append((
            properties["osmWayId"],
            _metric_line(geometry.get("coordinates")),
        ))
    return tuple(blockers)


def explicit_unramped_step_ids(
    route_parts: list[list],
    *,
    catalog_path: Path = DEFAULT_CATALOG,
) -> list[int]:
    """확인된 계단 선형을 실제 보행 경로가 통과할 때만 OSM way ID를 반환한다."""
    blockers = _load_catalog(str(catalog_path.resolve()))
    if not blockers:
        return []
    matched: set[int] = set()
    for part in route_parts:
        if not isinstance(part, list) or len(part) < 2:
            continue
        route_coordinates = []
        for point in part:
            if hasattr(point, "lng") and hasattr(point, "lat"):
                route_coordinates.append([point.lng, point.lat])
            elif isinstance(point, (list, tuple)) and len(point) >= 2:
                # 분석 part의 내부 계약은 (lat, lng) 순서다.
                route_coordinates.append([point[1], point[0]])
            else:
                raise ValueError("휠체어 경로 분석 좌표 계약이 올바르지 않습니다.")
        route = _metric_line(route_coordinates)
        for osm_way_id, blocker in blockers:
            if route.distance(blocker) <= MAX_ROUTE_DISTANCE_M:
                matched.add(osm_way_id)
    return sorted(matched)
