"""AI 경로 서버 응답을 프론트엔드 공통 도메인 모델로 변환한다."""
from __future__ import annotations

import logging

import httpx

from ..models import (
    LowFloorStatus,
    Place,
    RouteCandidate,
    RouteScore,
    RouteSegment,
    ScoreComponents,
    ScoreDisplay,
    ScoredRoute,
    ScoringOptions,
    TerrainSummary,
)
from ..feedback_tokens import create_feedback_token
from ..personalization import blended_rank_score, parse_state
from ..scoring.utils import clamp, round1
from ..settings import settings

log = logging.getLogger("providers.ai_pipeline")


class AIProviderError(RuntimeError):
    def __init__(self, status_code: int, detail: str):
        super().__init__(detail)
        self.status_code = status_code

_WEATHER_TO_AI = {
    "normal": "normal", "heatwave": "heatwave", "coldwave": "coldwave",
    "rain": "rain", "dust": "bad_air",
}


def _pipeline_payload(
    origin: Place,
    destination: Place,
    profile: str,
    weather_scenario: str,
    options: ScoringOptions,
    user_preference=None,
    weather_condition=None,
) -> dict:
    return {
        "origin_lat": origin.lat, "origin_lng": origin.lng, "origin_name": origin.name,
        "dest_lat": destination.lat, "dest_lng": destination.lng, "dest_name": destination.name,
        "profile": profile,
        "weather": _WEATHER_TO_AI.get(weather_scenario, "normal"),
        "prioritize_weather_safety": options.weather_avoid,
        "carry_luggage": options.carry_luggage,
        "avoid_stairs": options.avoid_stairs or bool(
            user_preference and user_preference.avoid_stairs_required
        ),
        "low_floor_priority": options.low_floor_priority,
        "uses_wheelchair": bool(user_preference and user_preference.uses_wheelchair),
        "uses_walking_aid": bool(user_preference and user_preference.uses_walking_aid),
        "max_walk_distance_m": (
            user_preference.max_walk_distance_m if user_preference else None
        ),
        "temp_c": weather_condition.temp_c if weather_condition else None,
        "feels_like_c": weather_condition.feels_like_c if weather_condition else None,
        "precipitation_mm": (
            weather_condition.precipitation_mm if weather_condition else None
        ),
        "wind_ms": weather_condition.wind_ms if weather_condition else None,
        "pm10": weather_condition.pm10 if weather_condition else None,
    }


def _response_detail(response: httpx.Response) -> str:
    try:
        detail = response.json().get("detail")
    except (ValueError, TypeError, AttributeError):
        detail = None
    if isinstance(detail, str):
        return detail
    if isinstance(detail, dict) and isinstance(detail.get("message"), str):
        return detail["message"]
    return f"AI pipeline server returned HTTP {response.status_code}."


async def _post_pipeline(path: str, payload: dict) -> dict:
    if not settings.ai_server_url:
        raise AIProviderError(503, "AI_SERVER_URL is not configured.")
    try:
        async with httpx.AsyncClient(timeout=settings.request_timeout * 8) as client:
            response = await client.post(
                f"{settings.ai_server_url.rstrip('/')}{path}",
                json=payload,
            )
            response.raise_for_status()
        data = response.json()
        if not isinstance(data, dict):
            raise TypeError("pipeline response must be an object")
        return data
    except httpx.HTTPStatusError as exc:
        status = exc.response.status_code
        log.warning("AI 경로 서버가 HTTP %s를 반환했습니다.", status)
        raise AIProviderError(
            503 if status == 503 else 502,
            _response_detail(exc.response),
        ) from exc
    except (httpx.HTTPError, ValueError, TypeError, KeyError) as exc:
        log.warning("AI 경로 서버 호출 실패 (%s)", type(exc).__name__)
        raise AIProviderError(502, "AI pipeline server request failed.") from exc


async def get_ai_pipeline_candidates(
    origin: Place,
    destination: Place,
    profile: str = "general",
    weather_scenario: str = "normal",
    options: ScoringOptions | None = None,
    user_preference=None,
    weather_condition=None,
) -> list[RouteCandidate]:
    """학습 모델 없이도 실제 geometry·지형 피처가 있는 후보를 수집한다."""
    payload = _pipeline_payload(
        origin,
        destination,
        profile,
        weather_scenario,
        options or ScoringOptions(),
        user_preference,
        weather_condition,
    )
    data = await _post_pipeline("/labeling/candidates", payload)
    candidates = data.get("candidates") or []
    if not isinstance(candidates, list) or not candidates:
        raise AIProviderError(502, "AI pipeline server returned no route candidates.")
    try:
        return [
            _to_route_candidate(item, origin, destination, index + 1)
            for index, item in enumerate(candidates)
        ]
    except (KeyError, TypeError, ValueError, RuntimeError) as exc:
        raise AIProviderError(
            502,
            "AI pipeline candidate contract is invalid.",
        ) from exc


async def get_ai_pipeline_routes(
    origin: Place,
    destination: Place,
    profile: str,
    weather_scenario: str,
    options: ScoringOptions,
    top_n: int = 3,
    personalization_state: str | None = None,
    user_preference=None,
    weather_condition=None,
) -> list[ScoredRoute]:
    payload = _pipeline_payload(
        origin,
        destination,
        profile,
        weather_scenario,
        options,
        user_preference,
        weather_condition,
    )
    data = await _post_pipeline("/recommend", payload)

    routes = data.get("routes") or []
    if not routes:
        raise AIProviderError(502, "AI pipeline server returned no routes.")
    valid_durations = [float(route["duration_min"]) for route in routes if float(route.get("duration_min") or 0) > 0]
    if not valid_durations:
        raise AIProviderError(502, "AI pipeline server returned no valid route duration.")
    state = parse_state(personalization_state)
    personalization_active = int(state.get("updates", 0)) > 0
    if personalization_active and not settings.personalization_configured:
        raise AIProviderError(503, "Personalization policy is not configured.")

    def rank_value(route: dict) -> float:
        probability = float(route["selection_probability"])
        if not personalization_active:
            return probability
        assert settings.personalization_max_share is not None
        assert settings.personalization_prior_reviews is not None
        return blended_rank_score(
            probability,
            state,
            route.get("features") or {},
            max_personal_share=settings.personalization_max_share,
            prior_reviews=settings.personalization_prior_reviews,
        )

    routes.sort(
        key=rank_value,
        reverse=True,
    )
    reranked = [{**route, "rank": index + 1} for index, route in enumerate(routes[:top_n])]
    return [_to_scored_route(route, origin, destination, profile) for route in reranked]


def _to_segment(item: dict, rank: int, index: int) -> RouteSegment:
    duration = float(item["duration_min"])
    stairs = item.get("stairs_count")
    return RouteSegment(
        id=str(item.get("id") or f"ai-{rank}-{index}"),
        mode=item.get("mode", "transfer"),
        description=str(item.get("description") or "이동 구간"),
        duration_min=duration,
        distance_m=item.get("distance_m"),
        outdoor=item.get("outdoor"),
        has_stairs=item.get("has_stairs"),
        stairs_count=int(stairs) if stairs is not None else None,
        has_slope=item.get("has_slope"),
        crosswalk_count=item.get("crosswalk_count"),
        bus_route_name=item.get("bus_route_name"),
        is_low_floor_bus=item.get("is_low_floor_bus"),
        wait_min=item.get("wait_min"),
        station_name=item.get("station_name"),
        has_elevator=item.get("has_elevator"),
        needs_vertical_move=item.get("needs_vertical_move"),
        path=item.get("path"),
        geometry_quality=item.get("geometry_quality"),
    )


def _to_route_candidate(
    r: dict,
    origin: Place,
    destination: Place,
    rank: int,
) -> RouteCandidate:
    feature = r.get("features") or {}
    segments = [
        _to_segment(item, rank, index)
        for index, item in enumerate(r.get("segments") or [])
    ]
    if not segments:
        raise RuntimeError("ai pipeline route has no truthful segments")

    transfer_count = feature.get("transfer_count")
    if transfer_count is None:
        transfer_count = sum(1 for segment in segments if segment.mode == "transfer")
    walk_distance = feature.get("walk_distance_m")
    if walk_distance is None:
        walking_segments = [segment for segment in segments if segment.mode == "walk"]
        if any(segment.distance_m is None for segment in walking_segments):
            raise RuntimeError("ai pipeline route has no truthful walking distance")
        walk_distance = sum(float(segment.distance_m) for segment in walking_segments)
    source_names = [str(source) for source in r.get("sources") or []]
    modes = [segment.bus_route_name or {"subway": "도시철도", "walk": "도보"}.get(segment.mode)
             for segment in segments]
    summary = str(r.get("summary") or "") or (
        " + ".join(dict.fromkeys(mode for mode in modes if mode))
        or f"{origin.name} → {destination.name}"
    )

    route_id = str(r.get("route_id") or f"ai-{rank}")
    path = [
        {"lat": point["lat"], "lng": point["lng"]}
        for point in r.get("path") or []
    ]
    if len(path) < 2:
        raise RuntimeError("ai pipeline route has no truthful geometry")
    return RouteCandidate(
        id=route_id,
        summary=summary,
        origin=origin.name,
        destination=destination.name,
        segments=segments,
        total_duration_min=float(r["duration_min"]),
        total_walk_m=float(walk_distance),
        transfer_count=int(transfer_count),
        path=path,
        sources=source_names,
        geometry_quality=r.get("geometry_quality"),
        terrain=TerrainSummary(
            avg_slope_percent=feature.get("avg_slope_percent"),
            max_slope_percent=feature.get("max_slope_percent"),
            min_slope_percent=feature.get("min_slope_percent"),
            uphill_distance_m=feature.get("uphill_distance_m"),
            downhill_distance_m=feature.get("downhill_distance_m"),
            elevation_gain_m=feature.get("elevation_gain_m"),
            elevation_loss_m=feature.get("elevation_loss_m"),
            source=feature.get("elevation_source"),
            resolution_m=feature.get("elevation_resolution_m"),
            status=feature.get("elevation_status", "unavailable"),
        ),
    )


def _to_scored_route(r: dict, origin: Place, destination: Place, profile: str) -> ScoredRoute:
    feature = r.get("features") or {}
    tags = r.get("tags") or []
    reasons = r.get("reasons") or []
    rank = int(r["rank"])
    route = _to_route_candidate(r, origin, destination, rank)
    is_low_floor = feature.get("is_low_floor_bus")
    bus_used = any(segment.mode == "bus" for segment in route.segments)
    walk_distance = route.total_walk_m
    transfer_count = route.transfer_count

    cautions = [str(tag["label"]) for tag in tags if tag.get("tone") == "negative"]
    voice_summary = (
        f"{rank}번째 경로입니다. 총 {round(float(r['duration_min']))}분, "
        f"도보 {round(float(walk_distance))}미터, 환승 {int(transfer_count)}회입니다."
        + (f" {reasons[0]}" if reasons else "")
    )
    selection_probability = float(r["selection_probability"])
    score = RouteScore(
        route_id=route.id,
        components=ScoreComponents(),
        display=ScoreDisplay(),
        # UI에 노출하지 않는 후보 집합 내 상대 선택 확률이다.
        final_score=round1(clamp(selection_probability * 100)),
        low_floor_status=_derive_low_floor_status(bus_used, is_low_floor),
        reasons=[str(reason) for reason in reasons],
        cautions=cautions,
        voice_summary=voice_summary,
        feedback_token=create_feedback_token(
            route.id,
            str(r.get("model_version") or "xgboost-human"),
            {
                "group_id": r.get("group_id"),
                "route_id": route.id,
                "profile": profile,
                **feature,
            },
        ),
    )
    return ScoredRoute(route=route, score=score)


def _derive_low_floor_status(bus_used: bool, is_low_floor) -> LowFloorStatus:
    if not bus_used:
        return "none"
    if is_low_floor is True:
        return "confirmed"
    if is_low_floor is False:
        return "regular"
    return "unknown"
