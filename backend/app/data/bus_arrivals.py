"""정류장 저상버스 도착 — 공유 데이터셋(data/bus_arrivals.json)에서 로드."""
from __future__ import annotations

from ..models import BusStopArrivals
from ._loader import load

BUS_ARRIVALS: dict[str, BusStopArrivals] = {
    k: BusStopArrivals.model_validate(v) for k, v in load("bus_arrivals.json").items()
}

BUS_STOP_LIST = list(BUS_ARRIVALS.values())


def get_arrivals(stop_id: str) -> BusStopArrivals | None:
    return BUS_ARRIVALS.get(stop_id)
