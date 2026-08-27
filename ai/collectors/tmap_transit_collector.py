"""TMAP 통합 대중교통 경로 수집기.

ODsay와 무관하게 TMAP ``/transit/routes`` 응답을 내부 RouteCandidate 계약으로
정규화한다. 대중교통 passShape는 즉시 exact 선형으로 사용하고, 보행 구간은
공통 보행 해석기로 다시 검증한다.
"""
from __future__ import annotations

import asyncio
import json
import logging
import math
import re
import time
from hashlib import sha256
from pathlib import Path
from threading import Lock
from uuid import uuid4
from weakref import WeakKeyDictionary

import httpx

from collectors.base import (
    BaseRouteCollector,
    CollectorError,
    CollectorNotConfigured,
    Coordinate,
    RouteCandidate,
)
from collectors.transit_walk import TransitWalkGeometryResolver
from config import settings

CACHE_SCHEMA_VERSION = 1
BASE_URL = "https://apis.openapi.sk.com/transit/routes"
NETWORK_ATTEMPTS = 2
RETRY_DELAY_SECONDS = 0.5
RETRYABLE_HTTP_STATUSES = frozenset({408, 425, 500, 502, 503, 504})
# 이 거리를 넘는 대중교통 구간의 정점 2개짜리 선형은 실측이 아니라
# 양 끝점을 이은 표시용 직선으로 본다.
_MIN_SHAPED_TRANSIT_DISTANCE_M = 1000.0
# 도로·선로를 따라가야 하는 모드. 항공·해상은 직선이 실제 경로이므로 제외한다.
_NETWORK_BOUND_MODES = frozenset({"bus", "subway", "train", "express_bus"})
_MODE_MAP = {
    "WALK": "walk",
    "BUS": "bus",
    "SUBWAY": "subway",
    "TRAIN": "train",
    "EXPRESSBUS": "express_bus",
    "FERRY": "ferry",
    "AIRPLANE": "airplane",
}
_TRAFFIC_TYPE = {
    "subway": 1,
    "bus": 2,
    "walk": 3,
    "express_bus": 4,
    "train": 5,
    "airplane": 6,
    "ferry": 7,
}
log = logging.getLogger("collectors.tmap_transit")
_write_locks: dict[str, Lock] = {}
_write_locks_guard = Lock()
_request_locks: WeakKeyDictionary = WeakKeyDictionary()
_request_semaphores: WeakKeyDictionary = WeakKeyDictionary()
_request_state_guard = Lock()


def _response_json(response: httpx.Response) -> object:
    """TMAP 문자열의 비이스케이프 제어문자만 허용해 응답을 복구한다."""
    try:
        return response.json()
    except ValueError:
        content = getattr(response, "content", None)
        if not isinstance(content, (bytes, bytearray)):
            raise
        encoding = getattr(response, "encoding", None) or "utf-8"
        return json.loads(bytes(content).decode(encoding), strict=False)


def _cache_dir() -> Path | None:
    configured = settings.TMAP_TRANSIT_CACHE_DIR.strip()
    if configured:
        return Path(configured)
    shared = settings.TMAP_CACHE_DIR.strip()
    return Path(shared) / "transit" if shared else None


def _identity(
    origin: Coordinate,
    destination: Coordinate,
    *,
    count: int,
) -> dict:
    return {
        "origin": [round(origin.lat, 6), round(origin.lng, 6)],
        "destination": [
            round(destination.lat, 6),
            round(destination.lng, 6),
        ],
        "count": count,
        "schema": CACHE_SCHEMA_VERSION,
    }


def _cache_path(identity: dict) -> Path | None:
    directory = _cache_dir()
    if directory is None:
        return None
    digest = sha256(
        json.dumps(identity, sort_keys=True, separators=(",", ":")).encode(
            "ascii"
        )
    ).hexdigest()
    return directory / f"transit-{digest}.json"


def _read_cache(identity: dict) -> dict | None:
    path = _cache_path(identity)
    if path is None or not path.is_file():
        return None
    try:
        wrapper = json.loads(path.read_text(encoding="utf-8"))
        cached_at = float(wrapper["cachedAtEpoch"])
        payload = wrapper["payload"]
    except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError):
        return None
    if (
        wrapper.get("schemaVersion") != CACHE_SCHEMA_VERSION
        or not isinstance(payload, dict)
        or time.time() - cached_at > settings.TMAP_TRANSIT_CACHE_TTL_SECONDS
    ):
        return None
    return payload


def _write_lock(path: Path) -> Lock:
    key = str(path.resolve())
    with _write_locks_guard:
        return _write_locks.setdefault(key, Lock())


def _write_cache(identity: dict, payload: dict) -> None:
    path = _cache_path(identity)
    if path is None:
        return
    with _write_lock(path):
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
        try:
            temporary.write_text(
                json.dumps(
                    {
                        "schemaVersion": CACHE_SCHEMA_VERSION,
                        "cachedAtEpoch": time.time(),
                        "payload": payload,
                    },
                    ensure_ascii=False,
                    separators=(",", ":"),
                ),
                encoding="utf-8",
            )
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)


def _request_lock(identity: dict) -> asyncio.Lock:
    loop = asyncio.get_running_loop()
    key = json.dumps(identity, sort_keys=True, separators=(",", ":"))
    with _request_state_guard:
        locks = _request_locks.setdefault(loop, {})
        return locks.setdefault(key, asyncio.Lock())


def _request_semaphore() -> asyncio.Semaphore:
    loop = asyncio.get_running_loop()
    with _request_state_guard:
        return _request_semaphores.setdefault(
            loop,
            asyncio.Semaphore(settings.TMAP_TRANSIT_MAX_CONCURRENT_REQUESTS),
        )


def _error_code(exc: BaseException) -> str:
    if isinstance(exc, httpx.TimeoutException):
        return "timeout"
    if isinstance(exc, httpx.HTTPStatusError):
        status = exc.response.status_code
        if status in {401, 403}:
            return "auth_failed"
        if status == 429:
            return "quota_exceeded"
        if status >= 500:
            return "upstream_5xx"
        return "invalid_response"
    if isinstance(exc, httpx.TransportError):
        return "network_error"
    return "invalid_response"


def _number(
    value: object,
    field: str,
    *,
    positive: bool,
) -> float:
    if value is None or isinstance(value, bool):
        raise CollectorError(
            f"TMAP 대중교통 응답의 {field}가 비어 있습니다.",
            code="invalid_response",
        )
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise CollectorError(
            f"TMAP 대중교통 응답의 {field}가 숫자가 아닙니다.",
            code="invalid_response",
        ) from exc
    if (
        not math.isfinite(number)
        or (positive and number <= 0)
        or (not positive and number < 0)
    ):
        raise CollectorError(
            f"TMAP 대중교통 응답의 {field} 범위가 올바르지 않습니다.",
            code="invalid_response",
        )
    return number


def _integer(value: object, field: str, *, minimum: int = 0) -> int:
    number = _number(value, field, positive=False)
    if not number.is_integer() or number < minimum:
        raise CollectorError(
            f"TMAP 대중교통 응답의 {field}가 정수가 아닙니다.",
            code="invalid_response",
        )
    return int(number)


def _coordinate(value: object, field: str) -> Coordinate:
    if not isinstance(value, dict):
        raise CollectorError(
            f"TMAP 대중교통 응답의 {field} 좌표가 객체가 아닙니다.",
            code="invalid_response",
        )
    try:
        lat = float(value["lat"])
        lng = float(value["lon"])
    except (KeyError, TypeError, ValueError) as exc:
        raise CollectorError(
            f"TMAP 대중교통 응답의 {field} 좌표가 올바르지 않습니다.",
            code="invalid_response",
        ) from exc
    if not (33 <= lat <= 39 and 124 <= lng <= 132):
        raise CollectorError(
            f"TMAP 대중교통 응답의 {field} 좌표가 국내 범위 밖입니다.",
            code="invalid_response",
        )
    return Coordinate(lat=lat, lng=lng)


def _line_string(value: object) -> list[Coordinate]:
    if not isinstance(value, str) or not value.strip():
        return []
    result: list[Coordinate] = []
    for token in value.split():
        parts = token.split(",")
        if len(parts) != 2:
            return []
        try:
            point = Coordinate(lat=float(parts[1]), lng=float(parts[0]))
        except ValueError:
            return []
        if not (33 <= point.lat <= 39 and 124 <= point.lng <= 132):
            return []
        if not result or result[-1] != point:
            result.append(point)
    return result if len(result) >= 2 else []


def _merge_paths(paths: list[list[Coordinate]]) -> list[Coordinate]:
    merged: list[Coordinate] = []
    for path in paths:
        if not path:
            continue
        if merged and merged[-1] == path[0]:
            merged.extend(path[1:])
        else:
            merged.extend(path)
    return merged


def _walk_path(leg: dict) -> list[Coordinate]:
    steps = leg.get("steps")
    if isinstance(steps, list) and steps:
        merged = _merge_paths([
            _line_string(step.get("linestring"))
            for step in steps
            if isinstance(step, dict)
        ])
        if len(merged) >= 2:
            return merged
    shape = leg.get("passShape")
    if isinstance(shape, dict):
        line = _line_string(shape.get("linestring"))
        if len(line) >= 2:
            return line
    line = _line_string(leg.get("linestring"))
    if len(line) >= 2:
        return line
    return []


def _transit_path(leg: dict) -> list[Coordinate]:
    shape = leg.get("passShape")
    return _line_string(shape.get("linestring")) if isinstance(shape, dict) else []


def _has_usable_transit_shape(
    mode: str,
    path: list[Coordinate],
    distance_m: float | None,
) -> bool:
    """공급자 선형이 실제 노선을 표현하는지 판정한다.

    정류장 사이가 1km를 넘는 구간은 노선이 굽어 있고 경유 정류장도 여럿이라
    passShape 정점이 2개일 수 없다. 시외버스·광역철도처럼 공급자가 양 끝점만
    주는 구간을 exact로 두면 지형을 가로지르는 직선이 실측 선형처럼
    표시되므로 확정으로 신뢰하지 않는다.

    항공·해상 구간은 도로나 선로를 따르지 않아 두 점을 잇는 직선이 실제
    경로다. 이런 모드는 정점이 2개여도 의심하지 않는다.
    """
    if len(path) < 2:
        return False
    if len(path) > 2:
        return True
    if mode not in _NETWORK_BOUND_MODES:
        return True
    return (distance_m or 0.0) <= _MIN_SHAPED_TRANSIT_DISTANCE_M


def _pass_stations(leg: dict) -> list[dict]:
    stop_list = leg.get("passStopList")
    if not isinstance(stop_list, dict):
        return []
    # TMAP 공식 응답 샘플은 stationList를 사용한다. 기존
    # 캐시·fixture의 stations도 24시간 TTL 동안 호환한다.
    raw = stop_list.get("stationList")
    if raw is None:
        raw = stop_list.get("stations")
    return [item for item in raw if isinstance(item, dict)] if isinstance(raw, list) else []


def _first_station_id(leg: dict) -> str | None:
    stations = _pass_stations(leg)
    if not stations:
        return None
    first = stations[0]
    value = first.get("stationID")
    return str(value).strip() if value is not None and str(value).strip() else None


def _last_station_id(leg: dict) -> str | None:
    stations = _pass_stations(leg)
    if not stations:
        return None
    last = stations[-1]
    value = last.get("stationID")
    return str(value).strip() if value is not None and str(value).strip() else None


def _route_name(value: object, mode: str) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    if mode in {"bus", "express_bus"} and ":" in text:
        _, suffix = text.split(":", 1)
        return suffix.strip() or text
    return text


def _subway_code(name: str | None) -> int | None:
    if not name:
        return None
    # TMAP의 service 값은 모든 철도 운영기관에서 공유하는 일반 분류값이다.
    # 동해선·부산김해경전철에 service=1을 적용하면 부산 1호선(71)으로
    # 오인식하므로, 부산교통공사 호선명이 확인된 경우에만 코드화한다.
    if re.search(r"동해선|(?:부산\s*[-·]?\s*김해|김해)\s*경전철", name):
        return None
    matched = re.search(r"(?:부산)?\s*(?:도시철도|지하철)?\s*([1-4])\s*호선", name)
    if matched:
        return 70 + int(matched.group(1))
    matched = re.search(r"\b([1-4])\b", name)
    if matched:
        return 70 + int(matched.group(1))
    return None


def _lane_payload(leg: dict, mode: str) -> list[dict]:
    source = leg.get("Lane")
    lanes = source if isinstance(source, list) and source else [leg]
    result: list[dict] = []
    for lane in lanes:
        if not isinstance(lane, dict):
            continue
        name = _route_name(lane.get("route", leg.get("route")), mode)
        route_id = lane.get("routeId", leg.get("routeId"))
        normalized: dict[str, object] = {"name": name}
        if mode in {"bus", "express_bus"}:
            normalized.update({"busNo": name, "busID": route_id})
        elif mode == "subway":
            code = _subway_code(name)
            if code is None and name and not re.search(
                r"동해선|(?:부산\s*[-·]?\s*김해|김해)\s*경전철",
                name,
            ):
                service = leg.get("service", lane.get("service"))
                if service in (1, 2, 3, 4, "1", "2", "3", "4"):
                    code = 70 + int(service)
            normalized["subwayCode"] = code
            if code is None and route_id is not None:
                normalized["routeID"] = route_id
        elif route_id is not None:
            normalized["routeID"] = route_id
        result.append({key: value for key, value in normalized.items() if value is not None})
    return result


def _normalized_leg(leg: dict, mode: str) -> dict:
    start = leg.get("start")
    end = leg.get("end")
    start_coord = _coordinate(start, "start")
    end_coord = _coordinate(end, "end")
    stations = _pass_stations(leg)
    start_station_name = (
        str(stations[0].get("stationName") or "").strip()
        if stations and isinstance(stations[0], dict)
        else ""
    )
    end_station_name = (
        str(stations[-1].get("stationName") or "").strip()
        if stations and isinstance(stations[-1], dict)
        else ""
    )
    start_name = (
        start_station_name
        or str(start.get("name") or "").strip()
        or None
    )
    end_name = (
        end_station_name
        or str(end.get("name") or "").strip()
        or None
    )
    return {
        "trafficType": _TRAFFIC_TYPE[mode],
        "sectionTime": _number(
            leg.get("sectionTime"), "sectionTime", positive=False
        ) / 60,
        "distance": _number(leg.get("distance"), "distance", positive=False),
        "startName": start_name,
        "endName": end_name,
        "startX": start_coord.lng,
        "startY": start_coord.lat,
        "endX": end_coord.lng,
        "endY": end_coord.lat,
        "startID": _first_station_id(leg),
        "endID": _last_station_id(leg),
        "lane": _lane_payload(leg, mode) if mode != "walk" else [],
        "providerMode": str(leg.get("mode") or ""),
        "providerRouteId": leg.get("routeId"),
        "providerService": leg.get("service"),
    }


class TmapTransitRouteCollector(BaseRouteCollector):
    source_name = "tmap_transit"
    BASE_URL = BASE_URL

    def __init__(
        self,
        *,
        avoid_stairs: bool = False,
        uses_wheelchair: bool = False,
    ) -> None:
        self.avoid_stairs = avoid_stairs
        self.uses_wheelchair = uses_wheelchair
        self.walk_resolver = TransitWalkGeometryResolver(
            avoid_stairs=avoid_stairs,
            uses_wheelchair=uses_wheelchair,
        )

    @staticmethod
    def _itineraries(data: object) -> list[dict]:
        if not isinstance(data, dict):
            raise CollectorError(
                "TMAP 대중교통 응답이 JSON 객체가 아닙니다.",
                code="invalid_response",
            )
        meta = data.get("metaData")
        plan = meta.get("plan") if isinstance(meta, dict) else None
        itineraries = plan.get("itineraries") if isinstance(plan, dict) else None
        if itineraries is None:
            return []
        if not isinstance(itineraries, list):
            raise CollectorError(
                "TMAP 대중교통 후보 목록이 배열이 아닙니다.",
                code="invalid_response",
            )
        return [item for item in itineraries if isinstance(item, dict)]

    async def _candidate(
        self,
        itinerary: dict,
    ) -> RouteCandidate:
        duration = _number(
            itinerary.get("totalTime"), "totalTime", positive=True
        ) / 60
        distance = _number(
            itinerary.get("totalDistance"), "totalDistance", positive=True
        )
        transfer_count = _integer(
            itinerary.get("transferCount"), "transferCount"
        )
        total_walk = _number(
            itinerary.get("totalWalkDistance"),
            "totalWalkDistance",
            positive=False,
        )
        legs = itinerary.get("legs")
        if not isinstance(legs, list) or not legs:
            raise CollectorError(
                "TMAP 대중교통 후보에 legs가 없습니다.",
                code="invalid_response",
            )

        normalized: list[tuple[dict, str, dict]] = []
        for leg in legs:
            if not isinstance(leg, dict):
                raise CollectorError(
                    "TMAP 대중교통 leg가 객체가 아닙니다.",
                    code="invalid_response",
                )
            provider_mode = str(leg.get("mode") or "").upper()
            mode = _MODE_MAP.get(provider_mode)
            if mode is None:
                raise CollectorError(
                    f"지원하지 않는 TMAP 대중교통 mode입니다: {provider_mode!r}",
                    code="invalid_response",
                )
            normalized.append((leg, mode, _normalized_leg(leg, mode)))

        walk_requests = [
            (
                index,
                _coordinate(leg.get("start"), "start"),
                _coordinate(leg.get("end"), "end"),
            )
            for index, (leg, mode, _) in enumerate(normalized)
            if mode == "walk"
            and _number(leg.get("distance"), "distance", positive=False) > 0
            and (
                self.avoid_stairs
                or self.uses_wheelchair
                or not _walk_path(leg)
            )
        ]
        walk_results = await asyncio.gather(*(
            self.walk_resolver.resolve(start, end)
            for _, start, end in walk_requests
        ))
        walk_by_index = {
            index: value
            for (index, _, _), value in zip(walk_requests, walk_results)
        }

        segments: list[dict] = []
        combined: list[Coordinate] = []
        qualities: list[str] = []
        metrics_adjusted = False
        for index, (leg, mode, raw) in enumerate(normalized):
            section_duration = float(raw["sectionTime"])
            section_distance = float(raw["distance"])
            accessibility: dict = {}
            if mode == "walk":
                supplied_path = _walk_path(leg)
                result = walk_by_index.get(index)
                if result is not None and result.quality == "exact":
                    path = result.path
                    quality = result.quality
                    accessibility = result.accessibility_evidence
                    if result.duration_min is not None:
                        section_duration = result.duration_min
                        raw["sectionTime"] = section_duration
                        metrics_adjusted = True
                    if result.distance_m is not None:
                        section_distance = result.distance_m
                        raw["distance"] = section_distance
                        metrics_adjusted = True
                elif supplied_path:
                    path = supplied_path
                    quality = "exact"
                else:
                    start = _coordinate(leg.get("start"), "start")
                    end = _coordinate(leg.get("end"), "end")
                    path = [start, end]
                    # 같은 정류장에서 갈아타면 실제로 걷지 않는다. 공급자가
                    # 0m와 동일 좌표를 함께 준 경우 추정한 값이 하나도 없으므로
                    # 확정된 사실로 둔다. 이를 estimated로 두면 걷지 않는
                    # 구간 하나가 경로 전체의 경사·그늘을 미확인으로 만든다.
                    quality = (
                        "exact"
                        if section_distance == 0 and start == end
                        else "estimated"
                    )
            else:
                path = _transit_path(leg)
                quality = (
                    "exact"
                    if _has_usable_transit_shape(mode, path, section_distance)
                    else "estimated"
                )
                if not path:
                    path = [
                        _coordinate(leg.get("start"), "start"),
                        _coordinate(leg.get("end"), "end"),
                    ]
            if combined and combined[-1] == path[0]:
                combined.extend(path[1:])
            else:
                combined.extend(path)
            qualities.append(quality)
            segments.append({
                "mode": mode,
                "duration_min": section_duration,
                "distance_m": section_distance,
                "path": path,
                "geometry_quality": quality,
                "raw": raw,
                "accessibility_evidence": accessibility,
            })

        if metrics_adjusted:
            duration = sum(float(item["duration_min"]) for item in segments)
            distance = sum(float(item["distance_m"]) for item in segments)
            total_walk = sum(
                float(item["distance_m"])
                for item in segments
                if item["mode"] == "walk"
            )
        if len(combined) < 2:
            raise CollectorError(
                "TMAP 대중교통 후보의 geometry가 비어 있습니다.",
                code="empty_geometry",
            )
        raw_response = {
            "info": {
                "totalTime": duration,
                "totalDistance": distance,
                "totalWalk": total_walk,
                "transferCount": transfer_count,
                "payment": (
                    itinerary.get("fare", {})
                    .get("regular", {})
                    .get("totalFare")
                    if isinstance(itinerary.get("fare"), dict)
                    else None
                ),
            },
            "subPath": [item["raw"] for item in segments],
            "provider": "tmap_transit",
            "provider_response": itinerary,
        }
        geometry_quality = (
            qualities[0]
            if qualities and len(set(qualities)) == 1
            else "mixed"
        )
        return RouteCandidate(
            source=self.source_name,
            path=combined,
            duration_min=duration,
            distance_m=distance,
            raw_response=raw_response,
            segments=segments,
            geometry_quality=geometry_quality,
        )

    async def _from_payload(
        self,
        data: dict,
        *,
        max_candidates: int,
    ) -> list[RouteCandidate]:
        itineraries = self._itineraries(data)
        candidates: list[RouteCandidate] = []
        rejected: list[str] = []
        cursor = 0
        while cursor < len(itineraries) and len(candidates) < max_candidates:
            remaining = max_candidates - len(candidates)
            batch = itineraries[cursor:cursor + remaining]
            batch_start = cursor
            cursor += len(batch)
            results = await asyncio.gather(*(
                self._candidate(item) for item in batch
            ), return_exceptions=True)
            for offset, result in enumerate(results):
                if isinstance(result, CollectorError):
                    rejected.append(
                        f"{batch_start + offset + 1}번 후보: {result}"
                    )
                elif isinstance(result, BaseException):
                    raise result
                else:
                    candidates.append(result)
        if not candidates:
            suffix = f" ({'; '.join(rejected[:3])})" if rejected else ""
            raise CollectorError(
                "TMAP이 유효한 대중교통 경로를 반환하지 않았습니다." + suffix,
                code="empty_geometry",
            )
        return candidates

    async def collect(
        self,
        origin: Coordinate,
        destination: Coordinate,
        *,
        max_candidates: int | None = None,
    ) -> list[RouteCandidate]:
        api_key = settings.TMAP_API_KEY.strip()
        if not api_key or api_key.startswith("YOUR_"):
            raise CollectorNotConfigured("TMAP_API_KEY가 설정되지 않았습니다.")
        count = max_candidates or settings.TMAP_TRANSIT_MAX_CANDIDATES
        if not 1 <= count <= settings.TMAP_TRANSIT_MAX_CANDIDATES:
            raise CollectorError(
                f"요청한 후보 수 {count}개가 TMAP 상한 "
                f"{settings.TMAP_TRANSIT_MAX_CANDIDATES}개를 초과합니다.",
                code="invalid_response",
                retryable=False,
            )
        identity = _identity(origin, destination, count=count)
        cached = await asyncio.to_thread(_read_cache, identity)
        if cached is not None:
            return await self._from_payload(cached, max_candidates=count)

        async with _request_lock(identity):
            cached = await asyncio.to_thread(_read_cache, identity)
            if cached is not None:
                return await self._from_payload(cached, max_candidates=count)
            for attempt in range(NETWORK_ATTEMPTS):
                try:
                    async with _request_semaphore():
                        async with httpx.AsyncClient(
                            timeout=settings.TMAP_TRANSIT_TIMEOUT_SECONDS,
                        ) as client:
                            response = await client.post(
                                self.BASE_URL,
                                headers={
                                    "appKey": api_key,
                                    "Accept": "application/json",
                                    "Content-Type": "application/json",
                                },
                                json={
                                    "startX": str(origin.lng),
                                    "startY": str(origin.lat),
                                    "endX": str(destination.lng),
                                    "endY": str(destination.lat),
                                    "count": count,
                                    "lang": 0,
                                    "format": "json",
                                },
                            )
                    response.raise_for_status()
                    data = _response_json(response)
                    # 파싱 가능한 후보가 하나 이상일 때만 성공 응답을 캐시한다.
                    candidates = await self._from_payload(
                        data,
                        max_candidates=count,
                    )
                    try:
                        await asyncio.to_thread(_write_cache, identity, data)
                    except OSError as exc:
                        log.warning(
                            "TMAP 대중교통 캐시 저장 실패 (%s)",
                            type(exc).__name__,
                        )
                    return candidates
                except CollectorError:
                    raise
                except httpx.HTTPStatusError as exc:
                    status = exc.response.status_code
                    if (
                        status in RETRYABLE_HTTP_STATUSES
                        and attempt + 1 < NETWORK_ATTEMPTS
                    ):
                        log.warning(
                            "TMAP 대중교통 일시 응답 실패 HTTP %d, 1회 재시도",
                            status,
                        )
                        await asyncio.sleep(RETRY_DELAY_SECONDS)
                        continue
                    raise CollectorError(
                        f"TMAP 대중교통 호출 실패: HTTP {status}",
                        code=_error_code(exc),
                    ) from exc
                except (httpx.HTTPError, ValueError, TypeError) as exc:
                    if attempt + 1 < NETWORK_ATTEMPTS:
                        log.warning(
                            "TMAP 대중교통 일시 응답 처리 실패 (%s), 1회 재시도",
                            type(exc).__name__,
                        )
                        await asyncio.sleep(RETRY_DELAY_SECONDS)
                        continue
                    raise CollectorError(
                        "TMAP 대중교통 호출 또는 응답 처리 실패: "
                        f"{type(exc).__name__}",
                        code=_error_code(exc),
                    ) from exc
            raise AssertionError(
                "TMAP 대중교통 재시도 루프가 결과 없이 종료되었습니다."
            )
