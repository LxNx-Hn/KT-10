"""경로 ranker가 공유하는 경량 피처 및 최소 표본 계약."""
from __future__ import annotations

import math
from typing import Any

MIN_REVIEWERS = 9
GEOMETRY_QUALITIES = frozenset({"exact", "mixed", "estimated"})

FEATURE_COLS = [
    "avg_slope_percent", "max_slope_percent", "min_slope_percent", "slope_iqr",
    "stair_count", "elevator_ratio", "transfer_count",
    "walk_distance_m", "total_duration_min", "is_low_floor_bus",
    "shade_ratio", "shaded_walk_m", "shade_building_height_coverage",
    "cctv_density_50m", "crosswalk_count", "crosswalk_signal_ratio",
    "shelter_nearby", "aed_nearby", "wheelchair_charger_nearby",
    "smart_shelter_nearby", "smart_shelter_has_ac",
    "dongbaekjeon_store_count_200m", "bus_stop_count_200m",
    "crowd_level", "temp_c", "feels_like_c", "precipitation_mm", "wind_ms", "pm10",
    "weather_heatwave", "weather_coldwave", "weather_rain", "weather_bad_air",
    "stair_avoidance_burden", "luggage_walk_burden", "luggage_stair_burden",
    "low_floor_priority_mismatch", "wheelchair_stair_burden",
    "wheelchair_elevator_gap", "walking_aid_walk_burden", "max_walk_excess_m",
    "weather_priority_walk_burden",
    "stroller_walk_burden", "stroller_stair_burden", "stroller_elevator_gap",
    "shade_priority_unshaded_walk_m", "minimize_transfers_burden",
]

RATIO_FEATURES = frozenset({
    "elevator_ratio",
    "shade_ratio",
    "shade_building_height_coverage",
    "crosswalk_signal_ratio",
    "wheelchair_elevator_gap",
    "stroller_elevator_gap",
    "low_floor_priority_mismatch",
})
BINARY_FEATURES = frozenset({
    "shelter_nearby",
    "aed_nearby",
    "wheelchair_charger_nearby",
    "smart_shelter_nearby",
    "smart_shelter_has_ac",
    "weather_heatwave",
    "weather_coldwave",
    "weather_rain",
    "weather_bad_air",
})
BOOLEAN_FEATURES = frozenset({"is_low_floor_bus"})
INTEGER_FEATURES = frozenset({
    "stair_count",
    "transfer_count",
    "crosswalk_count",
    "dongbaekjeon_store_count_200m",
    "bus_stop_count_200m",
})
NONNEGATIVE_FEATURES = frozenset({
    "avg_slope_percent",
    "slope_iqr",
    "stair_count",
    "transfer_count",
    "walk_distance_m",
    "shaded_walk_m",
    "cctv_density_50m",
    "crosswalk_count",
    "dongbaekjeon_store_count_200m",
    "bus_stop_count_200m",
    "precipitation_mm",
    "wind_ms",
    "pm10",
    "stair_avoidance_burden",
    "luggage_walk_burden",
    "luggage_stair_burden",
    "wheelchair_stair_burden",
    "walking_aid_walk_burden",
    "max_walk_excess_m",
    "weather_priority_walk_burden",
    "stroller_walk_burden",
    "stroller_stair_burden",
    "shade_priority_unshaded_walk_m",
    "minimize_transfers_burden",
})


def validate_feature_values(
    features: dict[str, Any],
    feature_columns: list[str] = FEATURE_COLS,
) -> None:
    """모델 입력의 타입·단위 범위를 검증하고 결측 ``None``은 보존한다."""
    for name in feature_columns:
        value = features[name]
        if value is None:
            continue
        if name in BOOLEAN_FEATURES:
            if not isinstance(value, bool):
                raise ValueError(f"{name}은 boolean 또는 null이어야 합니다.")
            continue
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"{name}은 유한한 숫자 또는 null이어야 합니다.")
        number = float(value)
        if not math.isfinite(number):
            raise ValueError(f"{name}은 유한한 숫자 또는 null이어야 합니다.")
        if name in NONNEGATIVE_FEATURES and number < 0:
            raise ValueError(f"{name}은 0 이상이어야 합니다.")
        if name == "total_duration_min" and number <= 0:
            raise ValueError("total_duration_min은 0보다 커야 합니다.")
        if name in RATIO_FEATURES and not 0 <= number <= 1:
            raise ValueError(f"{name}은 0~1 범위여야 합니다.")
        if name in BINARY_FEATURES and number not in {0.0, 1.0}:
            raise ValueError(f"{name}은 0, 1 또는 null이어야 합니다.")
        if name in INTEGER_FEATURES and not number.is_integer():
            raise ValueError(f"{name}은 0 이상의 정수 또는 null이어야 합니다.")

    minimum_slope = features.get("min_slope_percent")
    maximum_slope = features.get("max_slope_percent")
    if (
        minimum_slope is not None
        and maximum_slope is not None
        and float(minimum_slope) > float(maximum_slope)
    ):
        raise ValueError(
            "min_slope_percent는 max_slope_percent보다 클 수 없습니다."
        )
    shaded_walk = features.get("shaded_walk_m")
    walk_distance = features.get("walk_distance_m")
    if (
        shaded_walk is not None
        and walk_distance is not None
        and float(shaded_walk) > float(walk_distance) + 0.01
    ):
        raise ValueError("shaded_walk_m은 walk_distance_m보다 클 수 없습니다.")
