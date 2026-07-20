"""장소 검색 프로바이더. Kakao 키워드 검색(REST) 라이브 + mock 폴백."""
from __future__ import annotations

import logging

import httpx

from ..config import DISTRICT
from ..data.places import search_places_by_name
from ..models import Place
from ..settings import settings

log = logging.getLogger("providers.places")

KAKAO_KEYWORD_URL = "https://dapi.kakao.com/v2/local/search/keyword.json"


def _map_kakao(documents: list[dict]) -> list[Place]:
    out: list[Place] = []
    for i, d in enumerate(documents):
        try:
            out.append(
                Place(
                    id=d.get("id") or f"kakao-{i}",
                    name=d["place_name"],
                    lat=float(d["y"]),
                    lng=float(d["x"]),
                    category=d.get("category_group_name") or None,
                    address=d.get("road_address_name") or d.get("address_name") or None,
                )
            )
        except (KeyError, ValueError, TypeError):
            continue
    return out


async def search_places(query: str) -> list[Place]:
    q = (query or "").strip()
    if not q:
        return []
    if not settings.live_places:
        return search_places_by_name(q)
    try:
        async with httpx.AsyncClient(timeout=settings.request_timeout) as client:
            res = await client.get(
                KAKAO_KEYWORD_URL,
                params={
                    "query": q,
                    "size": 15,
                    "rect": ",".join(map(str, (
                        DISTRICT["bounds"]["min_lng"], DISTRICT["bounds"]["min_lat"],
                        DISTRICT["bounds"]["max_lng"], DISTRICT["bounds"]["max_lat"],
                    ))),
                    "sort": "accuracy",
                },
                headers={"Authorization": f"KakaoAK {settings.kakao_rest_api_key}"},
            )
            res.raise_for_status()
            return _map_kakao(res.json().get("documents", []))
    except (httpx.HTTPError, ValueError, TypeError, KeyError) as exc:
        log.warning("Kakao 장소검색 실패(%s)", type(exc).__name__)
        raise RuntimeError("Kakao place search request failed") from exc
