"""검증용 건물 높이와 태양 위치를 이용한 경로 그늘 계산.

기본 입력은 ``data/ai/buildings.demo.json``의 합성 데이터이며
``BUILDING_SOURCE=vworld``에서는 VWorld 건축물정보 도형·높이를 사용한다.
결과 상태는 입력 품질에 따라 ``estimated_demo`` 또는
``estimated_public``으로 구분한다.
"""
from __future__ import annotations

from datetime import UTC, datetime
import math
from zoneinfo import ZoneInfo

from shapely import affinity
from shapely.geometry import LineString, Point, Polygon
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union

from .data._loader import load
from .models import LatLng, RouteCandidate, ShadePathSegment, ShadeSummary

KST = ZoneInfo("Asia/Seoul")
SAMPLE_INTERVAL_M = 10.0
DEMO_BUILDING_DATA = load("buildings.demo.json")


def solar_position(moment: datetime, lat: float, lng: float) -> tuple[float, float]:
    """NOAA 근사식으로 태양 방위각(북=0, 시계방향)과 고도각을 계산한다."""
    local = moment.replace(tzinfo=KST) if moment.tzinfo is None else moment.astimezone(KST)
    utc = local.astimezone(UTC)
    day = utc.timetuple().tm_yday
    fractional_hour = utc.hour + utc.minute / 60 + utc.second / 3600
    gamma = 2 * math.pi / 365 * (day - 1 + (fractional_hour - 12) / 24)
    equation_of_time = 229.18 * (
        0.000075
        + 0.001868 * math.cos(gamma)
        - 0.032077 * math.sin(gamma)
        - 0.014615 * math.cos(2 * gamma)
        - 0.040849 * math.sin(2 * gamma)
    )
    declination = (
        0.006918
        - 0.399912 * math.cos(gamma)
        + 0.070257 * math.sin(gamma)
        - 0.006758 * math.cos(2 * gamma)
        + 0.000907 * math.sin(2 * gamma)
        - 0.002697 * math.cos(3 * gamma)
        + 0.00148 * math.sin(3 * gamma)
    )
    true_solar_minutes = (
        local.hour * 60
        + local.minute
        + local.second / 60
        + equation_of_time
        + 4 * lng
        - 60 * 9
    ) % 1440
    hour_angle_deg = true_solar_minutes / 4 - 180
    hour_angle = math.radians(hour_angle_deg)
    latitude = math.radians(lat)
    cos_zenith = (
        math.sin(latitude) * math.sin(declination)
        + math.cos(latitude) * math.cos(declination) * math.cos(hour_angle)
    )
    zenith = math.acos(max(-1.0, min(1.0, cos_zenith)))
    elevation = 90 - math.degrees(zenith)
    azimuth = math.degrees(
        math.atan2(
            math.sin(hour_angle),
            math.cos(hour_angle) * math.sin(latitude)
            - math.tan(declination) * math.cos(latitude),
        )
    )
    return (azimuth + 180) % 360, elevation


def _project(point: LatLng, ref_lat: float, ref_lng: float) -> tuple[float, float]:
    return (
        (point.lng - ref_lng) * 111_320 * math.cos(math.radians(ref_lat)),
        (point.lat - ref_lat) * 110_540,
    )


def _unproject(x: float, y: float, ref_lat: float, ref_lng: float) -> LatLng:
    return LatLng(
        lat=ref_lat + y / 110_540,
        lng=ref_lng + x / (111_320 * math.cos(math.radians(ref_lat))),
    )


def _distance(left: tuple[float, float], right: tuple[float, float]) -> float:
    return math.hypot(right[0] - left[0], right[1] - left[1])


def _walking_paths(
    route: RouteCandidate,
    *,
    demo: bool,
) -> tuple[list[list[LatLng]], float | None, str | None]:
    """실데이터는 실외 도보 구간만 사용하고, 전체 대중교통 선을 대신 쓰지 않는다."""
    if demo:
        return (
            [route.path] if route.path and len(route.path) >= 2 else [],
            route.total_walk_m,
            route.geometry_quality,
        )

    relevant = [
        segment
        for segment in route.segments
        if (
            (segment.mode == "walk" and segment.outdoor is not False)
            or (segment.mode == "transfer" and segment.outdoor is True)
        )
    ]
    if not relevant:
        return [], None, None
    if any(not segment.path or len(segment.path) < 2 for segment in relevant):
        route_is_entirely_outdoor_walking = all(
            (
                segment.mode == "walk" and segment.outdoor is not False
            ) or (
                segment.mode == "transfer" and segment.outdoor is True
            )
            for segment in route.segments
        )
        if (
            route_is_entirely_outdoor_walking
            and route.path
            and len(route.path) >= 2
            and all(segment.distance_m is not None for segment in relevant)
        ):
            return (
                [route.path],
                sum(float(segment.distance_m) for segment in relevant),
                route.geometry_quality,
            )
        return [], None, None
    if any(segment.distance_m is None for segment in relevant):
        return [], None, None
    qualities = [segment.geometry_quality for segment in relevant]
    quality: str | None
    if qualities and all(value == "exact" for value in qualities):
        quality = "exact"
    elif any(value == "estimated" for value in qualities):
        quality = "estimated"
    else:
        quality = "mixed"
    return (
        [segment.path for segment in relevant if segment.path],
        sum(float(segment.distance_m) for segment in relevant if segment.distance_m is not None),
        quality,
    )


def _swept_shadow(polygon: Polygon, shift: tuple[float, float]) -> BaseGeometry:
    """수직 건물을 태양 반대 방향으로 밀어 만든 정확한 평면 스윕 영역."""
    shifted = affinity.translate(polygon, xoff=shift[0], yoff=shift[1])
    pieces: list[BaseGeometry] = [polygon, shifted]
    for ring in [polygon.exterior, *polygon.interiors]:
        coordinates = list(ring.coords)
        for left, right in zip(coordinates, coordinates[1:]):
            pieces.append(Polygon([
                left,
                right,
                (right[0] + shift[0], right[1] + shift[1]),
                (left[0] + shift[0], left[1] + shift[1]),
                left,
            ]))
    return unary_union(pieces)


def _shadow_polygons(
    azimuth_deg: float,
    elevation_deg: float,
    ref_lat: float,
    ref_lng: float,
    building_data: dict,
) -> tuple[BaseGeometry, int, int]:
    shadow_azimuth = math.radians((azimuth_deg + 180) % 360)
    shadows: list[BaseGeometry] = []
    building_ids: set[str] = set()
    known_height_ids: set[str] = set()
    for building in building_data["buildings"]:
        building_id = str(building.get("buildingId") or building.get("id"))
        building_ids.add(building_id)
        raw_height = building.get("heightM")
        try:
            height = float(raw_height) if raw_height is not None else None
        except (TypeError, ValueError):
            height = None
        if height is None or not math.isfinite(height) or height <= 0:
            continue
        footprint = [
            _project(LatLng.model_validate(point), ref_lat, ref_lng)
            for point in building["footprint"]
        ]
        holes = [
            [
                _project(LatLng.model_validate(point), ref_lat, ref_lng)
                for point in ring
            ]
            for ring in building.get("holes") or []
        ]
        polygon = Polygon(footprint, holes)
        if polygon.is_empty or not polygon.is_valid or polygon.area <= 0:
            continue
        known_height_ids.add(building_id)
        shadow_length = height / math.tan(math.radians(elevation_deg))
        shift = (
            math.sin(shadow_azimuth) * shadow_length,
            math.cos(shadow_azimuth) * shadow_length,
        )
        shadows.append(_swept_shadow(polygon, shift))
    geometry = unary_union(shadows) if shadows else Polygon()
    return geometry, len(known_height_ids), len(building_ids)


def _display_polygons(geometry: BaseGeometry) -> list[list[tuple[float, float]]]:
    if geometry.is_empty:
        return []
    polygons = [geometry] if geometry.geom_type == "Polygon" else list(geometry.geoms)
    return [
        [(float(x), float(y)) for x, y in polygon.exterior.coords]
        for polygon in polygons
        if polygon.geom_type == "Polygon" and not polygon.is_empty
    ]


def calculate_shade(
    route: RouteCandidate,
    departure_at: datetime | None,
    building_data: dict,
) -> ShadeSummary:
    evaluated_at = departure_at or datetime.now(KST)
    if evaluated_at.tzinfo is None:
        evaluated_at = evaluated_at.replace(tzinfo=KST)
    else:
        evaluated_at = evaluated_at.astimezone(KST)
    source = str(building_data["source"])
    data_quality = str(building_data.get("dataQuality") or "demo")
    is_demo = data_quality == "demo"
    walking_paths, analyzed_walk_m, walking_quality = _walking_paths(
        route, demo=is_demo
    )
    estimated_status = (
        "estimated_public" if data_quality == "public" else "estimated_demo"
    )
    if not walking_paths:
        return ShadeSummary(
            status="unavailable",
            evaluated_at=evaluated_at,
            source=source,
            data_quality=data_quality,
            walking_geometry_quality=walking_quality,
            calculation_note=(
                "실외 도보 구간의 거리와 geometry가 모두 확인되지 않아 "
                "그늘 비율을 계산하지 않았습니다."
            ),
        )
    path = [point for walking_path in walking_paths for point in walking_path]
    ref_lat = sum(point.lat for point in path) / len(path)
    ref_lng = sum(point.lng for point in path) / len(path)
    azimuth, elevation = solar_position(evaluated_at, ref_lat, ref_lng)
    if elevation <= 0:
        return ShadeSummary(
            status="not_daylight",
            evaluated_at=evaluated_at,
            solar_azimuth_deg=round(azimuth, 2),
            solar_elevation_deg=round(elevation, 2),
            source=source,
            data_quality=data_quality,
            walking_geometry_quality=walking_quality,
            calculation_note="태양이 지평선 아래에 있어 주간 건물 그림자를 계산하지 않았습니다.",
        )

    projected_paths = [
        [_project(point, ref_lat, ref_lng) for point in walking_path]
        for walking_path in walking_paths
    ]
    shadow_geometry, known_heights, total_buildings = _shadow_polygons(
        azimuth, elevation, ref_lat, ref_lng, building_data
    )
    coverage = (
        known_heights / total_buildings if total_buildings else None
    )
    if shadow_geometry.is_empty:
        return ShadeSummary(
            status="unavailable",
            evaluated_at=evaluated_at,
            solar_azimuth_deg=round(azimuth, 2),
            solar_elevation_deg=round(elevation, 2),
            building_height_coverage=coverage,
            building_count=total_buildings,
            known_height_building_count=known_heights,
            source=source,
            data_quality=data_quality,
            walking_geometry_quality=walking_quality,
            calculation_note="높이가 확인된 경로 주변 건물이 없어 그늘을 계산하지 못했습니다.",
        )
    segments: list[ShadePathSegment] = []
    route_lines = [LineString(points) for points in projected_paths]
    total_geometry_m = sum(line.length for line in route_lines)
    shaded_geometry_m = sum(
        line.intersection(shadow_geometry).length for line in route_lines
    )
    for projected in projected_paths:
        for left, right in zip(projected, projected[1:]):
            length = _distance(left, right)
            steps = max(1, math.ceil(length / SAMPLE_INTERVAL_M))
            for index in range(steps):
                start_ratio = index / steps
                end_ratio = (index + 1) / steps
                start = (
                    left[0] + (right[0] - left[0]) * start_ratio,
                    left[1] + (right[1] - left[1]) * start_ratio,
                )
                end = (
                    left[0] + (right[0] - left[0]) * end_ratio,
                    left[1] + (right[1] - left[1]) * end_ratio,
                )
                midpoint = ((start[0] + end[0]) / 2, (start[1] + end[1]) / 2)
                segments.append(ShadePathSegment(
                    start=_unproject(*start, ref_lat, ref_lng),
                    end=_unproject(*end, ref_lat, ref_lng),
                    shaded=shadow_geometry.covers(Point(midpoint)),
                ))
    if total_geometry_m <= 0:
        ratio = None
        shaded_walk_m = None
    else:
        ratio = shaded_geometry_m / total_geometry_m
        shaded_walk_m = analyzed_walk_m * ratio if analyzed_walk_m is not None else None
    estimate_kind = "lower_bound" if coverage is not None and coverage < 1 else "estimate"
    display_polygons = _display_polygons(shadow_geometry)
    return ShadeSummary(
        status=estimated_status,
        evaluated_at=evaluated_at,
        shade_ratio=round(ratio, 4) if ratio is not None else None,
        shaded_walk_m=round(shaded_walk_m, 1) if shaded_walk_m is not None else None,
        total_walk_m=analyzed_walk_m,
        solar_azimuth_deg=round(azimuth, 2),
        solar_elevation_deg=round(elevation, 2),
        building_height_coverage=round(coverage, 4) if coverage is not None else None,
        building_count=total_buildings,
        known_height_building_count=known_heights,
        estimate_kind=estimate_kind,
        overlay_resolution_m=SAMPLE_INTERVAL_M,
        walking_geometry_quality=walking_quality,
        source=source,
        data_quality=data_quality,
        shadow_polygons=[
            [_unproject(x, y, ref_lat, ref_lng) for x, y in polygon]
            for polygon in display_polygons
        ],
        path_segments=segments,
        calculation_note=(
            (
                "VWorld 공공 건물 footprint와 확인된 높이, 평면 지형을 사용했습니다. "
                + (
                    "높이 결측 건물은 0m로 대체하지 않아 표시 비율은 확인된 "
                    "건물로 설명 가능한 최소 그늘입니다. "
                    if estimate_kind == "lower_bound"
                    else ""
                )
                + "나무 그늘과 지형 그림자는 포함하지 않습니다."
            )
            if data_quality == "public"
            else (
                "합성 건물 높이와 평면 지형을 사용한 검증용 데모 결과입니다. "
                "공공 건물 높이 데이터로 교체하기 전에는 실제 그늘로 해석하지 않습니다. "
                "나무 그늘과 지형 그림자는 포함하지 않습니다."
            )
        ),
    )


def calculate_demo_shade(route: RouteCandidate, departure_at: datetime | None) -> ShadeSummary:
    return calculate_shade(route, departure_at, DEMO_BUILDING_DATA)


def add_shade(
    routes: list[RouteCandidate],
    departure_at: datetime | None,
    building_data: dict,
) -> list[RouteCandidate]:
    for route in routes:
        route.shade = calculate_shade(route, departure_at, building_data)
    return routes


def add_demo_shade(
    routes: list[RouteCandidate], departure_at: datetime | None
) -> list[RouteCandidate]:
    return add_shade(routes, departure_at, DEMO_BUILDING_DATA)


def assign_characteristics(routes: list[RouteCandidate]) -> list[RouteCandidate]:
    """단일 종합순위를 만들기 전 사실 기반 대표 특성을 표시한다."""
    for route in routes:
        route.characteristics = []
    if not routes:
        return routes
    fastest_value = min(route.total_duration_min for route in routes)
    for route in routes:
        if route.total_duration_min == fastest_value:
            route.characteristics.append("fastest")

    shortest_walk_value = min(route.total_walk_m for route in routes)
    for route in routes:
        if route.total_walk_m == shortest_walk_value:
            route.characteristics.append("shortest_walk")

    fewest_transfers_value = min(route.transfer_count for route in routes)
    for route in routes:
        if route.transfer_count == fewest_transfers_value:
            route.characteristics.append("fewest_transfers")

    for route in routes:
        relevant_segments = [
            segment
            for segment in route.segments
            if segment.mode in ("walk", "transfer")
        ]
        if (
            relevant_segments
            and all(segment.has_stairs is False for segment in relevant_segments)
        ):
            route.characteristics.append("stair_free")
        bus_segments = [
            segment for segment in route.segments if segment.mode == "bus"
        ]
        if (
            bus_segments
            and all(segment.is_low_floor_bus is True for segment in bus_segments)
        ):
            route.characteristics.append("low_floor_confirmed")

    slope_candidates = [
        route for route in routes
        if route.terrain
        and route.terrain.status == "estimated_90m"
        and route.terrain.max_slope_percent is not None
        and route.terrain.min_slope_percent is not None
    ]
    if slope_candidates:
        slope_value = min(
            max(
                abs(route.terrain.max_slope_percent or 0),
                abs(route.terrain.min_slope_percent or 0),
            )
            for route in slope_candidates
        )
        for route in slope_candidates:
            worst_slope = max(
                abs(route.terrain.max_slope_percent or 0),
                abs(route.terrain.min_slope_percent or 0),
            )
            if worst_slope == slope_value:
                route.characteristics.append("lowest_slope")

    shade_candidates = [
        route for route in routes
        if route.shade
        and route.shade.status in ("estimated_demo", "estimated_public")
        and route.shade.shade_ratio is not None
    ]
    if shade_candidates:
        shade_value = max(
            float(route.shade.shade_ratio)
            for route in shade_candidates
            if route.shade and route.shade.shade_ratio is not None
        )
        if shade_value > 0:
            for route in shade_candidates:
                if (
                    route.shade
                    and route.shade.shade_ratio is not None
                    and float(route.shade.shade_ratio) == shade_value
                ):
                    route.characteristics.append("most_shade")
    return routes
