"""선택 경로의 버스 실시간·철도 시간표 도착정보 지연 조회.

초기 추천에는 어떤 호출도 추가하지 않는다. 상세 화면에서 선택한 후보만
조회하며, 동일 정류장/역·분 단위 요청은 짧은 TTL 캐시와 single-flight로
합친다. 실시간 값이 없는 경우 평균 배차간격으로 도착시간을 꾸며내지 않는다.
"""
from __future__ import annotations

import asyncio
import re
from datetime import UTC, datetime
from math import floor
from threading import Lock
from time import monotonic
from weakref import WeakKeyDictionary
from zoneinfo import ZoneInfo

from ..models import BusStopArrivals, RouteSegment, TransitLegArrival
from ..settings import settings
from .busan_bus import (
    clear_bus_stop_match_cache,
    find_bus_stop_candidates,
    get_bus_arrivals,
)
from .busan_subway import (
    SubwayTimetableError,
    clear_subway_timetable_cache,
    get_next_subway_journey,
)
from .busan_subway_stations import boards_at_origin_terminal

_KST = ZoneInfo("Asia/Seoul")
_EXTERNAL_SUBWAY_PATTERN = re.compile(
    r"동해선|(?:부산\s*[-·]?\s*김해|김해)\s*경전철",
    re.IGNORECASE,
)
_CACHE_TTL_SECONDS = 30.0
_cache: dict[str, tuple[float, TransitLegArrival]] = {}
_cache_guard = Lock()
_loop_locks: WeakKeyDictionary[
    asyncio.AbstractEventLoop,
    dict[str, asyncio.Lock],
] = WeakKeyDictionary()
_loop_locks_guard = Lock()


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


def _minutes_until(remaining_seconds: float) -> int:
    """남은 시간을 표시용 분으로 환산한다.

    1분 미만은 반올림하지 않고 0으로 내린다. 표시 계층이 0을 "곧 도착/출발"로
    쓰기 때문이며, 초 단위 잔여시간은 화면에 노출하지 않는다.
    """
    if remaining_seconds < 60:
        return 0
    return floor(remaining_seconds / 60 + 0.5)


def _subway_boarding_kind(
    start_name: str,
    end_name: str,
    route_id: str,
) -> str | None:
    """승차역이 시발역이면 origin, 중간역이면 intermediate를 반환한다."""
    try:
        boards_at_origin = boards_at_origin_terminal(
            start_name,
            end_name,
            route_id or None,
        )
    except ValueError:
        return None
    return "origin" if boards_at_origin else "intermediate"


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


async def _bus_stop_arrival(stop_id: str) -> BusStopArrivals | None:
    """한 BIMS 정류소의 도착판을 조회한다. 개별 실패는 후보 비교에서 제외한다."""
    try:
        return await get_bus_arrivals(stop_id)
    except RuntimeError:
        return None


async def _bus_arrival(segment: RouteSegment) -> TransitLegArrival:
    stop_id = (segment.transit_start_id or "").strip()
    path_start = segment.path[0] if segment.path else None
    if not settings.live_bus or not segment.station_name or path_start is None:
        return _unavailable(
            segment,
            "실시간 버스 도착정보를 조회할 정류소 식별자가 없습니다.",
            source="부산광역시 부산버스정보시스템",
        )
    location_key = (
        f"{round(path_start.lat, 5)}:{round(path_start.lng, 5)}"
        if path_start is not None
        else ""
    )
    key = (
        f"bus:{stop_id}:{_route_key(segment.station_name)}:"
        f"{location_key}:{_route_key(segment.bus_route_name)}"
    )
    if cached := _cache_get(key):
        return _for_segment(cached, segment)
    async with _request_lock(key):
        if cached := _cache_get(key):
            return _for_segment(cached, segment)
        expected_route = _route_key(segment.bus_route_name)
        matched_stops = await find_bus_stop_candidates(
            segment.station_name,
            lat=path_start.lat,
            lng=path_start.lng,
        )
        if not matched_stops:
            result = _unavailable(
                segment,
                "탑승 정류장을 확인할 수 없습니다.",
                source="부산광역시 부산버스정보시스템",
            )
            _cache_put(key, result)
            return result
        stop_results = await asyncio.gather(*(
            _bus_stop_arrival(candidate.stop_id)
            for candidate in matched_stops
        ))
        resolved = list(zip(matched_stops, stop_results, strict=True))
        available = [(candidate, stop) for candidate, stop in resolved if stop is not None]
        matches = [
            (candidate, stop, arrival)
            for candidate, stop in available
            for arrival in stop.arrivals
            if expected_route and _route_key(arrival.route_name) == expected_route
        ]
        matches.sort(key=lambda item: (
            item[0].distance_m if item[0].distance_m is not None else float("inf"),
            item[2].arrival_min is None,
            item[2].arrival_min if item[2].arrival_min is not None else 10**9,
        ))
        if not available:
            result = _unavailable(
                segment,
                "실시간 버스 도착정보를 불러오지 못했습니다.",
                source="부산광역시 부산버스정보시스템",
            )
        elif not matches:
            # BIMS가 정상이지만 이 노선의 차량 ETA가 없다는 뜻이다. 배차 없음으로
            # 단정하지 않으며, 평균 배차시간도 만들지 않는다.
            nearest_candidate, nearest_stop = available[0]
            result = _unavailable(
                segment,
                "도착 예정 정보 없음",
                source="부산광역시 부산버스정보시스템",
            )
            result.boarding_stop_name = nearest_stop.stop_name
            result.boarding_stop_id = nearest_candidate.stop_id
        else:
            candidate, stop, first = matches[0]
            result = TransitLegArrival(
                segment_id=segment.id,
                mode="bus",
                status="live",
                route_name=first.route_name,
                boarding_stop_name=stop.stop_name,
                boarding_stop_id=candidate.stop_id,
                arrival_min=first.arrival_min,
                arrival_message=first.arrival_message,
                is_low_floor=first.is_low_floor,
                observed_at=datetime.now(UTC),
                source="부산광역시 부산버스정보시스템",
            )
        _cache_put(key, result)
        return result


async def _subway_arrival(
    segment: RouteSegment,
    reference: datetime,
) -> TransitLegArrival:
    start_name = (segment.station_name or "").strip()
    end_name = (segment.end_station_name or "").strip()
    source = "부산교통공사 도시철도 시간표"
    if segment.mode == "train":
        return _unavailable(
            segment,
            "TMAP 열차 구간의 실시간·시간표 공급원이 아직 연결되지 않았습니다.",
            source="철도 도착정보 공급원 미연계",
        )
    route_context = " ".join(
        value
        for value in (
            segment.transit_route_id,
            segment.description,
            segment.station_name,
            segment.end_station_name,
        )
        if value
    )
    if _EXTERNAL_SUBWAY_PATTERN.search(route_context):
        return _unavailable(
            segment,
            "동해선·부산김해경전철 실시간·시간표 공급원이 아직 연결되지 않았습니다.",
            source="철도 도착정보 공급원 미연계",
        )
    if not settings.live_subway_timetable or not start_name or not end_name:
        return _unavailable(
            segment,
            "지하철 시간표를 조회할 역 이름 또는 공공데이터 인증키가 없습니다.",
            source=source,
        )
    local_reference = reference.astimezone(_KST)
    bucket = local_reference.strftime("%Y%m%d%H%M")
    route_id = (segment.transit_route_id or "").strip()
    key = (
        f"subway:{_route_key(start_name)}:{_route_key(end_name)}:"
        f"{_route_key(route_id)}:{bucket}"
    )
    if cached := _cache_get(key):
        return _for_segment(cached, segment)
    async with _request_lock(key):
        if cached := _cache_get(key):
            return _for_segment(cached, segment)
        try:
            journey = await get_next_subway_journey(
                start_name,
                end_name,
                local_reference,
                route_id,
            )
            result = TransitLegArrival(
                segment_id=segment.id,
                mode=segment.mode,  # type: ignore[arg-type]
                status="scheduled",
                route_name=segment.description.split(" · ", 1)[0],
                boarding_stop_name=segment.station_name,
                direction=segment.transit_direction,
                boarding_kind=_subway_boarding_kind(start_name, end_name, route_id),
                arrival_min=_minutes_until(
                    (journey.departure_at - local_reference).total_seconds()
                ),
                departure_time=journey.departure_time,
                destination_arrival_time=journey.destination_arrival_time,
                arrival_message="시간표 기준이며 실시간 열차 위치는 아닙니다.",
                observed_at=datetime.now(UTC),
                source=source,
            )
        except SubwayTimetableError as exc:
            result = _unavailable(
                segment,
                exc.public_message,
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
        if segment.mode in {"bus", "subway", "train"}
    ]
    return list(await asyncio.gather(*calls)) if calls else []


def clear_transit_arrival_cache() -> None:
    """테스트용 캐시 초기화."""
    with _cache_guard:
        _cache.clear()
    with _loop_locks_guard:
        _loop_locks.clear()
    clear_bus_stop_match_cache()
    clear_subway_timetable_cache()
