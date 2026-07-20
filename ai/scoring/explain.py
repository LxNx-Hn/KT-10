"""SHAP 기반 추천 이유 자동 생성 모듈."""
import shap
import pandas as pd

from scoring.train import FEATURE_COLS

# 피처별 (긍정 메시지, 부정 메시지) 쌍
# None은 해당 방향으로 메시지를 생성하지 않음
REASON_MAP: dict[str, tuple[str | None, str | None]] = {
    "elevator_ratio":              ("승강기로 이동할 수 있어 계단을 피할 수 있어요", "승강기 접근이 어려운 구간이 있어요"),
    "stair_count":                 ("계단이 없는 편이에요", "계단이 많아 이동이 불편할 수 있어요"),
    "avg_slope_percent":           ("평지 위주의 경로예요", "경사 구간이 있어요"),
    "max_slope_percent":           ("가장 가파른 구간도 완만한 편이에요", "급경사 구간이 포함돼 있어요"),
    "transfer_count":              ("환승 없이 한 번에 이동해요", "환승이 있는 경로예요"),
    "crowd_level":                 ("혼잡하지 않은 경로예요", "혼잡한 구간이 포함돼 있어요"),
    "is_low_floor_bus":            ("저상버스가 포함된 경로예요", "저상버스가 없는 경로예요"),
    "crosswalk_signal_ratio":      ("신호등 있는 횡단보도 위주예요", "신호등 없는 횡단보도가 포함돼 있어요"),
    "shelter_nearby":              ("경로 근처에 쉼터가 있어요", None),
    "smart_shelter_has_ac":        ("냉난방 가능한 버스쉘터가 근처에 있어요", None),
    "aed_nearby":                  ("경로 근처에 AED가 설치돼 있어요", None),
    "wheelchair_charger_nearby":   ("경로 근처에 전동휠체어 충전기가 있어요", None),
    "dongbaekjeon_store_count_300m":("동백전 가맹점이 많은 구역을 지나요", None),
    "cctv_density_50m":            ("CCTV가 잘 설치된 안전한 경로예요", "CCTV가 적은 구간이 있어요"),
}

# 기존 REASON_MAP 에 없는 키만 추가 (crowd_level, smart_shelter_has_ac,
# wheelchair_charger_nearby, aed_nearby는 이미 위에 존재하므로 제외)
REASON_MAP.update({
    "slope_iqr": (
        "경사 변화가 완만한 편이에요",
        "경사가 구간마다 들쭉날쭉해요",
    ),
    "total_duration_min": (
        "이동 시간이 짧은 경로예요",
        "이동 시간이 다소 걸리는 경로예요",
    ),
    "accident_zone_count": (
        "사고 위험 구간을 피한 경로예요",
        "사고다발구간이 포함돼 있어요",
    ),
})


def generate_reasons(
    ranker,
    X_route: pd.DataFrame,
    top_n: int = 4,
) -> list[str]:
    """
    학습된 XGBRanker와 SHAP을 활용해 추천 이유 문장 리스트를 반환한다.

    Parameters
    ----------
    ranker : XGBRanker
        학습된 모델.
    X_route : pd.DataFrame
        경로 1개의 피처 DataFrame (1행). 컬럼은 FEATURE_COLS와 일치해야 함.
    top_n : int
        반환할 이유 문장 최대 개수 (기본 4).

    Returns
    -------
    list of str
        추천 이유 문장 리스트.
    """
    explainer   = shap.TreeExplainer(ranker)
    shap_values = explainer.shap_values(X_route)

    # SHAP 절댓값 기준 상위 피처 선택
    top_feats = (
        pd.Series(shap_values[0], index=X_route.columns)
        .abs()
        .nlargest(top_n)
        .index
    )

    reasons = []
    for feat in top_feats:
        if feat not in REASON_MAP:
            continue
        pos_msg, neg_msg = REASON_MAP[feat]
        shap_val = shap_values[0][X_route.columns.get_loc(feat)]
        msg = pos_msg if shap_val > 0 else neg_msg
        if msg:
            reasons.append(msg)

    return reasons
