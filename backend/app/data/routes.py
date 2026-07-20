"""회귀검증용으로 사실이 고정된 단일 데모 OD 경로."""
from __future__ import annotations

from ..models import Place, RouteCandidate
from ._loader import load

DEMO_OD = {"origin_id": "gu-office", "destination_id": "seomyeon-stn"}
_DEMO_RAW = load("routes.demo.json")


def demo_candidates() -> list[RouteCandidate]:
    return [RouteCandidate.model_validate(row).model_copy(deep=True) for row in _DEMO_RAW]


def get_route_candidates(origin: Place, dest: Place) -> list[RouteCandidate]:
    """검증된 데모 OD만 반환하며 다른 OD를 합성하지 않는다."""
    if origin.id == DEMO_OD["origin_id"] and dest.id == DEMO_OD["destination_id"]:
        return demo_candidates()
    if origin.id == DEMO_OD["destination_id"] and dest.id == DEMO_OD["origin_id"]:
        routes = demo_candidates()
        for route in routes:
            route.origin = origin.name
            route.destination = dest.name
            if route.path:
                route.path = list(reversed(route.path))
        return routes
    return []
