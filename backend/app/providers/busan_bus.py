"""부산 BIMS 정류소 검색·실시간 도착 프로바이더.

공식 부산버스정보시스템 XML 계약만 사용한다. 도착 분이 숫자가 아니거나
저상버스 플래그가 0/1이 아니면 값을 꾸며내지 않고 원문 상태/미확인으로 보존한다.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
import json
from math import asin, cos, radians, sin, sqrt
from pathlib import Path
import re
from typing import Any

from defusedxml import ElementTree
from defusedxml.common import DefusedXmlException
import httpx

from ..models import BusArrival, BusStopArrivals
from ..settings import settings

log = logging.getLogger("providers.busan_bus")
_BASE_URL = "https://apis.data.go.kr/6260000/BusanBIMS"
_STOP_SNAPSHOT = Path(__file__).resolve().parents[3] / "data" / "ai" / "busan_bus_stops.json"


@dataclass(frozen=True)
class BusStopCandidate:
    stop_id: str
    stop_name: str
    distance_m: float | None


@dataclass(frozen=True)
class _LocalBusStop:
    stop_id: str
    stop_name: str
    ars_no: str | None
    lat: float
    lng: float
    name_key: str


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
    if query.isdigit() and len(query) == 5:
        matches = [stop for stop in _BUS_STOPS if stop.ars_no == query]
    else:
        key = _stop_name_key(query)
        matches = [stop for stop in _BUS_STOPS if key and key in stop.name_key]
        matches.sort(key=lambda stop: (stop.name_key != key, stop.stop_name, stop.stop_id))
    return [
        BusStopArrivals(stop_id=stop.stop_id, stop_name=stop.stop_name, arrivals=[])
        for stop in matches[:30]
    ]


def _stop_name_key(value: str | None) -> str:
    return re.sub(r"[^0-9A-Za-z가-힣]", "", value or "").casefold()


def _load_bus_stops() -> tuple[_LocalBusStop, ...]:
    try:
        payload = json.loads(_STOP_SNAPSHOT.read_text(encoding="utf-8"))
        rows = payload["stops"]
        expected_count = int(payload["count"])
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        raise RuntimeError("BIMS 정류소 로컬 인덱스를 읽을 수 없습니다.") from exc
    result: list[_LocalBusStop] = []
    for row in rows:
        try:
            item = _LocalBusStop(
                stop_id=str(row["id"]),
                stop_name=str(row["name"]),
                ars_no=str(row["arsNo"]) if row.get("arsNo") else None,
                lat=float(row["lat"]),
                lng=float(row["lng"]),
                name_key=_stop_name_key(str(row["name"])),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise RuntimeError("BIMS 정류소 로컬 인덱스 항목이 올바르지 않습니다.") from exc
        if item.stop_id and item.stop_name and item.name_key:
            result.append(item)
    if len(result) != expected_count:
        raise RuntimeError("BIMS 정류소 로컬 인덱스 전체 건수가 일치하지 않습니다.")
    return tuple(result)


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
    """공식 로컬 인덱스에서 이름과 좌표가 일치하는 BIMS 정류소 하나를 찾는다."""
    expected = _stop_name_key(stop_name)
    if not expected or lat is None or lng is None:
        return []
    candidates: list[BusStopCandidate] = []
    for stop in _BUS_STOPS:
        if (
            expected != stop.name_key
            and expected not in stop.name_key
            and stop.name_key not in expected
        ):
            continue
        candidates.append(BusStopCandidate(
            stop.stop_id,
            stop.stop_name,
            _distance_m(lat, lng, stop.lat, stop.lng),
        ))
    exact = [item for item in candidates if _stop_name_key(item.stop_name) == expected]
    selected = exact or candidates
    selected.sort(key=lambda item: (
        item.distance_m if item.distance_m is not None else float("inf"),
        item.stop_id,
    ))
    nearest = selected[0] if selected else None
    return (
        [nearest]
        if nearest is not None
        and nearest.distance_m is not None
        and nearest.distance_m <= 500
        else []
    )


_BUS_STOPS = _load_bus_stops()


def clear_bus_stop_match_cache() -> None:
    """기존 테스트 호출 호환용. 정류소 매칭은 불변 로컬 인덱스라 캐시가 없다."""
    return None


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
