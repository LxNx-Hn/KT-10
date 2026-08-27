"""부산 BIMS 정적 노선 보완 수집기.

TMAP이 반환한 후보를 대체하지 않고, TMAP 후보 목록에 빠진 부산 시내버스
직행만 공식 BIMS 노선 순서로 보완한다. BIMS에는 도로 선형이 없으므로
정류장 중심 연결선은 ``estimated``로 공개하며, 확인할 수 없는 시간값은
임의로 0으로 바꾸지 않고 해당 후보를 제외한다.
"""
from __future__ import annotations

import asyncio
import json
import logging
import math
import time
from pathlib import Path

import httpx
from defusedxml import ElementTree

from collectors.base import (
    BaseRouteCollector,
    CollectorError,
    CollectorNotConfigured,
    Coordinate,
    RouteCandidate,
)
from config import settings

_BASE_URL = "https://apis.data.go.kr/6260000/BusanBIMS"
_MAX_STOP_DISTANCE_M = 500.0
_DISCOVERY_STOP_DISTANCE_M = 1_500.0
_STOP_SNAPSHOT = Path(__file__).resolve().parents[2] / "data" / "ai" / "busan_bus_stops.json"
log = logging.getLogger("collectors.bims_transit")
_route_cache: dict[str, list[dict[str, str]]] = {}
_route_cache_loaded_at: dict[str, float] = {}
_catalog_lock: asyncio.Lock | None = None
_stop_coordinates: dict[str, Coordinate] | None = None


def _distance_m(left: Coordinate, right: Coordinate) -> float:
    lat1, lon1 = math.radians(left.lat), math.radians(left.lng)
    lat2, lon2 = math.radians(right.lat), math.radians(right.lng)
    dlat, dlon = lat2 - lat1, lon2 - lon1
    a = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 6_371_000.0 * 2 * math.asin(math.sqrt(a))


def _number(value: object) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) and parsed >= 0 else None


def _xml_items(content: bytes) -> list[dict[str, str]]:
    try:
        root = ElementTree.fromstring(content)
    except ElementTree.ParseError as exc:
        raise CollectorError("BIMS XML 응답을 해석할 수 없습니다.", code="invalid_response") from exc
    if root.findtext(".//resultCode") != "00":
        raise CollectorError(
            "BIMS가 정상 응답 코드를 반환하지 않았습니다.", code="provider_error"
        )
    return [
        {child.tag: child.text.strip() if child.text else "" for child in item}
        for item in root.findall(".//item")
    ]


class BimsTransitRouteCollector(BaseRouteCollector):
    source_name = "bims_transit"

    async def _get(self, client: httpx.AsyncClient, path: str, params: dict[str, object]) -> list[dict[str, str]]:
        query = {"serviceKey": settings.BUS_SERVICE_KEY, **params}
        response = await client.get(f"{_BASE_URL}/{path}", params=query)
        response.raise_for_status()
        return _xml_items(response.content)

    @staticmethod
    def _nearby_ars(
        point: Coordinate,
        *,
        max_distance_m: float = _MAX_STOP_DISTANCE_M,
    ) -> list[str]:
        try:
            rows = json.loads(_STOP_SNAPSHOT.read_text(encoding="utf-8"))["stops"]
        except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
            raise CollectorError("BIMS 정류소 인덱스를 읽을 수 없습니다.", code="invalid_response") from exc
        candidates = []
        for row in rows:
            ars = str(row.get("arsNo") or "").strip()
            if not ars:
                continue
            try:
                stop = Coordinate(float(row["lat"]), float(row["lng"]))
            except (KeyError, TypeError, ValueError):
                continue
            distance = _distance_m(point, stop)
            if distance <= max_distance_m:
                candidates.append((distance, ars))
        return list(dict.fromkeys(ars for _, ars in sorted(candidates)[:4]))

    @staticmethod
    def _snapshot_coordinates() -> dict[str, Coordinate]:
        global _stop_coordinates
        if _stop_coordinates is not None:
            return _stop_coordinates
        try:
            rows = json.loads(_STOP_SNAPSHOT.read_text(encoding="utf-8"))["stops"]
            _stop_coordinates = {
                str(row["id"]): Coordinate(float(row["lat"]), float(row["lng"]))
                for row in rows
            }
        except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
            raise CollectorError("BIMS 정류소 인덱스를 읽을 수 없습니다.", code="invalid_response") from exc
        return _stop_coordinates

    async def _load_routes(self, line_ids: set[str]) -> list[dict]:
        global _catalog_lock
        if not line_ids:
            return []
        if _catalog_lock is None:
            _catalog_lock = asyncio.Lock()
        async with _catalog_lock:
            now = time.time()
            missing = [
                line_id
                for line_id in line_ids
                if line_id not in _route_cache
                or now - _route_cache_loaded_at.get(line_id, 0) > settings.BIMS_CACHE_TTL_SECONDS
            ]
            if missing:
                timeout = httpx.Timeout(settings.BIMS_TIMEOUT_SECONDS)
                async with httpx.AsyncClient(timeout=timeout) as client:
                    semaphore = asyncio.Semaphore(settings.BIMS_MAX_CONCURRENT_REQUESTS)

                    async def fetch(line_id: str) -> tuple[str, list[dict[str, str]]]:
                        async with semaphore:
                            try:
                                return line_id, await self._get(
                                    client,
                                    "busInfoByRouteId",
                                    {"lineid": line_id, "numOfRows": 300, "pageNo": 1, "resultType": "xml"},
                                )
                            except (httpx.HTTPError, CollectorError) as exc:
                                log.warning("BIMS 노선 조회 실패 lineid=%s (%s)", line_id, type(exc).__name__)
                                return line_id, []

                    for line_id, rows in await asyncio.gather(*(fetch(line_id) for line_id in missing)):
                        _route_cache[line_id] = rows
                        _route_cache_loaded_at[line_id] = time.time()
        return [{"lineid": line_id, "stops": _route_cache[line_id]} for line_id in line_ids if _route_cache.get(line_id)]

    async def _discover_routes(self, origin: Coordinate, destination: Coordinate) -> list[dict]:
        timeout = httpx.Timeout(settings.BIMS_TIMEOUT_SECONDS)
        origin_ars = self._nearby_ars(origin)
        # 캠퍼스·대학 내부 목적지는 가장 가까운 정류소에 ARS가 없을 수
        # 있어 노선 발견 범위만 넓힌다. 실제 하차 후보 허용 거리는
        # _candidate의 500m 검사를 그대로 유지한다.
        destination_ars = self._nearby_ars(
            destination,
            max_distance_m=_DISCOVERY_STOP_DISTANCE_M,
        )
        if not origin_ars or not destination_ars:
            return []
        async with httpx.AsyncClient(timeout=timeout) as client:
            semaphore = asyncio.Semaphore(min(4, settings.BIMS_MAX_CONCURRENT_REQUESTS))

            async def routes_at(ars: str) -> set[str]:
                async with semaphore:
                    try:
                        rows = await self._get(client, "bitArrByArsno", {"arsno": ars, "resultType": "xml"})
                    except (httpx.HTTPError, CollectorError) as exc:
                        log.warning("BIMS 정류소 노선 조회 실패 arsno=%s (%s)", ars, type(exc).__name__)
                        return set()
                    return {row["lineid"].strip() for row in rows if row.get("lineid", "").strip()}

            origin_sets = await asyncio.gather(*(routes_at(ars) for ars in origin_ars))
            destination_sets = await asyncio.gather(*(routes_at(ars) for ars in destination_ars))
        origin_routes = set().union(*(set(rows) for rows in origin_sets))
        destination_routes = set().union(*(set(rows) for rows in destination_sets))
        return await self._load_routes(origin_routes & destination_routes)

    @staticmethod
    def _candidate(route: dict, origin: Coordinate, destination: Coordinate) -> RouteCandidate | None:
        stops = route.get("stops")
        if not isinstance(stops, list):
            return None
        parsed: list[dict] = []
        for row in stops:
            try:
                index = int(row["bstopidx"])
                point = Coordinate(float(row["lat"]), float(row["lin"]))
            except (KeyError, TypeError, ValueError):
                point = BimsTransitRouteCollector._snapshot_coordinates().get(str(row.get("nodeid") or ""))
                try:
                    index = int(row["bstopidx"])
                except (KeyError, TypeError, ValueError):
                    continue
                if point is None:
                    continue
            if not (33 <= point.lat <= 39 and 124 <= point.lng <= 132):
                continue
            parsed.append({"index": index, "point": point, "row": row})
        if len(parsed) < 2:
            return None
        boarding = min(parsed, key=lambda item: _distance_m(origin, item["point"]))
        if _distance_m(origin, boarding["point"]) > _MAX_STOP_DISTANCE_M:
            return None
        destination_options = [
            item for item in parsed
            if item["index"] > boarding["index"]
            and _distance_m(destination, item["point"]) <= _MAX_STOP_DISTANCE_M
        ]
        if not destination_options:
            return None
        alighting = min(destination_options, key=lambda item: _distance_m(destination, item["point"]))
        ride_stops = [item for item in parsed if boarding["index"] <= item["index"] <= alighting["index"]]
        ride_stops.sort(key=lambda item: item["index"])
        if len(ride_stops) < 2:
            return None
        ride_seconds = [_number(item["row"].get("avgym")) for item in ride_stops[:-1]]
        if any(value is None or value <= 0 for value in ride_seconds):
            return None
        walk_to = _distance_m(origin, boarding["point"])
        walk_from = _distance_m(alighting["point"], destination)
        walk_speed = settings.BIMS_WALK_SPEED_M_PER_MIN
        bus_duration = sum(ride_seconds) / 60
        walk_duration = (walk_to + walk_from) / walk_speed
        bus_distance = sum(_distance_m(a["point"], b["point"]) for a, b in zip(ride_stops, ride_stops[1:]))
        route_name = route.get("metadata", {}).get("buslinenum") or ride_stops[0]["row"].get("lineno")
        raw_bus = {
            "trafficType": 2,
            "sectionTime": bus_duration,
            "distance": bus_distance,
            "startName": boarding["row"].get("bstopnm"),
            "endName": alighting["row"].get("bstopnm"),
            "startID": boarding["row"].get("nodeid"),
            "endID": alighting["row"].get("nodeid"),
            "startX": boarding["point"].lng,
            "startY": boarding["point"].lat,
            "endX": alighting["point"].lng,
            "endY": alighting["point"].lat,
            "lane": [{"name": route_name, "busNo": route_name, "busID": route["lineid"]}],
            "provider": "bims_transit",
        }
        walk_a = {"trafficType": 3, "sectionTime": walk_to / walk_speed, "distance": walk_to}
        walk_b = {"trafficType": 3, "sectionTime": walk_from / walk_speed, "distance": walk_from}
        segments = [
            {"mode": "walk", "duration_min": walk_to / walk_speed, "distance_m": walk_to, "path": [origin, boarding["point"]], "geometry_quality": "estimated", "raw": walk_a},
            {"mode": "bus", "duration_min": bus_duration, "distance_m": bus_distance, "path": [item["point"] for item in ride_stops], "geometry_quality": "estimated", "raw": raw_bus},
            {"mode": "walk", "duration_min": walk_from / walk_speed, "distance_m": walk_from, "path": [alighting["point"], destination], "geometry_quality": "estimated", "raw": walk_b},
        ]
        return RouteCandidate(
            source="bims_transit",
            path=[point for segment in segments for point in segment["path"]],
            duration_min=walk_duration + bus_duration,
            distance_m=walk_to + bus_distance + walk_from,
            raw_response={
                "info": {"totalTime": walk_duration + bus_duration, "totalDistance": walk_to + bus_distance + walk_from, "totalWalk": walk_to + walk_from, "transferCount": 0},
                "subPath": [segment["raw"] for segment in segments],
                "provider": "bims_transit",
            },
            segments=segments,
            geometry_quality="estimated",
        )

    async def collect(self, origin: Coordinate, destination: Coordinate, *, max_candidates: int | None = None) -> list[RouteCandidate]:
        if not settings.BUS_SERVICE_KEY.strip() or settings.BUS_SERVICE_KEY.startswith("YOUR_"):
            raise CollectorNotConfigured("BUS_SERVICE_KEY가 설정되지 않았습니다.")
        try:
            routes = await self._discover_routes(origin, destination)
        except (httpx.HTTPError, CollectorError) as exc:
            log.warning("BIMS 보조 후보를 사용할 수 없습니다 (%s)", type(exc).__name__)
            return []
        candidates = [
            candidate
            for route in routes
            if (candidate := self._candidate(route, origin, destination)) is not None
        ]
        candidates.sort(key=lambda candidate: (candidate.duration_min or float("inf"), candidate.distance_m))
        return candidates[: max_candidates or settings.BIMS_MAX_CANDIDATES]
