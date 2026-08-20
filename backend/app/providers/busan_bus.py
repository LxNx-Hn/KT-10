"""부산 BIMS 정류소 검색·실시간 도착 프로바이더.

공식 부산버스정보시스템 XML 계약만 사용한다. 도착 분이 숫자가 아니거나
저상버스 플래그가 0/1이 아니면 값을 꾸며내지 않고 원문 상태/미확인으로 보존한다.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from math import asin, cos, radians, sin, sqrt
import re
from threading import Lock
from time import monotonic
from typing import Any

from defusedxml import ElementTree
from defusedxml.common import DefusedXmlException
import httpx

from ..models import BusArrival, BusStopArrivals
from ..settings import settings

log = logging.getLogger("providers.busan_bus")
_BASE_URL = "https://apis.data.go.kr/6260000/BusanBIMS"
_STOP_MATCH_CACHE_TTL_SECONDS = 24 * 3600
_stop_match_cache: dict[str, tuple[float, tuple[BusStopCandidate, ...]]] = {}
_stop_match_cache_guard = Lock()


@dataclass(frozen=True)
class BusStopCandidate:
    stop_id: str
    stop_name: str
    distance_m: float | None


def _text(item: Any, name: str) -> str | None:
    value = item.findtext(name)
    return value.strip() if value and value.strip() else None


def _integer(value: str | None) -> int | None:
    if value is None:
        return None
    try:
        number = int(value)
    except ValueError:
        return None
    if number < 0:
        raise RuntimeError(
            "부산 BIMS 응답에 음수 도착 지표가 포함됐습니다."
        )
    return number


def _low_floor(value: str | None) -> bool | None:
    if value == "1":
        return True
    if value == "0":
        return False
    return None


def _parse_root(content: bytes) -> Any:
    try:
        root = ElementTree.fromstring(content)
    except (ElementTree.ParseError, DefusedXmlException) as exc:
        raise RuntimeError("부산 BIMS XML 응답이 안전한 형식이 아닙니다.") from exc
    result_code = root.findtext(".//resultCode")
    if result_code != "00":
        message = root.findtext(".//resultMsg") or "응답 코드 미확인"
        raise RuntimeError(f"부산 BIMS 오류: {message}")
    return root


async def _request(path: str, params: dict[str, str | int]) -> Any:
    if not settings.live_bus:
        raise RuntimeError("부산 BIMS 서비스 키가 설정되지 않았습니다.")
    query = {"serviceKey": settings.bus_service_key, **params}
    try:
        async with httpx.AsyncClient(timeout=settings.request_timeout) as client:
            response = await client.get(f"{_BASE_URL}/{path}", params=query)
            response.raise_for_status()
        return _parse_root(response.content)
    except RuntimeError:
        raise
    except httpx.HTTPError as exc:
        log.warning("부산 BIMS 호출 실패 (%s)", type(exc).__name__)
        raise RuntimeError("부산 BIMS 호출에 실패했습니다.") from exc


async def search_bus_stops(query: str) -> list[BusStopArrivals]:
    query = query.strip()
    if not query:
        return []
    params: dict[str, str | int] = {"pageNo": 1, "numOfRows": 30}
    if query.isdigit() and len(query) == 5:
        params["arsno"] = query
    else:
        params["bstopnm"] = query
    root = await _request("busStopList", params)
    result: list[BusStopArrivals] = []
    for item in root.findall(".//item"):
        stop_id = _text(item, "bstopid")
        stop_name = _text(item, "bstopnm")
        if stop_id and stop_name:
            result.append(BusStopArrivals(stop_id=stop_id, stop_name=stop_name, arrivals=[]))
    return result


def _stop_name_key(value: str | None) -> str:
    return re.sub(r"[^0-9A-Za-z가-힣]", "", value or "").casefold()


def _coordinate(item: Any, *names: str) -> float | None:
    for name in names:
        raw = _text(item, name)
        if raw is None:
            continue
        try:
            return float(raw)
        except ValueError:
            continue
    return None


def _distance_m(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    earth_radius_m = 6_371_000.0
    d_lat = radians(lat2 - lat1)
    d_lng = radians(lng2 - lng1)
    first = sin(d_lat / 2) ** 2
    second = cos(radians(lat1)) * cos(radians(lat2)) * sin(d_lng / 2) ** 2
    return earth_radius_m * 2 * asin(sqrt(first + second))


async def find_bus_stop_candidates(
    stop_name: str,
    *,
    lat: float | None = None,
    lng: float | None = None,
) -> list[BusStopCandidate]:
    """정류소명과 경로 좌표가 함께 맞는 BIMS 정류소 후보를 가까운 순서로 찾는다."""
    query = stop_name.strip()
    expected = _stop_name_key(query)
    if not expected:
        return []
    cache_key = f"{expected}:{lat if lat is None else round(lat, 5)}:{lng if lng is None else round(lng, 5)}"
    now = monotonic()
    with _stop_match_cache_guard:
        cached = _stop_match_cache.get(cache_key)
        if cached is not None and cached[0] > now:
            return list(cached[1])
    root = await _request("busStopList", {
        "pageNo": 1,
        "numOfRows": 100,
        "bstopnm": query,
    })
    candidates: list[BusStopCandidate] = []
    for item in root.findall(".//item"):
        stop_id = _text(item, "bstopid")
        found_name = _text(item, "bstopnm")
        found_key = _stop_name_key(found_name)
        if not stop_id or not found_name or not found_key:
            continue
        if expected != found_key and expected not in found_key and found_key not in expected:
            continue
        found_lng = _coordinate(item, "gpsx", "x", "lng", "lon")
        found_lat = _coordinate(item, "gpsy", "y", "lat")
        distance = (
            _distance_m(lat, lng, found_lat, found_lng)
            if lat is not None
            and lng is not None
            and found_lat is not None
            and found_lng is not None
            else None
        )
        candidates.append(BusStopCandidate(stop_id, found_name, distance))
    exact = [item for item in candidates if _stop_name_key(item.stop_name) == expected]
    selected = exact or candidates
    selected.sort(key=lambda item: (
        item.distance_m is None,
        item.distance_m if item.distance_m is not None else float("inf"),
        item.stop_id,
    ))
    if lat is not None and lng is not None:
        nearby = [
            item for item in selected
            if item.distance_m is not None and item.distance_m <= 500
        ]
        if nearby:
            result = nearby[:5]
        else:
            result = []
    else:
        result = selected[:5] if len(selected) == 1 else []
    with _stop_match_cache_guard:
        _stop_match_cache[cache_key] = (
            monotonic() + _STOP_MATCH_CACHE_TTL_SECONDS,
            tuple(result),
        )
    return result


def clear_bus_stop_match_cache() -> None:
    with _stop_match_cache_guard:
        _stop_match_cache.clear()


def _arrival(item: Any, suffix: str) -> BusArrival | None:
    vehicle_no = _text(item, f"carno{suffix}")
    route_name = _text(item, "lineno")
    if not vehicle_no or not route_name:
        return None
    minute_text = _text(item, f"min{suffix}")
    arrival_min = _integer(minute_text)
    return BusArrival(
        route_name=route_name,
        vehicle_no=vehicle_no,
        arrival_min=arrival_min,
        arrival_message=None if arrival_min is not None else minute_text,
        remaining_stops=_integer(_text(item, f"station{suffix}")),
        is_low_floor=_low_floor(_text(item, f"lowplate{suffix}")),
    )


async def get_bus_arrivals(stop_id: str) -> BusStopArrivals:
    root = await _request("stopArrByBstopid", {"bstopid": stop_id})
    items = root.findall(".//item")
    arrivals = [arrival for item in items for suffix in ("1", "2") if (arrival := _arrival(item, suffix))]
    stop_name = next((_text(item, "nodenm") for item in items if _text(item, "nodenm")), None)
    return BusStopArrivals(stop_id=stop_id, stop_name=stop_name or stop_id, arrivals=arrivals)
