"""프로필별 가중치 표(합=1) + 조건 옵션 보정. 프론트엔드 weights.ts 와 동일."""
from __future__ import annotations

COMPONENT_KEYS = (
    "accessibility",
    "walk_comfort",
    "elevator",
    "low_floor_bus",
    "weather_safety",
    "safety",
    "data_reliability",
    "time_efficiency",
)

Weights = dict[str, float]

PROFILE_WEIGHTS: dict[str, Weights] = {
    "general": {
        "time_efficiency": 0.22,
        "walk_comfort": 0.18,
        "weather_safety": 0.15,
        "safety": 0.12,
        "accessibility": 0.10,
        "data_reliability": 0.10,
        "elevator": 0.08,
        "low_floor_bus": 0.05,
    },
    "elderly": {
        "walk_comfort": 0.22,
        "elevator": 0.20,
        "weather_safety": 0.18,
        "accessibility": 0.12,
        "time_efficiency": 0.08,
        "low_floor_bus": 0.08,
        "safety": 0.07,
        "data_reliability": 0.05,
    },
    "child": {
        "safety": 0.28,
        "walk_comfort": 0.16,
        "weather_safety": 0.16,
        "time_efficiency": 0.10,
        "accessibility": 0.08,
        "elevator": 0.08,
        "data_reliability": 0.10,
        "low_floor_bus": 0.04,
    },
    "disabled": {
        "accessibility": 0.20,
        "elevator": 0.20,
        "low_floor_bus": 0.20,
        "walk_comfort": 0.15,
        "weather_safety": 0.08,
        "safety": 0.07,
        "data_reliability": 0.07,
        "time_efficiency": 0.03,
    },
}


def normalize_weights(w: Weights) -> Weights:
    total = sum(w[k] for k in COMPONENT_KEYS)
    if total == 0:
        return dict(w)
    return {k: w[k] / total for k in COMPONENT_KEYS}


def apply_option_weights(
    base: Weights,
    *,
    carry_luggage: bool = False,
    low_floor_priority: bool = False,
    weather_avoid: bool = False,
    avoid_stairs: bool = False,
) -> Weights:
    w: Weights = dict(base)
    if carry_luggage:
        w["walk_comfort"] += 0.15
        w["accessibility"] += 0.05
    if low_floor_priority:
        w["low_floor_bus"] += 0.15
        w["elevator"] += 0.05
    if weather_avoid:
        w["weather_safety"] += 0.15
    if avoid_stairs:
        w["elevator"] += 0.12
        w["accessibility"] += 0.08
    return normalize_weights(w)
