"""정류장별 저상버스 도착 mock. 프론트 data/busArrivals.ts 와 동일."""
from __future__ import annotations

from ..models import BusArrival, BusStopArrivals

BUS_ARRIVALS: dict[str, BusStopArrivals] = {
    "stop-gu-office": BusStopArrivals(
        stop_id="stop-gu-office",
        stop_name="부산진구청 정류장",
        arrivals=[
            BusArrival(route_name="81", arrival_min=5, is_low_floor=True, remaining_stops=3),
            BusArrival(route_name="210", arrival_min=3, is_low_floor=False, remaining_stops=2),
            BusArrival(route_name="54", arrival_min=9, is_low_floor=None, remaining_stops=6),
        ],
    ),
    "stop-seomyeon": BusStopArrivals(
        stop_id="stop-seomyeon",
        stop_name="서면역 정류장",
        arrivals=[
            BusArrival(route_name="15", arrival_min=2, is_low_floor=True, remaining_stops=1),
            BusArrival(route_name="88", arrival_min=7, is_low_floor=None, remaining_stops=4),
            BusArrival(route_name="110", arrival_min=12, is_low_floor=False, remaining_stops=8),
        ],
    ),
    "stop-citizens-park": BusStopArrivals(
        stop_id="stop-citizens-park",
        stop_name="부산시민공원 정류장",
        arrivals=[
            BusArrival(route_name="129", arrival_min=4, is_low_floor=True, remaining_stops=2),
            BusArrival(route_name="63", arrival_min=6, is_low_floor=False, remaining_stops=5),
        ],
    ),
}

BUS_STOP_LIST = list(BUS_ARRIVALS.values())


def get_arrivals(stop_id: str) -> BusStopArrivals | None:
    return BUS_ARRIVALS.get(stop_id)
