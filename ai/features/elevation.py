"""부산 QGIS 90m DEM 기반의 경로 고도·경사 피처.

운영 요청은 메모리에 적재한 부산 지역 DEM을 사용한다. Open-Meteo와
Copernicus GLO-90 COG는 지역 DEM 범위 밖의 fallback 공급자다. 결과는
보도 턱·역사 내부 경사가 아닌 90m 격자 지형 수준의 참고값이다.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from hashlib import sha256
from itertools import pairwise
from math import asin, ceil, cos, floor, isfinite, radians, sin, sqrt
from pathlib import Path
from threading import Lock
from typing import NamedTuple
from uuid import uuid4

import httpx
import numpy as np
import rasterio
from affine import Affine
from config import settings
from rasterio.warp import transform as transform_coordinates

ELEVATION_URL = "https://api.open-meteo.com/v1/elevation"
DEM_BASE_URL = "https://copernicus-dem-90m.s3.eu-central-1.amazonaws.com"
# 15km 지원 상한을 약 90m 간격으로 표본화하면 최대 168개가 필요하다.
# 원격 공급자 fallback은 표본을 100개씩 나누어 전송한다.
MAX_POINTS = 200
PROVIDER_BATCH_SIZE = 100
SAMPLE_SPACING_M = 90.0
SOURCE = "Copernicus DEM GLO-90 via Open-Meteo"
LOCAL_DEM_SOURCE = "Copernicus DEM GLO-90 via AWS Open Data COG"
REGIONAL_DEM_SOURCE = "Busan DEM 90m (QGIS precomputed)"
CACHE_SCHEMA_VERSION = 3
log = logging.getLogger("features.elevation")
_dem_tile_locks: dict[str, Lock] = {}
_dem_tile_locks_guard = Lock()
_cache_write_locks: dict[str, Lock] = {}
_cache_write_locks_guard = Lock()
_regional_dem_lock = Lock()
_regional_dem: "RegionalDem | None" = None


class RegionalDem(NamedTuple):
    values: np.ndarray
    transform: Affine
    crs: object
    nodata: float | None


def _regional_dem_path() -> Path:
    configured = settings.ELEVATION_REGIONAL_DEM_PATH.strip()
    if configured:
        return Path(configured)
    return (
        Path(__file__).resolve().parents[1]
        / "data"
        / "precomputed"
        / "busan_dem_clipped_90m.tif"
    )


def prepare_regional_dem() -> dict[str, object] | None:
    """QGIS 부산 DEM을 한 번만 메모리에 적재해 요청 중 파일 I/O를 없앤다."""
    global _regional_dem
    with _regional_dem_lock:
        if _regional_dem is None:
            path = _regional_dem_path()
            if not path.is_file():
                return None
            with rasterio.open(path) as dataset:
                if (
                    dataset.count != 1
                    or dataset.width < 2
                    or dataset.height < 2
                    or dataset.crs is None
                    or dataset.crs.to_epsg() != 5179
                    or abs(float(dataset.res[0]) - 90.0) > 1e-6
                    or abs(float(dataset.res[1]) - 90.0) > 1e-6
                ):
                    raise ValueError(
                        "부산 사전계산 DEM의 CRS 또는 90m 해상도가 올바르지 않습니다."
                    )
                values = dataset.read(1)
                if values.dtype.kind not in {"f", "i", "u"}:
                    raise ValueError("부산 사전계산 DEM의 픽셀 형식이 숫자가 아닙니다.")
                _regional_dem = RegionalDem(
                    values=values,
                    transform=dataset.transform,
                    crs=dataset.crs,
                    nodata=(
                        float(dataset.nodata)
                        if dataset.nodata is not None
                        else None
                    ),
                )
        return {
            "path": str(_regional_dem_path()),
            "width": int(_regional_dem.values.shape[1]),
            "height": int(_regional_dem.values.shape[0]),
            "resolution_m": 90,
        }


def regional_dem_ready() -> bool:
    try:
        return prepare_regional_dem() is not None
    except (OSError, ValueError, rasterio.errors.RasterioError):
        return False


def _regional_dem_elevations(
    sampled: list[tuple[float, float]],
) -> list[float] | None:
    if prepare_regional_dem() is None or _regional_dem is None:
        return None
    xs, ys = transform_coordinates(
        "EPSG:4326",
        _regional_dem.crs,
        [lng for lat, lng in sampled],
        [lat for lat, lng in sampled],
    )
    inverse = ~_regional_dem.transform
    elevations: list[float] = []
    height, width = _regional_dem.values.shape
    for x, y in zip(xs, ys, strict=True):
        pixel_x, pixel_y = inverse * (x, y)
        pixel_x -= 0.5
        pixel_y -= 0.5
        x0 = floor(pixel_x)
        y0 = floor(pixel_y)
        if x0 < 0 or y0 < 0 or x0 + 1 >= width or y0 + 1 >= height:
            return None
        dx = pixel_x - x0
        dy = pixel_y - y0
        values = [
            float(_regional_dem.values[y0, x0]),
            float(_regional_dem.values[y0, x0 + 1]),
            float(_regional_dem.values[y0 + 1, x0]),
            float(_regional_dem.values[y0 + 1, x0 + 1]),
        ]
        if any(
            not isfinite(value)
            or (
                _regional_dem.nodata is not None
                and abs(value - _regional_dem.nodata) < 1e-6
            )
            for value in values
        ):
            return None
        elevations.append(
            values[0] * (1 - dx) * (1 - dy)
            + values[1] * dx * (1 - dy)
            + values[2] * (1 - dx) * dy
            + values[3] * dx * dy
        )
    return elevations


def _cache_write_lock(path: Path) -> Lock:
    key = str(path.resolve())
    with _cache_write_locks_guard:
        return _cache_write_locks.setdefault(key, Lock())


def _cache_path(
    sampled_parts: list[list[tuple[float, float]]],
) -> Path | None:
    cache_dir = settings.ELEVATION_CACHE_DIR.strip()
    if not cache_dir:
        return None
    digest = sha256(
        json.dumps(
            [
                [[round(lat, 7), round(lng, 7)] for lat, lng in part]
                for part in sampled_parts
            ],
            separators=(",", ":"),
        ).encode("ascii")
    ).hexdigest()
    return Path(cache_dir) / f"{digest}.json"


def _read_cache(
    sampled_parts: list[list[tuple[float, float]]],
) -> dict | None:
    path = _cache_path(sampled_parts)
    if path is None or not path.is_file():
        return None
    try:
        wrapper = json.loads(path.read_text(encoding="utf-8"))
        cached_at = float(wrapper["cachedAtEpoch"])
        result = wrapper["result"]
    except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError):
        return None
    if (
        wrapper.get("schemaVersion") != CACHE_SCHEMA_VERSION
        or not isinstance(result, dict)
        or result.get("elevation_status") != "estimated_90m"
        or time.time() - cached_at > settings.ELEVATION_CACHE_TTL_SECONDS
    ):
        return None
    return result


def _write_cache(
    sampled_parts: list[list[tuple[float, float]]],
    result: dict,
) -> None:
    path = _cache_path(sampled_parts)
    if path is None:
        return
    with _cache_write_lock(path):
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
        try:
            temporary.write_text(
                json.dumps(
                    {
                        "schemaVersion": CACHE_SCHEMA_VERSION,
                        "cachedAtEpoch": time.time(),
                        "result": result,
                    },
                    ensure_ascii=False,
                    separators=(",", ":"),
                ),
                encoding="utf-8",
            )
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)


def _dem_tile_id(lat: float, lng: float) -> str:
    """WGS84 좌표가 속한 Copernicus GLO-90 1도 COG 식별자."""
    latitude = floor(lat)
    longitude = floor(lng)
    northing = f"{'N' if latitude >= 0 else 'S'}{abs(latitude):02d}_00"
    easting = f"{'E' if longitude >= 0 else 'W'}{abs(longitude):03d}_00"
    return f"Copernicus_DSM_COG_30_{northing}_{easting}_DEM"


def _dem_tile_lock(tile_id: str) -> Lock:
    with _dem_tile_locks_guard:
        return _dem_tile_locks.setdefault(tile_id, Lock())


def _ensure_dem_tile(tile_id: str) -> Path | None:
    """공개 GLO-90 COG를 원자적으로 한 번만 내려받아 영속 캐시에 둔다."""
    configured_dir = settings.ELEVATION_DEM_DIR.strip()
    if not configured_dir:
        return None
    directory = Path(configured_dir)
    path = directory / f"{tile_id}.tif"
    with _dem_tile_lock(tile_id):
        if path.is_file() and path.stat().st_size > 0:
            return path
        directory.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
        url = f"{DEM_BASE_URL}/{tile_id}/{tile_id}.tif"
        try:
            with httpx.stream(
                "GET",
                url,
                follow_redirects=True,
                timeout=60.0,
            ) as response:
                response.raise_for_status()
                with temporary.open("wb") as handle:
                    for chunk in response.iter_bytes():
                        handle.write(chunk)
            with rasterio.open(temporary) as dataset:
                if (
                    dataset.count < 1
                    or dataset.width < 2
                    or dataset.height < 2
                    or dataset.crs is None
                    or dataset.crs.to_epsg() != 4326
                ):
                    raise ValueError("GLO-90 COG 공간 참조 또는 크기가 올바르지 않습니다.")
            temporary.replace(path)
            return path
        except (httpx.HTTPError, OSError, ValueError, rasterio.errors.RasterioError) as exc:
            log.warning(
                "로컬 GLO-90 타일 준비 실패 tile=%s type=%s",
                tile_id,
                type(exc).__name__,
            )
            return None
        finally:
            temporary.unlink(missing_ok=True)


def _local_dem_elevations(
    sampled: list[tuple[float, float]],
) -> tuple[list[float], str] | None:
    """표본 좌표를 같은 1도 타일끼리 묶어 로컬 COG에서 읽는다."""
    regional = _regional_dem_elevations(sampled)
    if regional is not None:
        return regional, REGIONAL_DEM_SOURCE
    if not settings.ELEVATION_DEM_DIR.strip():
        return None
    groups: dict[str, list[tuple[int, float, float]]] = {}
    for index, (lat, lng) in enumerate(sampled):
        groups.setdefault(_dem_tile_id(lat, lng), []).append((index, lat, lng))

    elevations: list[float | None] = [None] * len(sampled)
    for tile_id, points in groups.items():
        path = _ensure_dem_tile(tile_id)
        if path is None:
            return None
        try:
            with rasterio.open(path) as dataset:
                samples = dataset.sample(
                    [(lng, lat) for _, lat, lng in points],
                    indexes=1,
                    masked=True,
                )
                for (index, _, _), sample in zip(points, samples):
                    value = sample[0]
                    if np.ma.is_masked(value):
                        return None
                    number = float(value)
                    if not isfinite(number):
                        return None
                    elevations[index] = number
        except (OSError, ValueError, rasterio.errors.RasterioError) as exc:
            log.warning(
                "로컬 GLO-90 표본 조회 실패 tile=%s type=%s",
                tile_id,
                type(exc).__name__,
            )
            return None
    if any(value is None for value in elevations):
        return None
    return [float(value) for value in elevations], LOCAL_DEM_SOURCE


def _haversine_m(a: tuple[float, float], b: tuple[float, float]) -> float:
    radius = 6_371_000.0
    lat1, lng1 = map(radians, a)
    lat2, lng2 = map(radians, b)
    dlat, dlng = lat2 - lat1, lng2 - lng1
    value = sin(dlat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(dlng / 2) ** 2
    return radius * 2 * asin(sqrt(value))


def _valid_coordinate(point: tuple[float, float]) -> bool:
    try:
        lat, lng = float(point[0]), float(point[1])
    except (IndexError, TypeError, ValueError):
        return False
    return isfinite(lat) and isfinite(lng) and -90 <= lat <= 90 and -180 <= lng <= 180


def _sample(
    coords: list[tuple[float, float]],
    limit: int = MAX_POINTS,
) -> list[tuple[float, float]]:
    """약 90m 누적거리 간격으로 보간하되 API 상한을 지킨다.

    공급자 geometry는 같은 선도 정점 밀도가 다르고, 긴 직선은 시작·끝 두
    점만 줄 수 있다. 정점 인덱스 표본은 이 경우 중간 지형을 완전히 놓치므로
    실제 누적거리 기준으로 표본을 만든다.
    """
    if limit < 2 or len(coords) < 2 or any(not _valid_coordinate(point) for point in coords):
        return []

    compact = [(float(coords[0][0]), float(coords[0][1]))]
    for point in coords[1:]:
        normalized = (float(point[0]), float(point[1]))
        if _haversine_m(compact[-1], normalized) > 1e-6:
            compact.append(normalized)
    if len(compact) < 2:
        return []

    cumulative = [0.0]
    for start, end in pairwise(compact):
        cumulative.append(cumulative[-1] + _haversine_m(start, end))
    total = cumulative[-1]
    if not isfinite(total) or total <= 0:
        return []

    count = min(limit, max(2, ceil(total / SAMPLE_SPACING_M) + 1))
    sampled: list[tuple[float, float]] = []
    segment_index = 0
    for index in range(count):
        target = total * index / (count - 1)
        while (
            segment_index < len(compact) - 2
            and cumulative[segment_index + 1] < target
        ):
            segment_index += 1
        segment_start = cumulative[segment_index]
        segment_end = cumulative[segment_index + 1]
        ratio = (
            (target - segment_start) / (segment_end - segment_start)
            if segment_end > segment_start
            else 0.0
        )
        start = compact[segment_index]
        end = compact[segment_index + 1]
        sampled.append((
            start[0] + (end[0] - start[0]) * ratio,
            start[1] + (end[1] - start[1]) * ratio,
        ))
    return sampled


def _empty(status: str, source: str = SOURCE) -> dict:
    return {
        "avg_slope_percent": None,
        "max_slope_percent": None,
        "min_slope_percent": None,
        "slope_iqr": None,
        "uphill_distance_m": None,
        "downhill_distance_m": None,
        "elevation_gain_m": None,
        "elevation_loss_m": None,
        "elevation_source": source,
        "elevation_resolution_m": 90,
        "elevation_status": status,
        "slope_segments": [],
    }


def calculate_slope_features_for_parts(
    coord_parts: list[list[tuple[float, float]]],
    elevation_parts: list[list[float]],
    *,
    source: str = SOURCE,
) -> dict:
    """서로 끊어진 보행 구간을 연결하지 않고 경사 피처를 합산한다."""
    if (
        not coord_parts
        or len(coord_parts) != len(elevation_parts)
        or any(
            len(coords) < 2
            or len(coords) != len(elevations)
            or any(not _valid_coordinate(point) for point in coords)
            for coords, elevations in zip(coord_parts, elevation_parts)
        )
    ):
        return _empty("invalid", source)
    grades: list[float] = []
    grade_distances: list[float] = []
    slope_segments: list[dict] = []
    uphill_distance = downhill_distance = gain = loss = 0.0
    for coords, elevations in zip(coord_parts, elevation_parts):
        for start, end, z1, z2 in zip(
            coords,
            coords[1:],
            elevations,
            elevations[1:],
        ):
            distance = _haversine_m(start, end)
            if distance < 1:
                continue
            if isinstance(z1, bool) or isinstance(z2, bool):
                return _empty("invalid", source)
            try:
                start_elevation = float(z1)
                end_elevation = float(z2)
            except (TypeError, ValueError):
                return _empty("invalid", source)
            if not isfinite(start_elevation) or not isfinite(end_elevation):
                return _empty("invalid", source)
            delta = end_elevation - start_elevation
            grade = delta / distance * 100
            if not isfinite(grade):
                return _empty("invalid", source)
            grades.append(grade)
            grade_distances.append(distance)
            slope_segments.append({
                "start": {"lat": start[0], "lng": start[1]},
                "end": {"lat": end[0], "lng": end[1]},
                "slope_percent": round(grade, 3),
                "distance_m": round(distance, 1),
            })
            if delta > 0:
                gain += delta
                uphill_distance += distance
            elif delta < 0:
                loss += abs(delta)
                downhill_distance += distance
    if not grades:
        return _empty("invalid", source)
    absolute = np.abs(np.asarray(grades, dtype=float))
    return {
        "avg_slope_percent": round(
            float(np.average(absolute, weights=np.asarray(grade_distances))),
            3,
        ),
        "max_slope_percent": round(float(max(grades)), 3),
        "min_slope_percent": round(float(min(grades)), 3),
        "slope_iqr": round(float(np.percentile(absolute, 75) - np.percentile(absolute, 25)), 3),
        "uphill_distance_m": round(uphill_distance, 1),
        "downhill_distance_m": round(downhill_distance, 1),
        "elevation_gain_m": round(gain, 1),
        "elevation_loss_m": round(loss, 1),
        "elevation_source": source,
        "elevation_resolution_m": 90,
        "elevation_status": "estimated_90m",
        "slope_segments": slope_segments,
    }


def calculate_slope_features(
    coords: list[tuple[float, float]], elevations: list[float]
) -> dict:
    """단일 연속 경로 호환 API."""
    return calculate_slope_features_for_parts([coords], [elevations])


async def extract_elevation_features(
    route_coords: list[tuple[float, float]],
    client: httpx.AsyncClient | None = None,
) -> dict:
    """단일 연속 경로 호환 API."""
    return await extract_elevation_features_for_parts([route_coords], client)


async def extract_elevation_features_for_parts(
    route_parts: list[list[tuple[float, float]]],
    client: httpx.AsyncClient | None = None,
) -> dict:
    """보행 parts만 고도 조회하며 서로 떨어진 parts 사이 경사는 만들지 않는다."""
    sampled_parts = [_sample(part) for part in route_parts]
    if not sampled_parts or any(len(part) < 2 for part in sampled_parts):
        return _empty("unavailable")
    cached = await asyncio.to_thread(_read_cache, sampled_parts)
    if cached is not None:
        return cached
    sampled = [point for part in sampled_parts for point in part]
    local_result = await asyncio.to_thread(_local_dem_elevations, sampled)
    if local_result is not None:
        local_elevations, local_source = local_result
        elevation_parts: list[list[float]] = []
        offset = 0
        for part in sampled_parts:
            elevation_parts.append(
                local_elevations[offset:offset + len(part)]
            )
            offset += len(part)
        result = calculate_slope_features_for_parts(
            sampled_parts,
            elevation_parts,
            source=local_source,
        )
        if result["elevation_status"] == "estimated_90m":
            try:
                await asyncio.to_thread(_write_cache, sampled_parts, result)
            except OSError as exc:
                log.warning(
                    "고도 캐시 저장 실패 (%s)",
                    type(exc).__name__,
                )
        return result

    owns_client = client is None
    client = client or httpx.AsyncClient(follow_redirects=True)
    try:
        elevations: list[float] = []
        for start in range(0, len(sampled), PROVIDER_BATCH_SIZE):
            batch = sampled[start:start + PROVIDER_BATCH_SIZE]
            response = await client.get(
                ELEVATION_URL,
                params={
                    "latitude": ",".join(str(lat) for lat, _ in batch),
                    "longitude": ",".join(str(lng) for _, lng in batch),
                },
                timeout=12.0,
            )
            response.raise_for_status()
            data = response.json()
            if not isinstance(data, dict):
                return _empty("unavailable")
            batch_elevations = data.get("elevation")
            if (
                not isinstance(batch_elevations, list)
                or len(batch_elevations) != len(batch)
            ):
                return _empty("unavailable")
            elevations.extend(batch_elevations)

        elevation_parts: list[list[float]] = []
        offset = 0
        for part in sampled_parts:
            elevation_parts.append(elevations[offset:offset + len(part)])
            offset += len(part)
        result = calculate_slope_features_for_parts(
            sampled_parts,
            elevation_parts,
        )
        if result["elevation_status"] == "estimated_90m":
            try:
                await asyncio.to_thread(_write_cache, sampled_parts, result)
            except OSError as exc:
                log.warning(
                    "고도 캐시 저장 실패 (%s)",
                    type(exc).__name__,
                )
        return result
    except (httpx.HTTPError, ValueError, TypeError):
        return _empty("unavailable")
    finally:
        if owns_client:
            await client.aclose()
