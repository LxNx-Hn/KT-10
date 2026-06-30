"""부산진구 장소 — 공유 데이터셋(data/places.json)에서 로드."""
from __future__ import annotations

from ..models import Place
from ._loader import load

PLACES: list[Place] = [Place.model_validate(p) for p in load("places.json")]

_BY_ID = {p.id: p for p in PLACES}


def find_place(place_id: str) -> Place | None:
    return _BY_ID.get(place_id)


def search_places_by_name(query: str) -> list[Place]:
    q = query.strip().lower()
    if not q:
        return []
    return [
        p for p in PLACES if q in p.name.lower() or q in (p.address or "").lower()
    ]
