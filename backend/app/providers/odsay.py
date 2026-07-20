"""ODsay public-transit candidates normalized into the application's route contract."""
from __future__ import annotations

import logging

import httpx

from ..models import Place, RouteCandidate, RouteSegment
from ..settings import settings

log = logging.getLogger("providers.odsay")
_URL = "https://api.odsay.com/v1/api/searchPubTransPathT"


def _required_number(container: dict, key: str, *, minimum: float = 0) -> float:
    """외부 응답의 필수 수치를 결측 0으로 바꾸지 않고 검증한다."""
    if key not in container or container[key] is None:
        raise ValueError(f"ODsay response is missing {key}")
    value = float(container[key])
    if value < minimum:
        raise ValueError(f"ODsay response has invalid {key}")
    return value


def _lane_name(sub: dict) -> str:
    lanes = sub.get("lane") or []
    lane = lanes[0] if lanes else {}
    return str(lane.get("busNo") or lane.get("name") or lane.get("subwayCode") or "정보 미확인")


def _segment(path_index: int, segment_index: int, sub: dict) -> RouteSegment:
    traffic_type = sub.get("trafficType")
    duration = _required_number(sub, "sectionTime")
    distance = _required_number(sub, "distance") if sub.get("distance") is not None else None
    if traffic_type == 1:
        station = " → ".join(filter(None, [sub.get("startName"), sub.get("endName")]))
        return RouteSegment(
            id=f"odsay-{path_index}-{segment_index}", mode="subway",
            description=f"지하철 {_lane_name(sub)}", duration_min=duration,
            distance_m=distance, station_name=station or None,
        )
    if traffic_type == 2:
        return RouteSegment(
            id=f"odsay-{path_index}-{segment_index}", mode="bus",
            description=f"버스 {_lane_name(sub)}", duration_min=duration,
            distance_m=distance, bus_route_name=_lane_name(sub),
            # ODsay 응답만으로 저상버스 여부는 확정하지 않는다.
        )
    return RouteSegment(
        id=f"odsay-{path_index}-{segment_index}", mode="walk",
        description="도보 이동", duration_min=duration, distance_m=distance, outdoor=True,
    )


def _normalize(payload: dict, origin: Place, destination: Place) -> list[RouteCandidate]:
    paths = ((payload.get("result") or {}).get("path") or [])
    out: list[RouteCandidate] = []
    for i, item in enumerate(paths):
        info = item.get("info") or {}
        try:
            total_duration = _required_number(info, "totalTime", minimum=0.000001)
            total_walk = _required_number(info, "totalWalk")
            bus_transfers = int(_required_number(info, "busTransitCount"))
            subway_transfers = int(_required_number(info, "subwayTransitCount"))
            segments = [_segment(i, j, sub) for j, sub in enumerate(item.get("subPath") or [])]
        except (TypeError, ValueError):
            continue
        if not segments:
            continue
        first = info.get("firstStartStation") or origin.name
        last = info.get("lastEndStation") or destination.name
        out.append(RouteCandidate(
            id=f"odsay-{i + 1}", summary=f"{first} → {last}",
            origin=origin.name, destination=destination.name, segments=segments,
            total_duration_min=total_duration,
            total_walk_m=total_walk,
            transfer_count=bus_transfers + subway_transfers,
        ))
    return out


async def get_public_transit_candidates(origin: Place, destination: Place) -> list[RouteCandidate]:
    """Fetch real candidates. Fail loudly rather than misrepresenting a synthetic route as live."""
    if not settings.live_routes:
        return []
    params = {
        "apiKey": settings.odsay_api_key,
        "SX": origin.lng, "SY": origin.lat,
        "EX": destination.lng, "EY": destination.lat,
        "OPT": 0, "SearchType": 0,
    }
    try:
        async with httpx.AsyncClient(timeout=settings.request_timeout) as client:
            response = await client.get(_URL, params=params)
            response.raise_for_status()
        candidates = _normalize(response.json(), origin, destination)
    except Exception as exc:
        log.warning("ODsay public-transit lookup failed (%s)", type(exc).__name__)
        raise RuntimeError("ODsay public-transit lookup failed") from exc
    if not candidates:
        raise RuntimeError("ODsay returned no public-transit candidates")
    return candidates
