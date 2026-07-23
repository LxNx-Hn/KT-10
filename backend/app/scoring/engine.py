"""
점수화 엔진 오케스트레이터. 프론트엔드 scoring/engine.ts 와 동일 동작.
candidates + weather + profile + options → 채점·정렬된 상위 N 추천.
"""
from __future__ import annotations

from functools import cmp_to_key

from ..models import (
    RouteCandidate,
    RouteScore,
    ScoreComponents,
    ScoreDisplay,
    ScoredRoute,
    ScoringOptions,
    WeatherCondition,
)
from . import components as comp
from .explain import (
    build_cautions,
    build_reasons,
    build_voice_summary,
    derive_low_floor_status,
)
from .utils import clamp, round1
from .weights import COMPONENT_KEYS, PROFILE_WEIGHTS, Weights, apply_option_weights


def weighted_final(c: ScoreComponents, w: Weights) -> float:
    cd = c.model_dump()
    available = [key for key in COMPONENT_KEYS if cd[key] is not None]
    available_weight = sum(w[key] for key in available)
    if available_weight <= 0:
        raise ValueError("점수화할 수 있는 확인된 경로 특성이 없습니다.")
    return clamp(
        sum(cd[key] * w[key] for key in available) / available_weight
    )


def _round_components(c: ScoreComponents) -> ScoreComponents:
    return ScoreComponents(
        **{
            key: round1(value) if value is not None else None
            for key, value in c.model_dump().items()
        }
    )


def score_route(
    route: RouteCandidate,
    weather: WeatherCondition,
    profile: str,
    fastest_min: float,
    rank: int,
    options: ScoringOptions | None = None,
) -> RouteScore:
    opts = options or ScoringOptions()
    components = ScoreComponents(
        accessibility=comp.score_accessibility(route),
        walk_comfort=comp.score_walk_comfort(route),
        slope_comfort=comp.score_slope_comfort(route),
        shade_comfort=comp.score_shade_comfort(route),
        transfer_simplicity=comp.score_transfer_simplicity(route),
        elevator=comp.score_elevator(route),
        low_floor_bus=comp.score_low_floor_bus(route),
        weather_safety=comp.score_weather_safety(route, weather),
        safety=comp.score_safety(route),
        data_reliability=comp.score_data_reliability(route),
        time_efficiency=comp.score_time_efficiency(route.total_duration_min, fastest_min),
    )
    weights = apply_option_weights(
        PROFILE_WEIGHTS[profile],
        carry_luggage=opts.carry_luggage,
        stroller=opts.stroller,
        low_floor_priority=opts.low_floor_priority,
        weather_avoid=opts.weather_avoid,
        avoid_stairs=opts.avoid_stairs,
        shade_priority=opts.shade_priority,
        minimize_transfers=opts.minimize_transfers,
    )
    final_score = round1(weighted_final(components, weights))

    low_floor_status = derive_low_floor_status(route)
    reasons = build_reasons(route, components, low_floor_status)
    cautions = build_cautions(route, components, low_floor_status, weather)
    voice_summary = build_voice_summary(
        route, rank, low_floor_status, cautions[0] if cautions else None
    )

    return RouteScore(
        route_id=route.id,
        components=_round_components(components),
        display=ScoreDisplay(
            walk_burden=round1(100 - components.walk_comfort),
            weather_risk=round1(100 - components.weather_safety),
        ),
        final_score=final_score,
        low_floor_status=low_floor_status,
        reasons=reasons,
        cautions=cautions,
        voice_summary=voice_summary,
    )


def recommend_routes(
    candidates: list[RouteCandidate],
    weather: WeatherCondition,
    profile: str,
    options: ScoringOptions | None = None,
    top_n: int = 3,
) -> list[ScoredRoute]:
    if not candidates:
        return []
    opts = options or ScoringOptions()
    fastest_min = min(c.total_duration_min for c in candidates)

    scored: list[ScoredRoute] = [
        ScoredRoute(
            route=route,
            score=score_route(route, weather, profile, fastest_min, i + 1, opts),
        )
        for i, route in enumerate(candidates)
    ]

    def cmp(a: ScoredRoute, b: ScoredRoute) -> int:
        diff = b.score.final_score - a.score.final_score
        if abs(diff) > 0.05:
            return -1 if diff < 0 else 1
        if opts.low_floor_priority:
            ra = 1 if a.score.low_floor_status == "confirmed" else 0
            rb = 1 if b.score.low_floor_status == "confirmed" else 0
            if rb - ra != 0:
                return rb - ra
        return -1 if a.route.total_duration_min < b.route.total_duration_min else 1

    scored.sort(key=cmp_to_key(cmp))

    result: list[ScoredRoute] = []
    for idx, sr in enumerate(scored[:top_n]):
        sr.score.voice_summary = build_voice_summary(
            sr.route,
            idx + 1,
            sr.score.low_floor_status,
            sr.score.cautions[0] if sr.score.cautions else None,
        )
        result.append(sr)
    return result
