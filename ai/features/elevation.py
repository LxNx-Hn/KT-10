"""Copernicus GLO-90 기반의 경로 고도·경사 피처.

Open-Meteo Elevation API는 최대 100개 WGS84 좌표를 받으며 90m 해상도다.
따라서 결과는 보도 턱·역사 내부 경사가 아닌 지형 수준의 참고값으로만 사용한다.
"""
from __future__ import annotations

from math import asin, cos, radians, sin, sqrt

import httpx
import numpy as np

ELEVATION_URL = "https://api.open-meteo.com/v1/elevation"
MAX_POINTS = 100
SOURCE = "Copernicus DEM GLO-90 via Open-Meteo"


def _haversine_m(a: tuple[float, float], b: tuple[float, float]) -> float:
    radius = 6_371_000.0
    lat1, lng1 = map(radians, a)
    lat2, lng2 = map(radians, b)
    dlat, dlng = lat2 - lat1, lng2 - lng1
    value = sin(dlat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(dlng / 2) ** 2
    return radius * 2 * asin(sqrt(value))


def _sample(coords: list[tuple[float, float]], limit: int = MAX_POINTS) -> list[tuple[float, float]]:
    if len(coords) <= limit:
        return coords
    indices = np.linspace(0, len(coords) - 1, limit, dtype=int)
    return [coords[index] for index in dict.fromkeys(indices)]


def _empty(status: str) -> dict:
    return {
        "avg_slope_percent": None,
        "max_slope_percent": None,
        "min_slope_percent": None,
        "slope_iqr": None,
        "uphill_distance_m": None,
        "downhill_distance_m": None,
        "elevation_gain_m": None,
        "elevation_loss_m": None,
        "elevation_source": SOURCE,
        "elevation_resolution_m": 90,
        "elevation_status": status,
    }


def calculate_slope_features(
    coords: list[tuple[float, float]], elevations: list[float]
) -> dict:
    if len(coords) < 2 or len(coords) != len(elevations):
        return _empty("invalid")
    grades: list[float] = []
    uphill_distance = downhill_distance = gain = loss = 0.0
    for start, end, z1, z2 in zip(coords, coords[1:], elevations, elevations[1:]):
        distance = _haversine_m(start, end)
        if distance < 1:
            continue
        delta = float(z2) - float(z1)
        grade = delta / distance * 100
        grades.append(grade)
        if delta > 0:
            gain += delta
            uphill_distance += distance
        elif delta < 0:
            loss += abs(delta)
            downhill_distance += distance
    if not grades:
        return _empty("invalid")
    absolute = np.abs(np.asarray(grades, dtype=float))
    return {
        "avg_slope_percent": round(float(absolute.mean()), 3),
        "max_slope_percent": round(float(max(grades)), 3),
        "min_slope_percent": round(float(min(grades)), 3),
        "slope_iqr": round(float(np.percentile(absolute, 75) - np.percentile(absolute, 25)), 3),
        "uphill_distance_m": round(uphill_distance, 1),
        "downhill_distance_m": round(downhill_distance, 1),
        "elevation_gain_m": round(gain, 1),
        "elevation_loss_m": round(loss, 1),
        "elevation_source": SOURCE,
        "elevation_resolution_m": 90,
        "elevation_status": "estimated_90m",
    }


async def extract_elevation_features(
    route_coords: list[tuple[float, float]],
    client: httpx.AsyncClient | None = None,
) -> dict:
    sampled = _sample(route_coords)
    if len(sampled) < 2:
        return _empty("unavailable")
    owns_client = client is None
    client = client or httpx.AsyncClient(follow_redirects=True)
    try:
        response = await client.get(
            ELEVATION_URL,
            params={
                "latitude": ",".join(str(lat) for lat, _ in sampled),
                "longitude": ",".join(str(lng) for _, lng in sampled),
            },
            timeout=12.0,
        )
        response.raise_for_status()
        data = response.json()
        elevations = data.get("elevation")
        if not isinstance(elevations, list):
            return _empty("unavailable")
        return calculate_slope_features(sampled, elevations)
    except (httpx.HTTPError, ValueError, TypeError):
        return _empty("unavailable")
    finally:
        if owns_client:
            await client.aclose()
