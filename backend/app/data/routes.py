"""경로 후보 데이터. 데모 대표 경로는 공유 데이터셋(data/routes.demo.json)에서 로드하고,
임의 OD 는 코드 합성기로 생성한다. 프론트엔드와 동일한 데이터/로직을 사용한다."""
from __future__ import annotations

import math

from ..models import LatLng, Place, RouteCandidate, RouteSegment
from ._loader import load

DEMO_OD = {"origin_id": "gu-office", "destination_id": "seomyeon-stn"}

_DEMO_RAW = load("routes.demo.json")


def demo_candidates() -> list[RouteCandidate]:
    # 깊은 복사본 반환: 역방향 데모에서 origin/path 를 변경해도 원본이 오염되지 않도록.
    return [RouteCandidate.model_validate(r).model_copy(deep=True) for r in _DEMO_RAW]


def _assemble(
    id_: str,
    summary: str,
    origin: str,
    destination: str,
    segments: list[RouteSegment],
    path: list[LatLng],
) -> RouteCandidate:
    total_walk_m = sum((s.distance_m or 0) for s in segments if s.mode == "walk")
    total_duration_min = sum(s.duration_min + (s.wait_min or 0) for s in segments)
    vehicles = sum(1 for s in segments if s.mode in ("bus", "subway"))
    transfer_count = max(0, vehicles - 1)
    return RouteCandidate(
        id=id_,
        summary=summary,
        origin=origin,
        destination=destination,
        segments=segments,
        total_walk_m=total_walk_m,
        total_duration_min=total_duration_min,
        transfer_count=transfer_count,
        path=path,
    )


def _c(place: Place | None) -> LatLng:
    return LatLng(lat=place.lat if place else 0, lng=place.lng if place else 0)


# ── 임의 OD 합성기 ──

def _haversine_m(a: LatLng, b: LatLng) -> int:
    R = 6371000
    d_lat = math.radians(b.lat - a.lat)
    d_lng = math.radians(b.lng - a.lng)
    lat1 = math.radians(a.lat)
    lat2 = math.radians(b.lat)
    h = math.sin(d_lat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(d_lng / 2) ** 2
    return round(2 * R * math.asin(math.sqrt(h)))


def _seeded(seed: int):
    s = seed % 2147483647
    if s <= 0:
        s += 2147483646

    def rnd() -> float:
        nonlocal s
        s = (s * 16807) % 2147483647
        return s / 2147483647

    return rnd


def _synth_candidates(origin: Place, dest: Place) -> list[RouteCandidate]:
    o = _c(origin)
    d = _c(dest)
    dist = _haversine_m(o, d)
    rnd = _seeded(round(dist + origin.lat * 1000))
    mid = LatLng(lat=(origin.lat + dest.lat) / 2, lng=(origin.lng + dest.lng) / 2)
    path = [o, mid, d]
    walk_min = max(1, round(dist / 75))

    cand1 = _assemble(
        "syn-walk", "도보 경로", origin.name, dest.name,
        [
            RouteSegment(
                id="sw1", mode="walk", description=f"{dest.name}까지 도보", duration_min=walk_min,
                distance_m=dist, outdoor=True, crosswalk_count=1 + round(rnd() * 3),
                has_slope=rnd() > 0.6,
            )
        ],
        path,
    )

    low_floor = True if rnd() > 0.5 else (False if rnd() > 0.5 else None)
    cand2 = _assemble(
        "syn-bus", "버스 경로", origin.name, dest.name,
        [
            RouteSegment(id="sb-w1", mode="walk", description="정류장까지 도보", duration_min=max(2, round(walk_min * 0.3)), distance_m=round(dist * 0.25), outdoor=True, crosswalk_count=1),
            RouteSegment(id="sb-bus", mode="bus", description="버스 승차", duration_min=max(4, round(walk_min * 0.5)), wait_min=3 + round(rnd() * 4), bus_route_name=str(100 + round(rnd() * 200)), is_low_floor_bus=low_floor),
            RouteSegment(id="sb-w2", mode="walk", description="하차 후 도보", duration_min=max(2, round(walk_min * 0.25)), distance_m=round(dist * 0.2), outdoor=True, crosswalk_count=1),
        ],
        path,
    )

    elev = True if rnd() > 0.4 else (False if rnd() > 0.5 else None)
    cand3 = _assemble(
        "syn-subway", "지하철 경로", origin.name, dest.name,
        [
            RouteSegment(id="ss-w1", mode="walk", description="역까지 도보", duration_min=max(3, round(walk_min * 0.35)), distance_m=round(dist * 0.3), outdoor=True, crosswalk_count=1),
            RouteSegment(id="ss-sub", mode="subway", description="지하철 승차", duration_min=max(3, round(walk_min * 0.4)), wait_min=3, station_name=f"{origin.name} 인근역", has_elevator=elev, needs_vertical_move=True),
            RouteSegment(id="ss-w2", mode="walk", description="하차 후 도보", duration_min=max(2, round(walk_min * 0.25)), distance_m=round(dist * 0.2), outdoor=False, crosswalk_count=0),
        ],
        path,
    )

    return [cand1, cand2, cand3]


def get_route_candidates(origin: Place, dest: Place) -> list[RouteCandidate]:
    if origin.id == DEMO_OD["origin_id"] and dest.id == DEMO_OD["destination_id"]:
        return demo_candidates()
    if origin.id == DEMO_OD["destination_id"] and dest.id == DEMO_OD["origin_id"]:
        out = []
        for r in demo_candidates():
            r.origin = origin.name
            r.destination = dest.name
            if r.path:
                r.path = list(reversed(r.path))
            out.append(r)
        return out
    return _synth_candidates(origin, dest)
