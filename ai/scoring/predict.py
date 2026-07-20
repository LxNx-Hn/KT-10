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
        "stair_count":             1.0,
        "avg_slope_percent":       0.3,
        "max_slope_percent":       0.1,
        "transfer_count":          1.0,
        "total_duration_min":      0.05,
        "weather_risk":            0.1,
        "crowd_level":             0.3,
        "elevator_ratio":         -0.5,
        "is_low_floor_bus":       -0.5,
        "shelter_nearby":         -0.3,
        "crosswalk_signal_ratio": -0.2,
    },
    "elderly": {
        "stair_count":             5.0,
        "avg_slope_percent":       1.5,
        "max_slope_percent":       1.0,
        "slope_iqr":               0.5,
        "transfer_count":          2.0,
        "total_duration_min":      0.1,
        "weather_risk":            0.4,
        "crowd_level":             0.8,
        "elevator_ratio":         -2.0,
        "is_low_floor_bus":       -1.5,
        "shelter_nearby":         -1.5,
        "smart_shelter_has_ac":   -0.8,
        "crosswalk_signal_ratio": -0.8,
        "aed_nearby":             -0.5,
    },
    "child": {
        "stair_count":             1.5,
        "avg_slope_percent":       0.5,
        "max_slope_percent":       0.3,
        "transfer_count":          1.5,
        "total_duration_min":      0.08,
        "weather_risk":            0.2,
        "crowd_level":             0.5,
        "elevator_ratio":         -0.3,
        "is_low_floor_bus":       -0.5,
        "shelter_nearby":         -0.5,
        "crosswalk_signal_ratio": -2.0,  # 최중요
        "cctv_density_50m":       -1.0,
    },
    "teen": {
        "stair_count":             1.0,
        "avg_slope_percent":       0.3,
        "transfer_count":          1.0,
        "total_duration_min":      0.1,
        "weather_risk":            0.1,
        "crowd_level":             0.2,
        "crosswalk_signal_ratio": -0.5,
        "cctv_density_50m":       -0.5,
    },
    "disabled": {
        "stair_count":                  8.0,  # 최대 패널티
        "avg_slope_percent":            2.0,
        "max_slope_percent":            1.5,
        "slope_iqr":                    0.8,
        "transfer_count":               1.5,
        "total_duration_min":           0.08,
        "weather_risk":                 0.2,
        "crowd_level":                  0.6,
        "elevator_ratio":              -4.0,  # 최대 가산
        "is_low_floor_bus":            -3.0,  # 최대 가산
        "wheelchair_charger_nearby":   -1.0,
        "shelter_nearby":              -0.8,
        "crosswalk_signal_ratio":      -0.5,
    },
    "pregnant": {
        "stair_count":             3.0,
        "avg_slope_percent":       1.2,
        "max_slope_percent":       0.8,
        "transfer_count":          2.0,
        "total_duration_min":      0.1,
        "weather_risk":            0.5,  # 민감도 최고
        "crowd_level":             1.0,  # 혼잡 최대 회피
        "elevator_ratio":         -1.5,
        "is_low_floor_bus":       -1.5,
        "shelter_nearby":         -2.0,  # 최대 가산
        "smart_shelter_has_ac":   -1.2,
        "crosswalk_signal_ratio": -1.0,
        "aed_nearby":             -0.5,
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
        사용자 프로필 ("general" / "elderly" / "child" / "teen" / "disabled" / "pregnant").
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
