"""경로 ranker가 공유하는 경량 피처 및 최소 표본 계약."""
from __future__ import annotations

MIN_REVIEWERS = 9

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
