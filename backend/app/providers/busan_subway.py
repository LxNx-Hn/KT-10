"""부산교통공사 도시철도 운행시각표 공공데이터 프로바이더."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
import logging
import re
from threading import Lock
from time import monotonic
from weakref import WeakKeyDictionary
from zoneinfo import ZoneInfo

import httpx

from ..settings import settings
from .busan_subway_stations import (
    journey_direction,
    public_station_name,
    resolve_line,
)

log = logging.getLogger("providers.busan_subway")
_BASE_URL = "https://apis.data.go.kr/B551542/trainTime/getTrainTime"
_KST = ZoneInfo("Asia/Seoul")
_PAGE_SIZE = 1000
_CACHE_TTL_SECONDS = 6 * 3600
_MAX_JOURNEY_DURATION = timedelta(hours=3)
_TIME_PATTERN = re.compile(r"^(?:[01]\d|2[0-3]):[0-5]\d:[0-5]\d$")
_cache: dict[str, tuple[float, tuple[dict[str, str], ...]]] = {}
_cache_guard = Lock()
_loop_locks: WeakKeyDictionary[
    asyncio.AbstractEventLoop,
    dict[str, asyncio.Lock],
] = WeakKeyDictionary()
_loop_locks_guard = Lock()


@dataclass(frozen=True)
class SubwayJourney:
    departure_time: str
    destination_arrival_time: str
    departure_at: datetime
    destination_arrival_at: datetime


class SubwayTimetableError(RuntimeError):
    """공개 응답에 안전하게 사용할 실패 분류와 문구."""

    def __init__(self, code: str, public_message: str) -> None:
        super().__init__(public_message)
        self.code = code
        self.public_message = public_message


def service_day(value: date) -> int:
    if value.weekday() == 5:
        return 2
    if value.weekday() == 6:
        return 3
    return 1


def _station_query(value: str | None) -> str:
    cleaned = (value or "").strip()
    if len(cleaned) > 1 and cleaned.endswith("역"):
        cleaned = cleaned[:-1]
    return cleaned


def _request_lock(key: str) -> asyncio.Lock:
    loop = asyncio.get_running_loop()
    with _loop_locks_guard:
        locks = _loop_locks.setdefault(loop, {})
        return locks.setdefault(key, asyncio.Lock())


def _cache_get(key: str) -> list[dict[str, str]] | None:
    now = monotonic()
    with _cache_guard:
        cached = _cache.get(key)
        if cached is None:
            return None
        expires_at, rows = cached
        if expires_at <= now:
            _cache.pop(key, None)
            return None
        return [dict(row) for row in rows]


def _cache_put(key: str, rows: list[dict[str, str]]) -> None:
    with _cache_guard:
        _cache[key] = (
            monotonic() + _CACHE_TTL_SECONDS,
            tuple(dict(row) for row in rows),
        )


def _parse_page(payload: object) -> tuple[list[dict[str, str]], int]:
    if not isinstance(payload, dict):
        raise RuntimeError("도시철도 시간표 응답이 JSON 객체가 아닙니다.")
    header = payload.get("header")
    if not isinstance(header, dict) or str(header.get("resultCode")) != "00":
        raise RuntimeError("도시철도 시간표 API가 정상 응답을 반환하지 않았습니다.")
    body = payload.get("body")
    if not isinstance(body, dict):
        raise RuntimeError("도시철도 시간표 응답에 body가 없습니다.")
    try:
        total_count = int(body.get("totalCount", 0))
    except (TypeError, ValueError) as exc:
        raise RuntimeError("도시철도 시간표 전체 건수가 올바르지 않습니다.") from exc
    items = body.get("items")
    if items in (None, ""):
        return [], total_count
    if not isinstance(items, dict):
        raise RuntimeError("도시철도 시간표 항목 컨테이너가 올바르지 않습니다.")
    raw_rows = items.get("item", [])
    if isinstance(raw_rows, dict):
        raw_rows = [raw_rows]
    if not isinstance(raw_rows, list):
        raise RuntimeError("도시철도 시간표 항목 목록이 올바르지 않습니다.")
    rows: list[dict[str, str]] = []
    required = ("sname", "line", "trainno", "arrtime", "dayType", "updown")
    for raw in raw_rows:
        if not isinstance(raw, dict):
            continue
        row = {name: str(raw.get(name, "")).strip() for name in required}
        row["endcode"] = str(raw.get("endcode", "")).strip()
        if (
            all(row[name] for name in required)
            and _TIME_PATTERN.fullmatch(row["arrtime"])
        ):
            rows.append(row)
    return rows, total_count


async def _fetch_station_schedule(station_name: str, day_type: int) -> list[dict[str, str]]:
    station = _station_query(station_name)
    if not settings.live_subway_timetable or not station:
        raise SubwayTimetableError(
            "not_configured",
            "도시철도 시간표 설정을 확인할 수 없습니다.",
        )
    key = f"{station}:{day_type}"
    if cached := _cache_get(key):
        return cached
    async with _request_lock(key):
        if cached := _cache_get(key):
            return cached
        page = 1
        rows: list[dict[str, str]] = []
        while True:
            params = {
                "serviceKey": settings.data_go_kr_service_key,
                "pageNo": page,
                "numOfRows": _PAGE_SIZE,
                "_type": "json",
                "sname": station,
                "dayType": day_type,
            }
            try:
                async with httpx.AsyncClient(timeout=settings.request_timeout) as client:
                    response = await client.get(_BASE_URL, params=params)
                    response.raise_for_status()
                    payload = response.json()
            except (httpx.HTTPError, ValueError) as exc:
                log.warning("부산 도시철도 시간표 호출 실패 (%s)", type(exc).__name__)
                raise SubwayTimetableError(
                    "provider_unavailable",
                    "부산교통공사 시간표에 연결할 수 없습니다.",
                ) from exc
            page_rows, total_count = _parse_page(payload)
            rows.extend(page_rows)
            if page * _PAGE_SIZE >= total_count or not page_rows:
                break
            page += 1
        exact = [
            row for row in rows
            if _station_query(row["sname"]) == station
            and row["dayType"] == str(day_type)
        ]
        if not exact:
            raise SubwayTimetableError(
                "station_not_found",
                f"{station} 역의 공공 운행시간표를 확인할 수 없습니다.",
            )
        _cache_put(key, exact)
        return exact


def _clock_at(service_date: date, value: str) -> datetime:
    hour, minute, second = (int(part) for part in value.split(":"))
    return datetime.combine(service_date, time(hour, minute, second), tzinfo=_KST)


def _find_journey(
    start_rows: list[dict[str, str]],
    end_rows: list[dict[str, str]],
    *,
    service_date: date,
    reference: datetime,
    line: str,
    direction: str,
) -> SubwayJourney | None:
    destinations: dict[tuple[str, str, str, str, str], list[dict[str, str]]] = {}
    for row in end_rows:
        if row["line"] != line or row["updown"] != direction:
            continue
        identity = (
            row["line"], row["trainno"], row["dayType"], row["updown"], row["endcode"]
        )
        destinations.setdefault(identity, []).append(row)
    candidates: list[SubwayJourney] = []
    for start in start_rows:
        if start["line"] != line or start["updown"] != direction:
            continue
        identity = (
            start["line"],
            start["trainno"],
            start["dayType"],
            start["updown"],
            start["endcode"],
        )
        departure_at = _clock_at(service_date, start["arrtime"])
        if departure_at < reference - timedelta(minutes=1):
            continue
        for destination in destinations.get(identity, []):
            destination_at = _clock_at(service_date, destination["arrtime"])
            if destination_at < departure_at:
                destination_at += timedelta(days=1)
            journey_duration = destination_at - departure_at
            if (
                journey_duration <= timedelta(0)
                or journey_duration > _MAX_JOURNEY_DURATION
            ):
                continue
            candidates.append(SubwayJourney(
                departure_time=start["arrtime"],
                destination_arrival_time=destination["arrtime"],
                departure_at=departure_at,
                destination_arrival_at=destination_at,
            ))
    return min(candidates, key=lambda item: item.departure_at, default=None)


async def get_next_subway_journey(
    start_station_name: str,
    end_station_name: str,
    reference: datetime,
    route_id: object = None,
) -> SubwayJourney:
    """같은 열차가 두 역을 순서대로 통과하는 가장 이른 시간표를 반환한다."""
    local_reference = reference.astimezone(_KST)
    try:
        line = resolve_line(
            start_station_name,
            end_station_name,
            route_id,
        )
        start_public_name = public_station_name(start_station_name, line)
        end_public_name = public_station_name(end_station_name, line)
        direction = journey_direction(
            start_station_name,
            end_station_name,
            line,
        )
    except ValueError as exc:
        raise SubwayTimetableError(
            "station_mapping_failed",
            "도시철도 노선과 승·하차역을 정확히 확인할 수 없습니다.",
        ) from exc
    for day_offset in (0, 1):
        service_date = local_reference.date() + timedelta(days=day_offset)
        day_type = service_day(service_date)
        try:
            start_rows, end_rows = await asyncio.gather(
                _fetch_station_schedule(start_public_name, day_type),
                _fetch_station_schedule(end_public_name, day_type),
            )
        except SubwayTimetableError:
            raise
        except RuntimeError as exc:
            raise SubwayTimetableError(
                "provider_response_invalid",
                "부산교통공사 시간표 응답을 확인할 수 없습니다.",
            ) from exc
        journey = _find_journey(
            start_rows,
            end_rows,
            service_date=service_date,
            reference=local_reference,
            line=line,
            direction=direction,
        )
        if journey is not None:
            return journey
    raise SubwayTimetableError(
        "no_upcoming_journey",
        "현재 시각 이후의 순방향 도시철도 시간표가 없습니다.",
    )


def clear_subway_timetable_cache() -> None:
    with _cache_guard:
        _cache.clear()
    with _loop_locks_guard:
        _loop_locks.clear()
