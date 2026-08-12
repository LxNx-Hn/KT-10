"""NVIDIA NIM에서 서버가 확인한 경로 사실을 한국어로 풀어쓴다."""
from __future__ import annotations

import asyncio
import json

import httpx

from ..models import RouteCandidate, ScoredRoute
from ..settings import settings


class NimExplanationError(RuntimeError):
    """NIM 설명 생성 요청을 완료하지 못했다."""


def _route_facts(candidate: RouteCandidate) -> dict:
    """모델에 보낼, 캐시된 후보의 표시 가능한 사실만 만든다."""
    terrain = candidate.terrain
    shade = candidate.shade
    segments = []
    for segment in candidate.segments:
        item = {
            "mode": segment.mode,
            "description": segment.description,
            "durationMin": segment.duration_min,
        }
        if segment.distance_m is not None:
            item["distanceM"] = segment.distance_m
        for key in ("stairs_count", "has_elevator", "is_low_floor_bus"):
            value = getattr(segment, key)
            if value is not None:
                item[key] = value
        if segment.ramp_points:
            item["physicalRampPointCount"] = len(segment.ramp_points)
            if segment.ramp_replaces_stairs is True:
                item["physicalRampReplacesStairs"] = True
        if segment.station_external_ramp_count is not None:
            item["stationExternalRampInventoryCount"] = (
                segment.station_external_ramp_count
            )
            # 현재 공공데이터는 역 단위 재고이므로 특정 출구·경로에 있다고
            # 모델이 확대 해석하지 못하도록 일치 여부를 명시한다.
            item["stationRampMatchedToThisRoute"] = (
                segment.station_ramp_route_match is True
            )
        if segment.wheelchair_constraints_applied is True:
            item["mappedWheelchairConstraintsApplied"] = True
            item["wheelchairDataLimitations"] = list(
                segment.wheelchair_data_limitations or []
            )
        segments.append(item)
    facts = {
        "summary": candidate.summary,
        "origin": candidate.origin,
        "destination": candidate.destination,
        "totalDurationMin": candidate.total_duration_min,
        "totalWalkM": candidate.total_walk_m,
        "transferCount": candidate.transfer_count,
        "geometryQuality": candidate.geometry_quality,
        "segments": segments,
    }
    if terrain is not None and terrain.status == "estimated_90m":
        facts["terrain90m"] = {
            "avgSlopePercent": terrain.avg_slope_percent,
            "maxSlopePercent": terrain.max_slope_percent,
        }
    if shade is not None and shade.status == "estimated_public":
        facts["buildingShade"] = {"ratio": shade.shade_ratio}
    return facts


async def explain_route(candidate: RouteCandidate) -> str:
    """OpenAI 호환 NIM API를 호출하고 한 문단 응답만 반환한다."""
    if not settings.nvidia_api_key.strip() or not settings.nim_model.strip():
        raise NimExplanationError("NIM 설명 기능 설정이 필요합니다.")
    prompt = json.dumps(_route_facts(candidate), ensure_ascii=False, separators=(",", ":"))
    payload = {
        "model": settings.nim_model,
        "temperature": 0,
        "max_tokens": min(settings.nim_max_output_tokens, 300),
        "chat_template_kwargs": {"enable_thinking": False},
        "messages": [
            {
                "role": "system",
                "content": (
                    "/no_think\n"
                    "한국어 경로 안내를 차분하고 자연스러운 대화체의 짧은 한 문단으로 작성하세요. "
                    "먼저 총 소요시간과 총 도보거리를 안내한 뒤 segments 순서대로 설명하세요. "
                    "totalWalkM을 개별 segment의 durationMin과 결합하지 말고, 구간 거리와 시간은 같은 segment에 "
                    "distanceM과 durationMin이 함께 있을 때만 한 문장으로 묶으세요. 조건문처럼 '~걸리면'이라고 잇지 마세요. "
                    "제공한 JSON의 값만 사용하고 "
                    "값이 없는 시설, 계단, 경사로, 엘리베이터, 저상버스, 안전성은 언급하지 마세요. "
                    "physicalRampPointCount만 실제 경로의 경사로 근거입니다. stationRampMatchedToThisRoute가 false이면 "
                    "역 경사로 재고를 이 경로에서 이용한다고 말하지 마세요. mappedWheelchairConstraintsApplied는 지도에 "
                    "기록된 제한에만 해당하며 wheelchairDataLimitations도 함께 안내하세요. "
                    "terrain90m은 90m 지형 추정값으로 표현하세요. JSON이나 목록을 출력하지 마세요."
                ),
            },
            {"role": "user", "content": prompt},
        ],
    }
    try:
        async with httpx.AsyncClient(timeout=settings.nim_request_timeout_seconds) as client:
            for _ in range(settings.nim_response_attempts):
                response = await client.post(
                    settings.nim_base_url.rstrip("/") + "/chat/completions",
                    headers={
                        "Authorization": f"Bearer {settings.nvidia_api_key}",
                        "Content-Type": "application/json",
                    },
                    json=payload,
                )
                response.raise_for_status()
                content = response.json()["choices"][0]["message"].get("content")
                if isinstance(content, str) and content.strip():
                    return content.strip()[:2000]
    except (httpx.HTTPError, KeyError, IndexError, TypeError, ValueError) as exc:
        raise NimExplanationError("NIM 경로 설명을 생성하지 못했습니다.") from exc
    raise NimExplanationError("NIM 경로 설명 응답이 비어 있습니다.")


async def enrich_voice_summaries(scored: list[ScoredRoute]) -> list[ScoredRoute]:
    """기존 음성 챗봇의 경로 요약을 NIM으로 보강한다.

    NIM을 사용할 수 없거나 호출이 실패하면 순위화 단계에서 만든 규칙 기반
    ``voice_summary``를 유지하므로 기존 프런트의 음성·챗봇 흐름이 이어진다.
    """
    if not settings.nvidia_api_key.strip() or not settings.nim_model.strip():
        return scored

    limit = min(len(scored), settings.nim_route_explanation_max_routes)
    explanations = await asyncio.gather(
        *(explain_route(item.route) for item in scored[:limit]),
        return_exceptions=True,
    )
    for item, explanation in zip(scored[:limit], explanations, strict=True):
        if isinstance(explanation, str):
            item.score.voice_summary = explanation
    return scored
