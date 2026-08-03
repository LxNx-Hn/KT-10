"""선택 경로의 버스 실시간·지하철 시간표 도착정보 지연 조회.

초기 추천에는 어떤 호출도 추가하지 않는다. 상세 화면에서 선택한 후보만
조회하며, 동일 정류장/역·분 단위 요청은 짧은 TTL 캐시와 single-flight로
합친다. 실시간 값이 없는 경우 평균 배차간격으로 도착시간을 꾸며내지 않는다.
"""
from __future__ import annotations

import asyncio
import re
from datetime import UTC, date, datetime, time, timedelta
from math import ceil
from threading import Lock
from time import monotonic
from weakref import WeakKeyDictionary
from zoneinfo import ZoneInfo

import httpx

from ..models import RouteSegment, TransitLegArrival
from ..settings import settings
from .busan_bus import get_bus_arrivals

_KST = ZoneInfo("Asia/Seoul")
_CACHE_TTL_SECONDS = 30.0
_cache: dict[str, tuple[float, TransitLegArrival]] = {}
_cache_guard = Lock()
_loop_locks: WeakKeyDictionary[
    asyncio.AbstractEventLoop,
    dict[str, asyncio.Lock],
] = WeakKeyDictionary()
_loop_locks_guard = Lock()
_TIME_PATTERN = re.compile(r"^(?:[01]\d|2[0-3]):[0-5]\d(?::[0-5]\d)?$")


def _cache_get(key: str) -> TransitLegArrival | None:
    now = monotonic()
    with _cache_guard:
        cached = _cache.get(key)
        if cached is None:
            return None
        expires_at, value = cached
        if expires_at <= now:
            _cache.pop(key, None)
            return None
        return value.model_copy(deep=True)


def _cache_put(key: str, value: TransitLegArrival) -> None:
    with _cache_guard:
        _cache[key] = (
            monotonic() + _CACHE_TTL_SECONDS,
            value.model_copy(deep=True),
        )


def _for_segment(
    cached: TransitLegArrival,
    segment: RouteSegment,
) -> TransitLegArrival:
    """공유 캐시의 도착값을 현재 경로 구간 식별자에 결합한다."""
    result = cached.model_copy(deep=True)
    result.segment_id = segment.id
    return result


def _request_lock(key: str) -> asyncio.Lock:
    loop = asyncio.get_running_loop()
    with _loop_locks_guard:
        locks = _loop_locks.setdefault(loop, {})
        return locks.setdefault(key, asyncio.Lock())


def _route_key(value: str | None) -> str:
    return re.sub(r"[^0-9A-Za-z가-힣]", "", value or "").casefold()


def _unavailable(
    segment: RouteSegment,
    message: str,
    *,
    source: str,
) -> TransitLegArrival:
    return TransitLegArrival(
        segment_id=segment.id,
        mode=segment.mode,  # type: ignore[arg-type]
        status="unavailable",
        route_name=segment.bus_route_name,
        boarding_stop_name=segment.station_name,
        direction=segment.transit_direction,
        arrival_message=message,
        observed_at=datetime.now(UTC),
        source=source,
    )


async def _bus_arrival(segment: RouteSegment) -> TransitLegArrival:
    stop_id = (segment.transit_start_id or "").strip()
    if not settings.live_bus or not stop_id:
        return _unavailable(
            segment,
            "실시간 버스 도착정보를 조회할 정류소 식별자가 없습니다.",
            source="부산광역시 부산버스정보시스템",
        )
    key = f"bus:{stop_id}:{_route_key(segment.bus_route_name)}"
    if cached := _cache_get(key):
        return _for_segment(cached, segment)
    async with _request_lock(key):
        if cached := _cache_get(key):
            return _for_segment(cached, segment)
        try:
            stop = await get_bus_arrivals(stop_id)
        except RuntimeError:
            result = _unavailable(
                segment,
                "실시간 버스 도착정보를 불러오지 못했습니다.",
                source="부산광역시 부산버스정보시스템",
            )
        else:
            expected_route = _route_key(segment.bus_route_name)
            matching = [
                item
                for item in stop.arrivals
                if expected_route and _route_key(item.route_name) == expected_route
            ]
            matching.sort(
                key=lambda item: (
                    item.arrival_min is None,
                    item.arrival_min if item.arrival_min is not None else 10**9,
                )
            )
            if not matching:
                result = _unavailable(
                    segment,
                    "현재 이 노선의 실시간 도착정보가 없습니다.",
                    source="부산광역시 부산버스정보시스템",
                )
                result.boarding_stop_name = stop.stop_name
            else:
                first = matching[0]
                result = TransitLegArrival(
                    segment_id=segment.id,
                    mode="bus",
                    status="live",
                    route_name=first.route_name,
                    boarding_stop_name=stop.stop_name,
                    arrival_min=first.arrival_min,
                    arrival_message=first.arrival_message,
                    observed_at=datetime.now(UTC),
                    source="부산광역시 부산버스정보시스템",
                )
        _cache_put(key, result)
        return result


def _service_day(value: date) -> int:
    if value.weekday() == 5:
        return 2
    if value.weekday() == 6:
        return 3
    return 1


def _parse_clock(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = value.strip()
    return cleaned if _TIME_PATTERN.fullmatch(cleaned) else None


def _minutes_until(clock: str, reference: datetime) -> int:
    parts = [int(part) for part in clock.split(":")]
    while len(parts) < 3:
        parts.append(0)
    scheduled = datetime.combine(
        reference.date(),
        time(parts[0], parts[1], parts[2]),
        tzinfo=_KST,
    )
    if scheduled < reference - timedelta(minutes=1):
        scheduled += timedelta(days=1)
    return max(0, ceil((scheduled - reference).total_seconds() / 60))


async def _subway_arrival(
    segment: RouteSegment,
    reference: datetime,
) -> TransitLegArrival:
    start_id = (segment.transit_start_id or "").strip()
    end_id = (segment.transit_end_id or "").strip()
    source = "ODsay 지하철 시간표"
    if not settings.odsay_api_key or not start_id or not end_id:
        return _unavailable(
            segment,
            "지하철 시간표를 조회할 역 식별자가 없습니다.",
            source=source,
        )
    local_reference = reference.astimezone(_KST)
    bucket = local_reference.strftime("%Y%m%d%H%M")
    key = f"subway:{start_id}:{end_id}:{bucket}"
    if cached := _cache_get(key):
        return _for_segment(cached, segment)
    async with _request_lock(key):
        if cached := _cache_get(key):
            return _for_segment(cached, segment)
        params = {
            "apiKey": settings.odsay_api_key,
            "SID": start_id,
            "EID": end_id,
            "MODE": 1,
            "DAY": _service_day(local_reference.date()),
            "TIME": local_reference.strftime("%H%M"),
            "output": "json",
        }
        try:
            async with httpx.AsyncClient(timeout=settings.request_timeout) as client:
                response = await client.get(
                    "https://api.odsay.com/v1/api/subwayPathSchedule",
                    params=params,
                )
                response.raise_for_status()
                payload = response.json()
            if not isinstance(payload, dict):
                raise TypeError("ODsay 시간표 응답이 JSON 객체가 아닙니다.")
            payload_result = payload.get("result")
            if not isinstance(payload_result, dict):
                raise TypeError("ODsay 시간표 응답에 결과 객체가 없습니다.")
            paths = payload_result.get("path")
            if not isinstance(paths, list) or not paths or not isinstance(paths[0], dict):
                raise TypeError("ODsay 시간표 응답에 경로 목록이 없습니다.")
            info = paths[0].get("info")
            if not isinstance(info, dict):
                raise TypeError("ODsay 시간표 응답에 요약 정보가 없습니다.")
            departure = _parse_clock(info.get("departureTime"))
            arrival = _parse_clock(info.get("arrivalTime"))
            if departure is None:
                raise RuntimeError("ODsay 시간표 응답에 출발시간이 없습니다.")
            result = TransitLegArrival(
                segment_id=segment.id,
                mode="subway",
                status="scheduled",
                route_name=segment.description.split(" · ", 1)[0],
                boarding_stop_name=segment.station_name,
                direction=segment.transit_direction,
                arrival_min=_minutes_until(departure, local_reference),
                departure_time=departure,
                destination_arrival_time=arrival,
                arrival_message="시간표 기준이며 실시간 열차 위치는 아닙니다.",
                observed_at=datetime.now(UTC),
                source=source,
            )
        except (httpx.HTTPError, TypeError, ValueError, RuntimeError):
            result = _unavailable(
                segment,
                "지하철 시간표를 불러오지 못했습니다.",
                source=source,
            )
        _cache_put(key, result)
        return result


async def get_route_transit_arrivals(
    segments: list[RouteSegment],
    *,
    reference: datetime | None = None,
) -> list[TransitLegArrival]:
    """선택 후보의 대중교통 구간만 병렬 조회한다."""
    observed_reference = reference or datetime.now(UTC)
    calls = [
        _bus_arrival(segment)
        if segment.mode == "bus"
        else _subway_arrival(segment, observed_reference)
        for segment in segments
        if segment.mode in {"bus", "subway"}
    ]
    return list(await asyncio.gather(*calls)) if calls else []


def clear_transit_arrival_cache() -> None:
    """테스트용 캐시 초기화."""
    with _cache_guard:
        _cache.clear()
    with _loop_locks_guard:
        _loop_locks.clear()
