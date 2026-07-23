"""설명 가능한 데모 경로 비교와 사용자별 온라인 재정렬."""
from __future__ import annotations

from .feedback_tokens import create_feedback_token
from .models import ScoredRoute
from .personalization import blended_rank_score, parse_state
from .scoring.explain import build_voice_summary
from .settings import settings

RULE_MODEL_VERSION = "rule-demo-v1"


def route_features(item: ScoredRoute, profile: str) -> dict:
    route = item.route
    terrain = route.terrain
    shade = route.shade
    walk_segments = [segment for segment in route.segments if segment.mode == "walk"]
    bus_segments = [segment for segment in route.segments if segment.mode == "bus"]
    vertical_segments = [segment for segment in route.segments if segment.needs_vertical_move]
    stair_values = [
        segment.stairs_count
        if segment.stairs_count is not None
        else (0 if segment.has_stairs is False else None)
        for segment in route.segments
        if segment.mode in ("walk", "transfer")
    ]
    crosswalk_values = [segment.crosswalk_count for segment in walk_segments]
    return {
        "route_id": route.id,
        "profile": profile,
        "avg_slope_percent": terrain.avg_slope_percent if terrain else None,
        "max_slope_percent": terrain.max_slope_percent if terrain else None,
        "stair_count": (
            sum(value for value in stair_values if value is not None)
            if stair_values and all(value is not None for value in stair_values)
            else None
        ),
        "elevator_ratio": (
            sum(segment.has_elevator is True for segment in vertical_segments)
            / len(vertical_segments)
            if vertical_segments
            and all(segment.has_elevator is not None for segment in vertical_segments)
            else None
        ),
        "transfer_count": route.transfer_count,
        "walk_distance_m": route.total_walk_m,
        "total_duration_min": route.total_duration_min,
        "is_low_floor_bus": (
            float(all(segment.is_low_floor_bus is True for segment in bus_segments))
            if bus_segments
            and all(segment.is_low_floor_bus is not None for segment in bus_segments)
            else None
        ),
        "crosswalk_count": (
            sum(value for value in crosswalk_values if value is not None)
            if crosswalk_values and all(value is not None for value in crosswalk_values)
            else None
        ),
        "shade_ratio": (
            shade.shade_ratio
            if shade and shade.status in ("estimated_demo", "estimated_public") else None
        ),
        "shaded_walk_m": (
            shade.shaded_walk_m
            if shade and shade.status in ("estimated_demo", "estimated_public") else None
        ),
        "solar_elevation_deg": (
            shade.solar_elevation_deg
            if shade and shade.status in ("estimated_demo", "estimated_public") else None
        ),
        "rule_score": item.score.final_score,
    }


def select_representative_routes(
    ranked: list[ScoredRoute], top_n: int
) -> list[ScoredRoute]:
    """대표 특성 우승 경로를 먼저 보존하고 나머지는 규칙 점수순으로 채운다."""
    selected: list[ScoredRoute] = []
    for characteristic in ("fastest", "lowest_slope", "most_shade"):
        winner = next(
            (item for item in ranked if characteristic in item.route.characteristics),
            None,
        )
        if winner and all(item.route.id != winner.route.id for item in selected):
            selected.append(winner)
    for item in ranked:
        if len(selected) >= top_n:
            break
        if all(existing.route.id != item.route.id for existing in selected):
            selected.append(item)
    return selected[:top_n]


def personalize_and_sign(
    items: list[ScoredRoute],
    profile: str,
    personalization_state: str | None,
) -> list[ScoredRoute]:
    state = parse_state(personalization_state)
    active = int(state.get("updates", 0)) > 0
    if active and not settings.personalization_configured:
        raise RuntimeError("Personalization policy is not configured.")

    rows = [(item, route_features(item, profile)) for item in items]
    if active:
        assert settings.personalization_max_share is not None
        assert settings.personalization_prior_reviews is not None
        for item, features in rows:
            item.score.final_score = round(
                blended_rank_score(
                    item.score.final_score / 100,
                    state,
                    features,
                    max_personal_share=settings.personalization_max_share,
                    prior_reviews=settings.personalization_prior_reviews,
                ) * 100,
                1,
            )
        rows.sort(key=lambda row: row[0].score.final_score, reverse=True)

    result: list[ScoredRoute] = []
    for rank, (item, features) in enumerate(rows, start=1):
        item.score.feedback_token = create_feedback_token(
            item.route.id, RULE_MODEL_VERSION, features
        )
        item.score.voice_summary = build_voice_summary(
            item.route,
            rank,
            item.score.low_floor_status,
            item.score.cautions[0] if item.score.cautions else None,
        )
        result.append(item)
    return result
