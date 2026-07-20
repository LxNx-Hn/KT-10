"""실제 후기 보상을 이용한 사용자별 온라인 만족도 모델."""
from __future__ import annotations

import json
import math

FEATURES = (
    "avg_slope_percent", "max_slope_percent", "stair_count", "elevator_ratio",
    "transfer_count", "walk_distance_m", "total_duration_min", "is_low_floor_bus",
    "crosswalk_count", "crosswalk_signal_ratio", "shelter_nearby",
    "wheelchair_charger_nearby", "crowd_level", "temp_c", "feels_like_c",
    "precipitation_mm", "wind_ms", "pm10", "stair_avoidance_burden",
    "luggage_walk_burden", "luggage_stair_burden", "low_floor_priority_mismatch",
    "wheelchair_stair_burden", "wheelchair_elevator_gap", "walking_aid_walk_burden",
    "max_walk_excess_m", "weather_priority_walk_burden",
)


class PersonalizationStateError(RuntimeError):
    """저장된 개인화 상태가 손상되었거나 지원하지 않는 버전인 경우."""


def _sigmoid(value: float) -> float:
    return 1.0 / (1.0 + math.exp(-max(-30.0, min(30.0, value))))


def vector(features: dict) -> dict[str, float]:
    """결측 indicator와 log1p 변환으로 미확인과 실제 0을 구분한다."""
    result: dict[str, float] = {}
    for name in FEATURES:
        value = features.get(name)
        result[f"{name}__known"] = float(value is not None)
        if value is None:
            result[name] = 0.0
        else:
            number = float(value)
            result[name] = math.copysign(math.log1p(abs(number)), number)
    return result


def parse_state(raw: str | None) -> dict:
    if not raw:
        return {"version": 1, "bias": 0.0, "weights": {}, "updates": 0}
    try:
        state = json.loads(raw)
    except (TypeError, ValueError) as exc:
        raise PersonalizationStateError("저장된 개인화 상태 JSON이 손상되었습니다.") from exc
    if not isinstance(state, dict) or state.get("version") != 1:
        raise PersonalizationStateError("지원하지 않는 개인화 상태 버전입니다.")
    weights = state.get("weights")
    updates = state.get("updates")
    bias = state.get("bias")
    if not isinstance(weights, dict) or not isinstance(updates, int) or updates < 0:
        raise PersonalizationStateError("개인화 상태 구조가 올바르지 않습니다.")
    try:
        numeric = [float(bias), *(float(value) for value in weights.values())]
    except (TypeError, ValueError) as exc:
        raise PersonalizationStateError("개인화 상태에 숫자가 아닌 계수가 있습니다.") from exc
    if not all(math.isfinite(value) for value in numeric):
        raise PersonalizationStateError("개인화 상태에 유한하지 않은 계수가 있습니다.")
    return {"version": 1, "bias": numeric[0], "weights": weights, "updates": updates}


def reward_target(
    *, was_usable: bool, rating: int, would_reuse: bool | None,
    usable_weight: float, rating_weight: float, reuse_weight: float,
) -> float:
    if not 1 <= rating <= 5:
        raise ValueError("rating은 1~5 범위여야 합니다.")
    if min(usable_weight, rating_weight, reuse_weight) < 0:
        raise ValueError("후기 신호 가중치는 음수일 수 없습니다.")
    weighted = [
        (1.0 if was_usable else 0.0, usable_weight),
        ((rating - 1) / 4, rating_weight),
    ]
    if would_reuse is not None:
        weighted.append((1.0 if would_reuse else 0.0, reuse_weight))
    total_weight = sum(weight for _, weight in weighted)
    if total_weight <= 0:
        raise ValueError("응답된 후기 신호의 가중치 합은 0보다 커야 합니다.")
    return sum(value * weight for value, weight in weighted) / total_weight


def predict(state: dict, features: dict) -> float:
    values = vector(features)
    logit = float(state.get("bias", 0.0)) + sum(
        float(state.get("weights", {}).get(name, 0.0)) * value for name, value in values.items()
    )
    return _sigmoid(logit)


def update_state(
    state: dict,
    features: dict,
    target: float,
    *,
    learning_rate_base: float,
    regularization: float,
) -> dict:
    if not 0 <= target <= 1:
        raise ValueError("개인화 target은 0~1 범위여야 합니다.")
    if learning_rate_base <= 0 or regularization < 0:
        raise ValueError("학습률은 0보다 크고 정규화는 0 이상이어야 합니다.")
    state = {
        "version": 1,
        "bias": float(state.get("bias", 0.0)),
        "weights": {name: float(value) for name, value in state.get("weights", {}).items()},
        "updates": int(state.get("updates", 0)),
    }
    values = vector(features)
    error = target - predict(state, features)
    learning_rate = learning_rate_base / math.sqrt(state["updates"] + 1)
    for name, value in values.items():
        old = state["weights"].get(name, 0.0)
        state["weights"][name] = old + learning_rate * (error * value - regularization * old)
    state["bias"] += learning_rate * error
    state["updates"] += 1
    return state


def blended_rank_score(
    global_probability: float,
    state: dict,
    features: dict,
    *,
    max_personal_share: float,
    prior_reviews: float,
) -> float:
    updates = int(state.get("updates", 0))
    if updates <= 0:
        return global_probability
    personal_share = max_personal_share * updates / (updates + prior_reviews)
    return (1 - personal_share) * global_probability + personal_share * predict(state, features)
