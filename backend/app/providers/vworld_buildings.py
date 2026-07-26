"""VWorld 공공 건축물정보 WFS에서 footprint와 높이를 함께 조회한다."""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import math
from pathlib import Path
from threading import Lock
import time
from typing import Any
from uuid import uuid4
from weakref import WeakKeyDictionary

import httpx

from ..building_heights import validated_building_height
from ..models import LatLng, RouteCandidate
from ..settings import settings

VWORLD_DATA_URL = "https://api.vworld.kr/req/data"
VWORLD_LAYER = "LT_C_BLDGINFO"
QUERY_BUFFER_M = 250.0
QUERY_SEGMENT_M = 500.0
PAGE_SIZE = 1000
MAX_FEATURES = 10_000
MAX_QUERY_BOXES = 200
MAX_CONCURRENT_QUERIES = 3
MAX_MEMORY_CACHE_BOXES = 4096
MAX_MEMORY_ROUTE_BUILDING_SETS = 1024
CACHE_SCHEMA_VERSION = 1
_warm_tasks: set[asyncio.Task] = set()
_warming_boxes: set[tuple[float, float, float, float]] = set()
_warming_boxes_guard = Lock()
_memory_cache: dict[
    tuple[str, tuple[float, float, float, float]],
    tuple[float, list[dict]],
] = {}
_memory_cache_guard = Lock()
_route_memory_cache: dict[
    tuple[str, tuple[tuple[float, float, float, float], ...]],
    tuple[float, dict],
] = {}
_route_memory_cache_guard = Lock()
_request_locks: WeakKeyDictionary = WeakKeyDictionary()
_request_locks_guard = Lock()
log = logging.getLogger("providers.vworld_buildings")


def _cache_namespace() -> str:
    material = (
        f"{CACHE_SCHEMA_VERSION}|{settings.vworld_api_key}|"
        f"{settings.vworld_api_domain}|{settings.vworld_cache_dir}"
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def _store_memory_cache(
    query_box: tuple[float, float, float, float],
    features: list[dict],
) -> None:
    key = (_cache_namespace(), query_box)
    with _memory_cache_guard:
        _memory_cache[key] = (time.monotonic(), features)
        while len(_memory_cache) > MAX_MEMORY_CACHE_BOXES:
            oldest = next(iter(_memory_cache))
            _memory_cache.pop(oldest, None)


def _read_route_memory_cache(
    query_boxes: list[tuple[float, float, float, float]],
) -> dict | None:
    key = (_cache_namespace(), tuple(query_boxes))
    now = time.monotonic()
    with _route_memory_cache_guard:
        cached = _route_memory_cache.get(key)
        if (
            cached is None
            or now - cached[0]
            > settings.vworld_cache_ttl_hours * 3600
        ):
            if cached is not None:
                _route_memory_cache.pop(key, None)
            return None
        return cached[1]


def _store_route_memory_cache(
    query_boxes: list[tuple[float, float, float, float]],
    building_data: dict,
) -> None:
    key = (_cache_namespace(), tuple(query_boxes))
    with _route_memory_cache_guard:
        _route_memory_cache[key] = (time.monotonic(), building_data)
        while len(_route_memory_cache) > MAX_MEMORY_ROUTE_BUILDING_SETS:
            oldest = next(iter(_route_memory_cache))
            _route_memory_cache.pop(oldest, None)


def _distance_m(left: LatLng, right: LatLng) -> float:
    mean_lat = math.radians((left.lat + right.lat) / 2)
    dx = math.radians(right.lng - left.lng) * math.cos(mean_lat)
    dy = math.radians(right.lat - left.lat)
    return 6_371_008.8 * math.hypot(dx, dy)


def _sample_path(path: list[LatLng]) -> list[LatLng]:
    if len(path) < 2:
        return []
    sampled = [path[0]]
    distance_to_sample = QUERY_SEGMENT_M
    for left, right in zip(path, path[1:], strict=False):
        start = left
        remaining = _distance_m(start, right)
        while remaining > 0 and remaining >= distance_to_sample:
            ratio = distance_to_sample / remaining
            point = LatLng(
                lat=start.lat + (right.lat - start.lat) * ratio,
                lng=start.lng + (right.lng - start.lng) * ratio,
            )
            sampled.append(point)
            start = point
            remaining = _distance_m(start, right)
            distance_to_sample = QUERY_SEGMENT_M
        distance_to_sample -= remaining
    if sampled[-1] != path[-1]:
        sampled.append(path[-1])
    return sampled


def _path_query_boxes(
    path: list[LatLng],
) -> list[tuple[float, float, float, float]]:
    sampled = _sample_path(path)
    boxes: list[tuple[float, float, float, float]] = []
    for left, right in zip(sampled, sampled[1:], strict=False):
        mean_lat = (left.lat + right.lat) / 2
        lat_buffer = QUERY_BUFFER_M / 110_540
        lng_buffer = QUERY_BUFFER_M / (
            111_320 * math.cos(math.radians(mean_lat))
        )
        boxes.append((
            min(left.lng, right.lng) - lng_buffer,
            min(left.lat, right.lat) - lat_buffer,
            max(left.lng, right.lng) + lng_buffer,
            max(left.lat, right.lat) + lat_buffer,
        ))
    return boxes


def _exact_walking_paths(routes: list[RouteCandidate]) -> list[list[LatLng]]:
    paths: list[list[LatLng]] = []
    for route in routes:
        relevant = [
            segment
            for segment in route.segments
            if (
                (segment.mode == "walk" and segment.outdoor is not False)
                or (segment.mode == "transfer" and segment.outdoor is True)
            )
        ]
        if not relevant:
            continue
        if all(
            segment.geometry_quality == "exact"
            and segment.path
            and len(segment.path) >= 2
            for segment in relevant
        ):
            paths.extend(
                segment.path
                for segment in relevant
                if segment.path is not None
            )
            continue
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
            and route.geometry_quality == "exact"
            and route.path
            and len(route.path) >= 2
        ):
            paths.append(route.path)
    return paths


def _route_query_boxes(
    routes: list[RouteCandidate],
) -> list[tuple[float, float, float, float]]:
    boxes = {
        tuple(round(value, 7) for value in box)
        for path in _exact_walking_paths(routes)
        for box in _path_query_boxes(path)
    }
    if len(boxes) > MAX_QUERY_BOXES:
        raise RuntimeError(
            f"보행 경로 건물 조회 영역이 안전 한도 {MAX_QUERY_BOXES}개를 초과했습니다."
        )
    return sorted(boxes)


def _feature_identity(feature: dict) -> str:
    feature_id = feature.get("id")
    if feature_id not in (None, ""):
        return f"id:{feature_id}"
    properties = feature.get("properties") or {}
    for key in ("ufid", "bldrgst_pk", "bd_mgt_sn"):
        value = properties.get(key)
        if value not in (None, ""):
            return f"{key}:{value}"
    canonical = json.dumps(
        {
            "geometry": feature.get("geometry"),
            "properties": properties,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _cache_path(query_box: tuple[float, float, float, float]) -> Path | None:
    cache_dir = settings.vworld_cache_dir.strip()
    if not cache_dir:
        return None
    digest = hashlib.sha256(
        json.dumps(
            {
                "layer": VWORLD_LAYER,
                "box": [round(value, 7) for value in query_box],
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("ascii")
    ).hexdigest()
    return Path(cache_dir) / f"{digest}.json"


def _read_cached_features(
    query_box: tuple[float, float, float, float],
) -> list[dict] | None:
    now = time.monotonic()
    memory_key = (_cache_namespace(), query_box)
    with _memory_cache_guard:
        memory_cached = _memory_cache.get(memory_key)
        if (
            memory_cached is not None
            and now - memory_cached[0]
            <= settings.vworld_cache_ttl_hours * 3600
        ):
            return memory_cached[1]
    path = _cache_path(query_box)
    if path is None or not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        cached_at = float(payload["cachedAtEpoch"])
        features = payload["features"]
    except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError):
        return None
    if (
        payload.get("schemaVersion") != CACHE_SCHEMA_VERSION
        or not isinstance(features, list)
        or time.time() - cached_at > settings.vworld_cache_ttl_hours * 3600
    ):
        return None
    validated = [
        feature for feature in features
        if isinstance(feature, dict)
    ]
    _store_memory_cache(query_box, validated)
    return validated


def _write_cached_features(
    query_box: tuple[float, float, float, float],
    features: list[dict],
) -> None:
    _store_memory_cache(query_box, features)
    path = _cache_path(query_box)
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    try:
        temporary.write_text(
            json.dumps(
                {
                    "schemaVersion": CACHE_SCHEMA_VERSION,
                    "cachedAtEpoch": time.time(),
                    "features": features,
                },
                ensure_ascii=False,
                separators=(",", ":"),
            ),
            encoding="utf-8",
        )
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


async def _download_query_box(
    client: httpx.AsyncClient,
    base_params: dict[str, Any],
    query_box: tuple[float, float, float, float],
    semaphore: asyncio.Semaphore,
) -> list[dict]:
    min_lng, min_lat, max_lng, max_lat = query_box
    box_params = {
        **base_params,
        "geomFilter": f"BOX({min_lng},{min_lat},{max_lng},{max_lat})",
    }
    all_features: list[dict] = []
    seen_feature_ids: set[str] = set()
    page = 1
    total = 0
    async with semaphore:
        while True:
            response = await client.get(
                VWORLD_DATA_URL,
                params={**box_params, "page": page},
            )
            response.raise_for_status()
            try:
                features, total = _feature_collection(response.json())
            except ValueError as exc:
                raise RuntimeError("VWorld 건물 응답이 JSON이 아닙니다.") from exc
            if total > MAX_FEATURES:
                raise RuntimeError(
                    f"보행 회랑 한 구간의 건물이 {total}건으로 안전 조회 한도 "
                    f"{MAX_FEATURES}건을 초과했습니다."
                )
            if len(features) > PAGE_SIZE:
                raise RuntimeError(
                    "VWorld 건물 응답이 요청한 페이지 크기를 초과했습니다."
                )
            page_ids = [
                str(feature["id"])
                for feature in features
                if isinstance(feature, dict)
                and feature.get("id") not in (None, "")
            ]
            duplicate_ids = seen_feature_ids.intersection(page_ids)
            if len(page_ids) != len(set(page_ids)) or duplicate_ids:
                raise RuntimeError(
                    "VWorld 건물 페이지에 중복 feature ID가 있습니다."
                )
            seen_feature_ids.update(page_ids)
            all_features.extend(features)
            if len(all_features) > total:
                raise RuntimeError(
                    "VWorld 건물 응답의 전체 건수와 페이지 결과가 다릅니다."
                )
            if not features and len(all_features) < total:
                raise RuntimeError(
                    "VWorld 건물 페이지가 전체 건수보다 먼저 종료됐습니다."
                )
            if len(all_features) >= total:
                break
            page += 1
    await asyncio.to_thread(
        _write_cached_features,
        query_box,
        all_features,
    )
    return all_features


def _query_box_request_lock(
    query_box: tuple[float, float, float, float],
) -> asyncio.Lock:
    loop = asyncio.get_running_loop()
    key = (_cache_namespace(), query_box)
    with _request_locks_guard:
        locks = _request_locks.setdefault(loop, {})
        return locks.setdefault(key, asyncio.Lock())


async def _download_missing_query_box(
    client: httpx.AsyncClient,
    base_params: dict[str, Any],
    query_box: tuple[float, float, float, float],
    semaphore: asyncio.Semaphore,
) -> list[dict]:
    """동시 후보가 공유하는 같은 회랑 box는 공급자에 한 번만 요청한다."""
    async with _query_box_request_lock(query_box):
        cached = await asyncio.to_thread(
            _read_cached_features,
            query_box,
        )
        if cached is not None:
            return cached
        return await _download_query_box(
            client,
            base_params,
            query_box,
            semaphore,
        )


async def _warm_query_boxes(
    query_boxes: list[tuple[float, float, float, float]],
    base_params: dict[str, Any],
) -> None:
    try:
        semaphore = asyncio.Semaphore(MAX_CONCURRENT_QUERIES)
        async with httpx.AsyncClient(
            timeout=settings.request_timeout * 3,
        ) as client:
            results = await asyncio.gather(
                *(
                    _download_missing_query_box(
                        client,
                        base_params,
                        query_box,
                        semaphore,
                    )
                    for query_box in query_boxes
                ),
                return_exceptions=True,
            )
        for result in results:
            if isinstance(result, BaseException):
                log.warning(
                    "VWorld 건물 회랑 백그라운드 준비 실패 (%s)",
                    type(result).__name__,
                )
    finally:
        with _warming_boxes_guard:
            _warming_boxes.difference_update(query_boxes)


def _schedule_query_box_warm(
    query_boxes: list[tuple[float, float, float, float]],
    base_params: dict[str, Any],
) -> None:
    with _warming_boxes_guard:
        pending = [
            query_box
            for query_box in query_boxes
            if query_box not in _warming_boxes
        ]
        _warming_boxes.update(pending)
    if not pending:
        return
    task = asyncio.create_task(_warm_query_boxes(pending, base_params))
    _warm_tasks.add(task)
    task.add_done_callback(_warm_tasks.discard)


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
    raw_total = record.get("total")
    if raw_total is None:
        total = len(features)
    else:
        try:
            total = int(raw_total)
        except (TypeError, ValueError) as exc:
            raise RuntimeError(
                "VWorld 건물 응답의 전체 건수가 유효하지 않습니다."
            ) from exc
        if total < 0:
            raise RuntimeError(
                "VWorld 건물 응답의 전체 건수가 유효하지 않습니다."
            )
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
        height = validated_building_height(properties.get("height"))
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
    wait_for_complete: bool = False,
    cache_only: bool = False,
) -> dict:
    if not settings.vworld_api_key:
        raise RuntimeError("BUILDING_SOURCE=vworld requires VWORLD_API_KEY.")
    query_boxes = _route_query_boxes(routes)
    if transport is None:
        route_cached = _read_route_memory_cache(query_boxes)
        if route_cached is not None:
            return route_cached
    base_params = {
        "service": "data",
        "version": "2.0",
        "request": "GetFeature",
        "key": settings.vworld_api_key,
        "format": "json",
        "errorFormat": "json",
        "size": PAGE_SIZE,
        "data": VWORLD_LAYER,
        "columns": "ufid,height,bldrgst_pk,pnu,bd_mgt_sn",
        "geometry": "true",
        "attribute": "true",
        "crs": "EPSG:4326",
    }
    if settings.vworld_api_domain:
        base_params["domain"] = settings.vworld_api_domain

    cached_results = await asyncio.gather(*(
        asyncio.to_thread(_read_cached_features, query_box)
        for query_box in query_boxes
    ))
    query_results = [
        cached
        for cached in cached_results
        if cached is not None
    ]
    missing_boxes = [
        query_box
        for query_box, cached in zip(
            query_boxes,
            cached_results,
            strict=True,
        )
        if cached is None
    ]
    cache_complete = not missing_boxes
    if (
        missing_boxes
        and not cache_only
        and transport is None
        and not wait_for_complete
    ):
        _schedule_query_box_warm(missing_boxes, base_params)
    elif missing_boxes and not cache_only:
        try:
            async with httpx.AsyncClient(
                timeout=settings.request_timeout * 3,
                transport=transport,
            ) as client:
                semaphore = asyncio.Semaphore(MAX_CONCURRENT_QUERIES)
                query_results.extend(await asyncio.gather(*(
                    _download_missing_query_box(
                        client,
                        base_params,
                        query_box,
                        semaphore,
                    )
                    for query_box in missing_boxes
                )))
            cache_complete = True
        except httpx.HTTPStatusError as exc:
            raise RuntimeError(
                f"VWorld 건물 API가 HTTP {exc.response.status_code}를 반환했습니다."
            ) from exc
        except httpx.HTTPError as exc:
            raise RuntimeError("VWorld 건물 API 연결에 실패했습니다.") from exc

    unique_features: dict[str, dict] = {}
    for features in query_results:
        for feature in features:
            if isinstance(feature, dict):
                unique_features.setdefault(
                    _feature_identity(feature),
                    feature,
                )
    all_features = list(unique_features.values())
    buildings = _building_rows(all_features)
    building_data = {
        "schemaVersion": 1,
        "source": "VWorld LT_C_BLDGINFO WFS",
        "dataQuality": "public",
        "cacheComplete": cache_complete,
        "queryBufferM": QUERY_BUFFER_M,
        "featureCount": len(all_features),
        "buildings": buildings,
    }
    if cache_complete and transport is None:
        _store_route_memory_cache(query_boxes, building_data)
    return building_data
