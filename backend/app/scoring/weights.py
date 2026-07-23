"""프로필별 가중치 표(합=1) + 조건 옵션 보정. 프론트엔드 weights.ts 와 동일."""
from __future__ import annotations

COMPONENT_KEYS = (
    "accessibility",
    "walk_comfort",
    "slope_comfort",
    "shade_comfort",
    "transfer_simplicity",
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
        "walk_comfort": 0.15,
        "transfer_simplicity": 0.10,
        "weather_safety": 0.10,
        "safety": 0.09,
        "slope_comfort": 0.08,
        "shade_comfort": 0.06,
        "accessibility": 0.06,
        "data_reliability": 0.06,
        "elevator": 0.04,
        "low_floor_bus": 0.04,
    },
    "elderly": {
        "walk_comfort": 0.17,
        "slope_comfort": 0.14,
        "elevator": 0.14,
        "accessibility": 0.11,
        "transfer_simplicity": 0.10,
        "weather_safety": 0.10,
        "shade_comfort": 0.07,
        "low_floor_bus": 0.06,
        "time_efficiency": 0.04,
        "safety": 0.04,
        "data_reliability": 0.03,
    },
    "child": {
        "safety": 0.24,
        "transfer_simplicity": 0.14,
        "walk_comfort": 0.12,
        "weather_safety": 0.10,
        "time_efficiency": 0.08,
        "shade_comfort": 0.07,
        "data_reliability": 0.07,
        "slope_comfort": 0.05,
        "accessibility": 0.05,
        "elevator": 0.05,
        "low_floor_bus": 0.03,
    },
    "youth": {
        "time_efficiency": 0.24,
        "transfer_simplicity": 0.15,
        "safety": 0.12,
        "walk_comfort": 0.12,
        "data_reliability": 0.09,
        "weather_safety": 0.08,
        "shade_comfort": 0.05,
        "slope_comfort": 0.04,
        "accessibility": 0.04,
        "elevator": 0.04,
        "low_floor_bus": 0.03,
    },
    "disabled": {
        "accessibility": 0.16,
        "elevator": 0.16,
        "low_floor_bus": 0.16,
        "walk_comfort": 0.13,
        "slope_comfort": 0.11,
        "transfer_simplicity": 0.08,
        "weather_safety": 0.06,
        "data_reliability": 0.05,
        "shade_comfort": 0.04,
        "safety": 0.04,
        "time_efficiency": 0.01,
    },
    "pregnant": {
        "walk_comfort": 0.18,
        "slope_comfort": 0.15,
        "elevator": 0.14,
        "transfer_simplicity": 0.11,
        "weather_safety": 0.10,
        "shade_comfort": 0.08,
        "accessibility": 0.08,
        "safety": 0.05,
        "time_efficiency": 0.04,
        "data_reliability": 0.04,
        "low_floor_bus": 0.03,
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
    stroller: bool = False,
    low_floor_priority: bool = False,
    weather_avoid: bool = False,
    avoid_stairs: bool = False,
    shade_priority: bool = False,
    minimize_transfers: bool = False,
) -> Weights:
    w: Weights = dict(base)
    if carry_luggage:
        w["walk_comfort"] += 0.15
        w["transfer_simplicity"] += 0.08
        w["accessibility"] += 0.05
    if stroller:
        w["accessibility"] += 0.12
        w["elevator"] += 0.10
        w["walk_comfort"] += 0.08
        w["low_floor_bus"] += 0.05
    if low_floor_priority:
        w["low_floor_bus"] += 0.15
        w["elevator"] += 0.05
    if weather_avoid:
        w["weather_safety"] += 0.15
    if avoid_stairs:
        w["elevator"] += 0.12
        w["accessibility"] += 0.08
    if shade_priority:
        w["shade_comfort"] += 0.20
    if minimize_transfers:
        w["transfer_simplicity"] += 0.20
    return normalize_weights(w)
