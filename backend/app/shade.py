"""검증용 건물 높이와 태양 위치를 이용한 경로 그늘 계산.

기본 입력은 ``data/ai/buildings.demo.json``의 합성 데이터이며
``BUILDING_SOURCE=vworld``에서는 VWorld 건축물정보 도형·높이를 사용한다.
결과 상태는 입력 품질에 따라 ``estimated_demo`` 또는
``estimated_public``으로 구분한다.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import math
from zoneinfo import ZoneInfo

from shapely import affinity
from shapely.geometry import LineString, Point, Polygon
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union

from .building_heights import validated_building_height
from .data._loader import load
from .models import LatLng, RouteCandidate, ShadePathSegment, ShadeSummary

KST = ZoneInfo("Asia/Seoul")
SAMPLE_INTERVAL_M = 10.0
DISPLAY_SIMPLIFY_TOLERANCE_M = 0.5
DISPLAY_COORDINATE_DECIMALS = 7
DEMO_BUILDING_DATA = load("buildings.demo.json")
VWORLD_SHADE_SOURCE = "VWorld LT_C_BLDGINFO WFS"


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


def _project_mapping(
    point: object,
    ref_lat: float,
    ref_lng: float,
) -> tuple[float, float]:
    if not isinstance(point, dict):
        raise ValueError("건물 footprint 좌표가 객체 형식이 아닙니다.")
    try:
        lat = float(point["lat"])
        lng = float(point["lng"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("건물 footprint 좌표가 숫자가 아닙니다.") from exc
    if (
        not math.isfinite(lat)
        or not math.isfinite(lng)
        or not -90 <= lat <= 90
        or not -180 <= lng <= 180
    ):
        raise ValueError("건물 footprint 좌표 범위가 올바르지 않습니다.")
    return (
        (lng - ref_lng) * 111_320 * math.cos(math.radians(ref_lat)),
        (lat - ref_lat) * 110_540,
    )


def _unproject(x: float, y: float, ref_lat: float, ref_lng: float) -> LatLng:
    return LatLng(
        lat=ref_lat + y / 110_540,
        lng=ref_lng + x / (111_320 * math.cos(math.radians(ref_lat))),
    )


def _unproject_display(
    x: float,
    y: float,
    ref_lat: float,
    ref_lng: float,
) -> LatLng:
    point = _unproject(x, y, ref_lat, ref_lng)
    return LatLng(
        lat=round(point.lat, DISPLAY_COORDINATE_DECIMALS),
        lng=round(point.lng, DISPLAY_COORDINATE_DECIMALS),
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


def _solar_reference_points(
    route: RouteCandidate,
    walking_paths: list[list[LatLng]],
) -> list[LatLng]:
    """태양 고도 선판정에는 실제 보행선이 없더라도 경로 위치만 사용한다."""
    if walking_paths:
        return [
            point
            for walking_path in walking_paths
            for point in walking_path
        ]
    if route.path:
        return route.path
    return [
        point
        for segment in route.segments
        for point in (segment.path or [])
    ]


def _swept_shadow(polygon: Polygon, shift: tuple[float, float]) -> BaseGeometry:
    """수직 건물을 태양 반대 방향으로 밀어 만든 정확한 평면 스윕 영역."""
    shifted = affinity.translate(polygon, xoff=shift[0], yoff=shift[1])
    pieces: list[BaseGeometry] = [polygon, shifted]
    for ring in [polygon.exterior, *polygon.interiors]:
        coordinates = list(ring.coords)
        for left, right in zip(
            coordinates,
            coordinates[1:],
            strict=False,
        ):
            pieces.append(Polygon([
                left,
                right,
                (right[0] + shift[0], right[1] + shift[1]),
                (left[0] + shift[0], left[1] + shift[1]),
                left,
            ]))
    return unary_union(pieces)


@dataclass(frozen=True)
class _PreparedBuildingShadow:
    footprint: Polygon
    shadow: BaseGeometry
    route_distance_limit_m: float


@dataclass(frozen=True)
class PreparedShadeContext:
    ref_lat: float
    ref_lng: float
    azimuth_deg: float
    elevation_deg: float
    known_height_buildings: int
    total_buildings: int
    filter_by_route: bool
    building_shadows: tuple[_PreparedBuildingShadow, ...]


def _prepare_shadow_context(
    azimuth_deg: float,
    elevation_deg: float,
    ref_lat: float,
    ref_lng: float,
    building_data: dict,
    route_lines: list[LineString] | None = None,
) -> PreparedShadeContext:
    shadow_azimuth = math.radians((azimuth_deg + 180) % 360)
    prepared: list[_PreparedBuildingShadow] = []
    building_ids: set[str] = set()
    known_height_ids: set[str] = set()
    tan_elevation = math.tan(math.radians(elevation_deg))
    filter_by_route = len(building_data.get("buildings", [])) > 5
    route_bounds = [
        line.bounds
        for line in (route_lines or [])
        if not line.is_empty
    ]
    for building in building_data["buildings"]:
        building_id = str(building.get("buildingId") or building.get("id"))
        building_ids.add(building_id)
        height = validated_building_height(building.get("heightM"))
        if height is None:
            continue
        footprint = [
            _project_mapping(point, ref_lat, ref_lng)
            for point in building["footprint"]
        ]
        known_height_ids.add(building_id)
        shadow_length = height / tan_elevation

        if (
            route_bounds
            and shadow_length > 0
            and filter_by_route
        ):
            min_x = min(point[0] for point in footprint)
            min_y = min(point[1] for point in footprint)
            max_x = max(point[0] for point in footprint)
            max_y = max(point[1] for point in footprint)
            distance_limit = shadow_length + 100.0
            if all(
                max_x < route_min_x - distance_limit
                or min_x > route_max_x + distance_limit
                or max_y < route_min_y - distance_limit
                or min_y > route_max_y + distance_limit
                for (
                    route_min_x,
                    route_min_y,
                    route_max_x,
                    route_max_y,
                ) in route_bounds
            ):
                continue
        holes = [
            [
                _project_mapping(point, ref_lat, ref_lng)
                for point in ring
            ]
            for ring in building.get("holes") or []
        ]
        polygon = Polygon(footprint, holes)
        if polygon.is_empty or not polygon.is_valid or polygon.area <= 0:
            continue

        route_distance_limit = shadow_length + 100.0
        if route_lines and shadow_length > 0 and filter_by_route:
            if all(line.distance(polygon) > (shadow_length + 100.0) for line in route_lines):
                continue

        shift = (
            math.sin(shadow_azimuth) * shadow_length,
            math.cos(shadow_azimuth) * shadow_length,
        )
        prepared.append(_PreparedBuildingShadow(
            footprint=polygon,
            shadow=_swept_shadow(polygon, shift),
            route_distance_limit_m=route_distance_limit,
        ))
    return PreparedShadeContext(
        ref_lat=ref_lat,
        ref_lng=ref_lng,
        azimuth_deg=azimuth_deg,
        elevation_deg=elevation_deg,
        known_height_buildings=len(known_height_ids),
        total_buildings=len(building_ids),
        filter_by_route=filter_by_route,
        building_shadows=tuple(prepared),
    )


def _shadow_geometry_for_route(
    context: PreparedShadeContext,
    route_lines: list[LineString],
) -> BaseGeometry:
    shadows = [
        prepared.shadow
        for prepared in context.building_shadows
        if (
            not context.filter_by_route
            or not route_lines
            or any(
                line.distance(prepared.footprint)
                <= prepared.route_distance_limit_m
                for line in route_lines
            )
        )
    ]
    return unary_union(shadows) if shadows else Polygon()


def building_height_counts(building_data: dict) -> tuple[int, int]:
    """그림자 계산 없이 (높이 확인 건물 수, 전체 건물 수)만 센다."""
    building_ids: set[str] = set()
    known_height_ids: set[str] = set()
    for building in building_data.get("buildings", []):
        building_id = str(building.get("buildingId") or building.get("id"))
        building_ids.add(building_id)
        if validated_building_height(building.get("heightM")) is not None:
            known_height_ids.add(building_id)
    return len(known_height_ids), len(building_ids)


def _shadow_polygons(
    azimuth_deg: float,
    elevation_deg: float,
    ref_lat: float,
    ref_lng: float,
    building_data: dict,
    route_lines: list[LineString] | None = None,
) -> tuple[BaseGeometry, int, int]:
    context = _prepare_shadow_context(
        azimuth_deg,
        elevation_deg,
        ref_lat,
        ref_lng,
        building_data,
        route_lines,
    )
    return (
        _shadow_geometry_for_route(context, route_lines or []),
        context.known_height_buildings,
        context.total_buildings,
    )


def prepare_shade_context(
    routes: list[RouteCandidate],
    departure_at: datetime,
    building_data: dict,
) -> PreparedShadeContext | None:
    """같은 OD·시각 후보가 공유하는 태양과 건물 그림자를 준비한다."""
    data_quality = str(building_data.get("dataQuality") or "demo")
    is_demo = data_quality == "demo"
    walking_paths = []
    for route in routes:
        route_paths, _, quality = _walking_paths(route, demo=is_demo)
        if route_paths and (is_demo or quality == "exact"):
            walking_paths.extend(route_paths)
    points = [
        point
        for path in walking_paths
        for point in path
    ]
    if not points:
        return None
    ref_lat = sum(point.lat for point in points) / len(points)
    ref_lng = sum(point.lng for point in points) / len(points)
    solar_at = round_to_30_minutes(departure_at)
    azimuth, elevation = solar_position(solar_at, ref_lat, ref_lng)
    if elevation <= 0:
        return None
    route_lines = [
        LineString([
            _project(point, ref_lat, ref_lng)
            for point in path
        ])
        for path in walking_paths
        if len(path) >= 2
    ]
    return _prepare_shadow_context(
        azimuth,
        elevation,
        ref_lat,
        ref_lng,
        building_data,
        route_lines,
    )


def _display_polygons(geometry: BaseGeometry) -> list[list[tuple[float, float]]]:
    if geometry.is_empty:
        return []
    display_geometry = geometry.simplify(
        DISPLAY_SIMPLIFY_TOLERANCE_M,
        preserve_topology=True,
    )
    polygons = (
        [display_geometry]
        if display_geometry.geom_type == "Polygon"
        else list(display_geometry.geoms)
    )
    return [
        [(float(x), float(y)) for x, y in polygon.exterior.coords]
        for polygon in polygons
        if polygon.geom_type == "Polygon" and not polygon.is_empty
    ]


def round_to_30_minutes(dt: datetime) -> datetime:
    """태양 방위각/고도각 연산 및 캐싱을 위해 시각을 30분 단위 버킷으로 정규화한다."""
    minute = (dt.minute // 30) * 30
    return dt.replace(minute=minute, second=0, microsecond=0)


def calculate_shade(
    route: RouteCandidate,
    departure_at: datetime | None,
    building_data: dict,
    *,
    prepared_context: PreparedShadeContext | None = None,
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
    solar_points = _solar_reference_points(route, walking_paths)
    if prepared_context is not None:
        ref_lat = prepared_context.ref_lat
        ref_lng = prepared_context.ref_lng
        azimuth = prepared_context.azimuth_deg
        elevation = prepared_context.elevation_deg
    elif solar_points:
        ref_lat = sum(point.lat for point in solar_points) / len(solar_points)
        ref_lng = sum(point.lng for point in solar_points) / len(solar_points)
        solar_at = round_to_30_minutes(evaluated_at)
        azimuth, elevation = solar_position(solar_at, ref_lat, ref_lng)
    else:
        ref_lat = ref_lng = azimuth = elevation = None
    if elevation is not None and elevation <= 0:
        return ShadeSummary(
            status="not_daylight",
            evaluated_at=evaluated_at,
            solar_azimuth_deg=round(azimuth, 2),
            solar_elevation_deg=round(elevation, 2),
            source=source,
            data_quality=data_quality,
            walking_geometry_quality=walking_quality,
            calculation_note=(
                "태양 고도가 0도 이하인 시각이라 건물 그늘을 계산하지 "
                "않았습니다."
            ),
        )
    if not walking_paths:
        return ShadeSummary(
            status="unavailable",
            evaluated_at=evaluated_at,
            solar_azimuth_deg=round(azimuth, 2) if azimuth is not None else None,
            solar_elevation_deg=(
                round(elevation, 2) if elevation is not None else None
            ),
            source=source,
            data_quality=data_quality,
            walking_geometry_quality=walking_quality,
            calculation_note=(
                "분석할 수 있는 보행 경로 좌표가 없어 건물 그늘을 계산하지 "
                "않았습니다."
            ),
        )
    assert ref_lat is not None
    assert ref_lng is not None
    assert azimuth is not None
    assert elevation is not None
    if not is_demo and walking_quality != "exact":
        return ShadeSummary(
            status="unavailable",
            evaluated_at=evaluated_at,
            total_walk_m=analyzed_walk_m,
            solar_azimuth_deg=round(azimuth, 2),
            solar_elevation_deg=round(elevation, 2),
            source=source,
            data_quality=data_quality,
            walking_geometry_quality=walking_quality,
            calculation_note=(
                "실제 보행 경로가 완전히 확인되지 않아 건물 그늘을 계산하지 "
                "않았습니다."
            ),
        )
    if not is_demo and building_data.get("cacheComplete") is False:
        return ShadeSummary(
            status="unavailable",
            evaluated_at=evaluated_at,
            total_walk_m=analyzed_walk_m,
            solar_azimuth_deg=round(azimuth, 2),
            solar_elevation_deg=round(elevation, 2),
            source=source,
            data_quality=data_quality,
            walking_geometry_quality=walking_quality,
            calculation_note=(
                "경로 주변 건물 데이터가 캐시에 완전히 준비되지 않아 건물 "
                "그늘을 계산하지 않았습니다."
            ),
        )

    applicable_bounds = building_data.get("applicableBounds")
    if applicable_bounds is not None:
        try:
            min_lat = float(applicable_bounds["minLat"])
            max_lat = float(applicable_bounds["maxLat"])
            min_lng = float(applicable_bounds["minLng"])
            max_lng = float(applicable_bounds["maxLng"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("건물 데이터 적용 범위가 올바르지 않습니다.") from exc
        if (
            not all(math.isfinite(value) for value in (
                min_lat, max_lat, min_lng, max_lng
            ))
            or min_lat >= max_lat
            or min_lng >= max_lng
        ):
            raise ValueError("건물 데이터 적용 범위가 올바르지 않습니다.")
        if any(
            not (
                min_lat <= point.lat <= max_lat
                and min_lng <= point.lng <= max_lng
            )
            for walking_path in walking_paths
            for point in walking_path
        ):
            return ShadeSummary(
                status="unavailable",
                evaluated_at=evaluated_at,
                total_walk_m=analyzed_walk_m,
                solar_azimuth_deg=round(azimuth, 2),
                solar_elevation_deg=round(elevation, 2),
                source=source,
                data_quality=data_quality,
                walking_geometry_quality=walking_quality,
                calculation_note=(
                    "보행 경로가 확인된 건물 데이터 범위를 벗어나 건물 그늘을 "
                    "계산하지 않았습니다."
                ),
            )

    projected_paths = [
        [_project(point, ref_lat, ref_lng) for point in walking_path]
        for walking_path in walking_paths
    ]
    route_lines = [LineString(points) for points in projected_paths if len(points) >= 2]
    if prepared_context is not None:
        known_heights = prepared_context.known_height_buildings
        total_buildings = prepared_context.total_buildings
    else:
        known_heights, total_buildings = building_height_counts(building_data)
    coverage = (
        known_heights / total_buildings if total_buildings else None
    )
    if (
        data_quality == "public"
        and total_buildings > 0
        and known_heights < total_buildings
    ):
        # 관련 건물 높이가 완전하지 않으면 부분 그림자를 실제 그늘 비율처럼
        # 표시하지 않는다. lower bound 추정도 만들지 않는다.
        return ShadeSummary(
            status="unavailable",
            evaluated_at=evaluated_at,
            total_walk_m=analyzed_walk_m,
            solar_azimuth_deg=round(azimuth, 2),
            solar_elevation_deg=round(elevation, 2),
            building_height_coverage=round(coverage, 4)
            if coverage is not None
            else None,
            building_count=total_buildings,
            known_height_building_count=known_heights,
            source=source,
            data_quality=data_quality,
            walking_geometry_quality=walking_quality,
            calculation_note=(
                "경로 주변 건물의 확인된 높이가 완전하지 않아 건물 그늘을 "
                "계산하지 않았습니다."
            ),
        )
    if prepared_context is None:
        shadow_geometry, known_heights, total_buildings = _shadow_polygons(
            azimuth,
            elevation,
            ref_lat,
            ref_lng,
            building_data,
            route_lines=route_lines,
        )
    else:
        shadow_geometry = _shadow_geometry_for_route(
            prepared_context,
            route_lines,
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
            calculation_note=(
                "경로 주변에서 계산 가능한 건물 그림자를 만들 수 없었습니다."
            ),
        )
    segments: list[ShadePathSegment] = []
    route_lines = [LineString(points) for points in projected_paths]
    total_geometry_m = sum(line.length for line in route_lines)
    shaded_geometry_m = sum(
        line.intersection(shadow_geometry).length for line in route_lines
    )
    for projected in projected_paths:
        for left, right in zip(
            projected,
            projected[1:],
            strict=False,
        ):
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
        return ShadeSummary(
            status="unavailable",
            evaluated_at=evaluated_at,
            total_walk_m=analyzed_walk_m,
            solar_azimuth_deg=round(azimuth, 2),
            solar_elevation_deg=round(elevation, 2),
            building_height_coverage=(
                round(coverage, 4) if coverage is not None else None
            ),
            building_count=total_buildings,
            known_height_building_count=known_heights,
            walking_geometry_quality=walking_quality,
            source=source,
            data_quality=data_quality,
            calculation_note=(
                "분석 가능한 보행 경로 길이가 없어 건물 그늘을 계산하지 "
                "않았습니다."
            ),
        )
    ratio = shaded_geometry_m / total_geometry_m
    shaded_walk_m = (
        analyzed_walk_m * ratio
        if analyzed_walk_m is not None
        else None
    )
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
            [_unproject_display(x, y, ref_lat, ref_lng) for x, y in polygon]
            for polygon in display_polygons
        ],
        path_segments=segments,
        calculation_note=(
            (
                "VWorld 공공 건물 footprint와 확인된 높이, 평면 지형 기반 "
                "추정 결과입니다. "
                + (
                    "표시 비율은 높이가 확인된 건물로 설명 가능한 최소 "
                    "그늘입니다. "
                    if estimate_kind == "lower_bound"
                    else ""
                )
                + "범위는 건물 그늘이며 나무 그늘과 지형 그림자는 제외 범위입니다."
            )
            if data_quality == "public"
            else (
                "합성 건물 높이와 평면 지형 기반 검증용 데모 결과입니다. "
                "실제 서비스 기준은 VWorld 공공 건물 높이 데이터입니다. "
                "범위는 건물 그늘이며 나무 그늘과 지형 그림자는 제외 범위입니다."
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


def resolve_shade_without_buildings(
    routes: list[RouteCandidate],
    departure_at: datetime | None,
    *,
    source: str,
    data_quality: str,
) -> bool:
    """건물 조회 전에 전 후보를 확정할 수 있으면 그늘 결과를 바로 채운다.

    현재 조기 확정 대상은 실외 보행 geometry가 없거나 태양 고도가 0도
    이하인 경우다. 한 경로라도 주간 건물 계산이 필요하면 후보를 변경하지
    않고 False를 반환한다.
    """
    evaluated_at = departure_at or datetime.now(KST)
    if evaluated_at.tzinfo is None:
        evaluated_at = evaluated_at.replace(tzinfo=KST)
    else:
        evaluated_at = evaluated_at.astimezone(KST)
    is_demo = data_quality == "demo"
    summaries: list[ShadeSummary] = []

    for route in routes:
        walking_paths, analyzed_walk_m, walking_quality = _walking_paths(
            route,
            demo=is_demo,
        )
        solar_points = _solar_reference_points(route, walking_paths)
        if not solar_points:
            summaries.append(ShadeSummary(
                status="unavailable",
                evaluated_at=evaluated_at,
                source=source,
                data_quality=data_quality,
                walking_geometry_quality=walking_quality,
                calculation_note=(
                    "태양 위치를 계산할 경로 좌표가 없어 건물 그늘을 계산하지 "
                    "않았습니다."
                ),
            ))
            continue

        ref_lat = sum(point.lat for point in solar_points) / len(solar_points)
        ref_lng = sum(point.lng for point in solar_points) / len(solar_points)
        solar_at = round_to_30_minutes(evaluated_at)
        azimuth, elevation = solar_position(solar_at, ref_lat, ref_lng)
        if elevation > 0:
            if walking_paths:
                return False
            summaries.append(ShadeSummary(
                status="unavailable",
                evaluated_at=evaluated_at,
                solar_azimuth_deg=round(azimuth, 2),
                solar_elevation_deg=round(elevation, 2),
                source=source,
                data_quality=data_quality,
                walking_geometry_quality=walking_quality,
                calculation_note=(
                    "분석할 수 있는 보행 경로 좌표가 없어 건물 그늘을 계산하지 "
                    "않았습니다."
                ),
            ))
            continue
        summaries.append(ShadeSummary(
            status="not_daylight",
            evaluated_at=evaluated_at,
            total_walk_m=analyzed_walk_m,
            solar_azimuth_deg=round(azimuth, 2),
            solar_elevation_deg=round(elevation, 2),
            source=source,
            data_quality=data_quality,
            walking_geometry_quality=walking_quality,
            calculation_note=(
                "태양 고도가 0도 이하인 시각이라 건물 그늘을 계산하지 "
                "않았습니다."
            ),
        ))

    for route, summary in zip(routes, summaries, strict=True):
        route.shade = summary
    return True


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
