"""장소 검색 프로바이더. Kakao 키워드 검색(REST) 라이브 + 개발용 demo."""
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
    malformed = 0
    bounds = DISTRICT["bounds"]
    for i, d in enumerate(documents):
        if not isinstance(d, dict):
            malformed += 1
            continue
        try:
            name = str(d["place_name"]).strip()
            if not name:
                raise ValueError("empty place name")
            lat = float(d["y"])
            lng = float(d["x"])
            # rect는 검색 힌트이므로 공급자가 권역 밖 결과를 반환할 수 있다.
            # 이 경우는 계약 오류가 아니라 명시적인 서비스 권역 필터다.
            if not (
                bounds["min_lat"] <= lat <= bounds["max_lat"]
                and bounds["min_lng"] <= lng <= bounds["max_lng"]
            ):
                continue
            out.append(
                Place(
                    id=str(d.get("id") or f"kakao-{i}"),
                    name=name,
                    lat=lat,
                    lng=lng,
                    category=d.get("category_group_name") or None,
                    address=d.get("road_address_name") or d.get("address_name") or None,
                )
            )
        except (KeyError, ValueError, TypeError):
            malformed += 1
            continue
    if malformed:
        log.warning(
            "Kakao 장소검색 응답에서 계약 위반 문서 %s건을 제외했습니다.",
            malformed,
        )
    if documents and malformed == len(documents):
        raise ValueError("Kakao place search response has no valid documents.")
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
            payload = res.json()
            if not isinstance(payload, dict) or not isinstance(
                payload.get("documents"),
                list,
            ):
                raise ValueError("Kakao place search response is invalid.")
            return _map_kakao(payload["documents"])
    except httpx.HTTPStatusError as exc:
        status = exc.response.status_code
        log.warning("Kakao 장소검색 HTTP 실패(status=%s)", status)
        if status in {401, 403}:
            raise RuntimeError("Kakao place search authentication failed.") from exc
        if status == 429:
            raise RuntimeError("Kakao place search rate limit exceeded.") from exc
        raise RuntimeError("Kakao place search provider request failed.") from exc
    except (httpx.HTTPError, ValueError, TypeError, KeyError) as exc:
        log.warning("Kakao 장소검색 실패(%s)", type(exc).__name__)
        raise RuntimeError("Kakao place search provider request failed.") from exc
