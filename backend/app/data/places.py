"""부산진구(서면 일대) 대표 장소 mock. 프론트 data/places.ts 와 동일."""
from __future__ import annotations

from ..models import Place

PLACES: list[Place] = [
    Place(id="seomyeon-stn", name="서면역", category="지하철역", lat=35.1578, lng=129.0594, address="부산진구 중앙대로 지하"),
    Place(id="bujeon-stn", name="부전역", category="지하철역", lat=35.1631, lng=129.0608, address="부산진구 동천로"),
    Place(id="yangjeong-stn", name="양정역", category="지하철역", lat=35.1733, lng=129.0686, address="부산진구 중앙대로"),
    Place(id="jeonpo-stn", name="전포역", category="지하철역", lat=35.1571, lng=129.0686, address="부산진구 서전로"),
    Place(id="gaya-stn", name="가야역", category="지하철역", lat=35.149, lng=129.036, address="부산진구 가야대로"),
    Place(id="gu-office", name="부산진구청", category="관공서", lat=35.1626, lng=129.053, address="부산진구 시민공원로"),
    Place(id="citizens-park", name="부산시민공원", category="공원", lat=35.169, lng=129.056, address="부산진구 시민공원로"),
    Place(id="lotte-seomyeon", name="롯데백화점 부산본점", category="쇼핑", lat=35.1556, lng=129.0596, address="부산진구 가야대로"),
    Place(id="songsanghyeon", name="송상현광장", category="광장", lat=35.166, lng=129.057, address="부산진구 중앙대로"),
    Place(id="seomyeon-mall", name="서면지하상가", category="쇼핑", lat=35.1577, lng=129.059, address="부산진구 중앙대로 지하"),
    Place(id="jin-market", name="부전시장", category="시장", lat=35.1612, lng=129.0605, address="부산진구 중앙대로"),
]

_BY_ID = {p.id: p for p in PLACES}


def find_place(place_id: str) -> Place | None:
    return _BY_ID.get(place_id)


def search_places_by_name(query: str) -> list[Place]:
    q = query.strip().lower()
    if not q:
        return []
    return [
        p
        for p in PLACES
        if q in p.name.lower() or q in (p.address or "").lower()
    ]
