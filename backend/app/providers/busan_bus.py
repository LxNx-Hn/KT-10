"""부산 BIMS 정류소 검색·실시간 도착 프로바이더.

공식 부산버스정보시스템 XML 계약만 사용한다. 도착 분이 숫자가 아니거나
저상버스 플래그가 0/1이 아니면 값을 꾸며내지 않고 원문 상태/미확인으로 보존한다.
"""
from __future__ import annotations

import logging
from xml.etree import ElementTree

import httpx

from ..models import BusArrival, BusStopArrivals
from ..settings import settings

log = logging.getLogger("providers.busan_bus")
_BASE_URL = "https://apis.data.go.kr/6260000/BusanBIMS"


def _text(item: ElementTree.Element, name: str) -> str | None:
    value = item.findtext(name)
    return value.strip() if value and value.strip() else None


def _integer(value: str | None) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except ValueError:
        return None


def _low_floor(value: str | None) -> bool | None:
    if value == "1":
        return True
    if value == "0":
        return False
    return None


def _parse_root(content: bytes) -> ElementTree.Element:
    root = ElementTree.fromstring(content)
    result_code = root.findtext(".//resultCode")
    if result_code != "00":
        message = root.findtext(".//resultMsg") or "응답 코드 미확인"
        raise RuntimeError(f"부산 BIMS 오류: {message}")
    return root


async def _request(path: str, params: dict[str, str | int]) -> ElementTree.Element:
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
    except (httpx.HTTPError, ElementTree.ParseError) as exc:
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


def _arrival(item: ElementTree.Element, suffix: str) -> BusArrival | None:
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
