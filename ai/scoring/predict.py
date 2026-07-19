"""
추론 모듈.

XGBoost 점수에 프로필별 로짓 패널티를 적용하고 Softmax로 확률을 계산하여
상위 K개 경로 순위를 반환한다.

로짓 패널티 설계 원칙:
  - 양수 값: 해당 피처가 클수록 불리 (로짓에서 감산)
  - 음수 값: 해당 피처가 클수록 유리 (로짓에서 가산 = 보너스)
  - 베이스라인: 고정 상수. 추후 날씨·혼잡도에 따른 동적 조정으로 확장 예정.
"""
import numpy as np
import pandas as pd

from scoring.train import FEATURE_COLS

# 프로필별 로짓 패널티 테이블 (베이스라인 고정값)
LOGIT_PENALTIES: dict[str, dict[str, float]] = {
    "general": {
        "avg_slope_percent": 0.2,
        "crosswalk_count":   0.1,
        "crowd_level":       0.3,
        "weather_risk":      0.3,
    },
    "elderly": {
        "stair_count":         2.0,
        "avg_slope_percent":   1.5,
        "max_slope_percent":   1.0,
        "transfer_count":      1.2,
        "walk_distance_m":     0.001,
        "crowd_level":         0.8,
        "weather_risk":        1.0,
        "elevator_ratio":     -1.5,   # 엘리베이터 있으면 가산
        "shelter_nearby":     -0.8,   # 쉼터 근접 시 가산
        "smart_shelter_has_ac":-0.6,  # 냉난방 쉘터 근접 시 가산
    },
    "child": {
        "stair_count":              0.5,
        "crosswalk_count":          0.8,
        "crowd_level":              0.5,
        "weather_risk":             0.8,
        "crosswalk_signal_ratio":  -1.0,  # 신호등 많을수록 가산
    },
    "disabled": {
        "stair_count":                3.0,
        "avg_slope_percent":          2.0,
        "max_slope_percent":          1.5,
        "walk_distance_m":            0.0008,
        "elevator_ratio":            -2.0,   # 최대 가산
        "is_low_floor_bus":          -1.5,
        "wheelchair_charger_nearby": -0.5,
    },
}


def _softmax(logits: np.ndarray) -> np.ndarray:
    """수치 안정 Softmax."""
    e = np.exp(logits - logits.max())
    return e / e.sum()


def predict_and_rank(
    rankers: dict,
    route_features_list: list[dict],
    profile: str,
    top_k: int = 3,
) -> list[dict]:
    """
    경로 후보 리스트를 받아 프로필별 추천 순위를 반환한다.

    Parameters
    ----------
    rankers : dict
        train_rankers()가 반환한 {profile: XGBRanker} 딕셔너리.
    route_features_list : list of dict
        경로 후보별 피처 딕셔너리 리스트.
        없는 피처 키는 0으로 자동 처리.
    profile : str
        사용자 프로필 ("general" / "elderly" / "child" / "disabled").
    top_k : int
        반환할 상위 경로 수 (기본 3).

    Returns
    -------
    list of dict
        순위별 결과 리스트.
        각 dict: {"rank", "route_index", "xgb_score", "adjusted_score", "probability"}
    """
    ranker = rankers.get(profile)
    if ranker is None:
        raise ValueError(f"프로필 '{profile}'에 대한 모델이 없습니다.")

    # 없는 피처 키는 0으로 채워 DataFrame 구성
    X = pd.DataFrame([
        {col: feat.get(col, 0) for col in FEATURE_COLS}
        for feat in route_features_list
    ])

    # ① XGBoost 베이스 점수
    xgb_scores = ranker.predict(X)

    # ② 프로필별 로짓 패널티 적용
    penalties = LOGIT_PENALTIES.get(profile, {})
    adjusted  = xgb_scores.astype(float).copy()
    for i, feat_dict in enumerate(route_features_list):
        for feat_name, weight in penalties.items():
            adjusted[i] -= weight * feat_dict.get(feat_name, 0)

    # ③ Softmax → 확률
    probs      = _softmax(adjusted)
    ranked_idx = np.argsort(probs)[::-1][:top_k]

    return [
        {
            "rank":           rank + 1,
            "route_index":    int(idx),
            "xgb_score":      round(float(xgb_scores[idx]), 4),
            "adjusted_score": round(float(adjusted[idx]), 4),
            "probability":    round(float(probs[idx]), 4),
        }
        for rank, idx in enumerate(ranked_idx)
    ]
