"""
XGBRanker 학습 모듈.

현재는 가상 데이터(synthetic data)로 파이프라인 구조를 검증한다.
실데이터 수신 후 generate_synthetic_data()를 실제 데이터 로딩으로 교체한다.
"""
import pickle
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.model_selection import GroupKFold
from xgboost import XGBRanker

PROFILES   = ["general", "elderly", "child", "teen", "disabled", "pregnant"]
MODEL_DIR  = Path("ai/data")

# 전체 피처 컬럼 (API 경로 응답 기반 피처 + 공간 데이터 기반 피처)
FEATURE_COLS = [
    # 경사·지형 (API 경로 응답 기반 — 실데이터 수신 후 채워짐)
    "avg_slope_percent", "max_slope_percent", "min_slope_percent", "slope_iqr",
    # 이동·접근성 (API 경로 응답 기반)
    "stair_count", "elevator_ratio", "transfer_count",
    "walk_distance_m", "total_duration_min", "is_low_floor_bus",
    # 안전 (공간 데이터 기반 — extractor.py 출력)
    "cctv_density_50m", "crosswalk_count", "crosswalk_signal_ratio",
    "accident_zone_count",
    # 편의시설 (공간 데이터 기반 — extractor.py 출력)
    "shelter_nearby", "aed_nearby", "wheelchair_charger_nearby",
    "smart_shelter_nearby", "smart_shelter_has_ac",
    # 부산 특화 (공간 데이터 기반 — extractor.py 출력)
    "dongbaekjeon_store_count_300m", "bus_stop_count_200m",
    # 환경 (수동 입력)
    "crowd_level", "weather_risk",
]


def auto_label(features: dict, profile: str) -> float:
    """
    규칙 기반 경로 선호 점수 생성 (0~1).

    기준점 10.0에서 패널티를 빼고 가산을 더한 뒤 0~1로 정규화.
    도보 거리(walk_distance_m): 1km 초과분에만 패널티 적용.

    프로필별 핵심:
      general  : 소요시간·환승 최소화
      elderly  : 계단·경사 최소화, 쉼터·엘리베이터 최중요
      child    : 신호등 횡단보도·CCTV 최중요
      teen     : general 유사, 이동시간·야간 안전성 중요
      disabled : 계단 절대 회피(최대 패널티), 엘리베이터·저상버스 최대 가산
      pregnant : elderly 유사, 날씨 민감도 최고, 혼잡 최대 회피

    ⚠️ 실제 사용자 선택 데이터 수집 후 이 함수를 교체한다.
    """
    stair      = features.get("stair_count", 0)
    slope_avg  = features.get("avg_slope_percent", 0)
    slope_max  = features.get("max_slope_percent", 0)
    slope_iqr  = features.get("slope_iqr", 0)
    elevator   = features.get("elevator_ratio", 0)
    transfer   = features.get("transfer_count", 0)
    walk_m     = features.get("walk_distance_m", 0)
    duration   = features.get("total_duration_min", 0)
    low_floor  = features.get("is_low_floor_bus", 0)
    weather    = features.get("weather_risk", 0)
    shelter    = features.get("shelter_nearby", 0)
    signal_r   = features.get("crosswalk_signal_ratio", 1.0)
    cctv       = features.get("cctv_density_50m", 0)
    crowd      = features.get("crowd_level", 0.5)
    smart_ac   = features.get("smart_shelter_has_ac", 0)
    aed        = features.get("aed_nearby", 0)
    wc_charger = features.get("wheelchair_charger_nearby", 0)

    # 1km 초과 도보 거리 (100m 단위, 초과분에만 패널티)
    walk_excess = max(0.0, walk_m - 1000.0) / 100.0

    score = 10.0

    if profile == "general":
        score -= stair     * 1.0
        score -= slope_avg * 0.3
        score -= slope_max * 0.1
        score -= transfer  * 1.0
        score -= duration  * 0.05
        score -= weather   * 0.1
        score -= crowd     * 0.3
        score += elevator  * 0.5
        score += low_floor * 0.5
        score += shelter   * 0.3
        score += signal_r  * 0.2
        score += cctv      * 0.2

    elif profile == "elderly":
        score -= stair       * 5.0
        score -= slope_avg   * 1.5
        score -= slope_max   * 1.0
        score -= slope_iqr   * 0.5
        score -= transfer    * 2.0
        score -= walk_excess * 0.5
        score -= duration    * 0.1
        score -= weather     * 0.4
        score -= crowd       * 0.8
        score += elevator    * 2.0
        score += low_floor   * 1.5
        score += shelter     * 1.5
        score += smart_ac    * 0.8
        score += signal_r    * 0.8
        score += aed         * 0.5

    elif profile == "child":
        score -= stair       * 1.5
        score -= slope_avg   * 0.5
        score -= slope_max   * 0.3
        score -= transfer    * 1.5
        score -= walk_excess * 0.3
        score -= duration    * 0.08
        score -= weather     * 0.2
        score -= crowd       * 0.5
        score += elevator    * 0.3
        score += low_floor   * 0.5
        score += shelter     * 0.5
        score += signal_r    * 2.0   # 신호등 횡단보도 최중요
        score += cctv        * 1.0

    elif profile == "teen":
        score -= stair     * 1.0
        score -= slope_avg * 0.3
        score -= transfer  * 1.0
        score -= duration  * 0.1
        score -= weather   * 0.1
        score -= crowd     * 0.2
        score += elevator  * 0.2
        score += low_floor * 0.3
        score += signal_r  * 0.5
        score += cctv      * 0.5   # 야간 안전성

    elif profile == "disabled":
        score -= stair       * 8.0   # 최대 패널티
        score -= slope_avg   * 2.0
        score -= slope_max   * 1.5
        score -= slope_iqr   * 0.8
        score -= transfer    * 1.5
        score -= walk_excess * 0.4
        score -= duration    * 0.08
        score -= weather     * 0.2
        score -= crowd       * 0.6
        score += elevator    * 4.0   # 최대 가산
        score += low_floor   * 3.0   # 최대 가산
        score += wc_charger  * 1.0
        score += shelter     * 0.8
        score += signal_r    * 0.5

    elif profile == "pregnant":
        score -= stair       * 3.0
        score -= slope_avg   * 1.2
        score -= slope_max   * 0.8
        score -= transfer    * 2.0
        score -= walk_excess * 0.5
        score -= duration    * 0.1
        score -= weather     * 0.5   # 날씨 민감도 최고
        score -= crowd       * 1.0   # 혼잡 최대 회피
        score += elevator    * 1.5
        score += low_floor   * 1.5
        score += shelter     * 2.0   # 쉼터 최대 가산
        score += smart_ac    * 1.2
        score += signal_r    * 1.0
        score += aed         * 0.5

    return max(0.0, min(1.0, score / 10.0))


def generate_synthetic_data(n_groups: int = 300, n_routes: int = 3, seed: int = 42) -> pd.DataFrame:
    """
    가상 경로 데이터 생성.

    ⚠️ 실데이터 수신 후 이 함수를 실제 데이터 로딩으로 교체한다.
    함수 시그니처(반환 타입 포함)는 유지하여 train_rankers()와의 호환성 보존.
    """
    np.random.seed(seed)
    records = []

    for g in range(n_groups):
        for _ in range(n_routes):
            slope_vals = np.random.uniform(0, 20, 10)
            rec = {
                "group_id": g,
                # 경사
                "avg_slope_percent": float(slope_vals.mean()),
                "max_slope_percent": float(slope_vals.max()),
                "min_slope_percent": float(np.random.uniform(-10, 0)),
                "slope_iqr":         float(np.percentile(slope_vals, 75) - np.percentile(slope_vals, 25)),
                # 이동
                "stair_count":       int(np.random.randint(0, 10)),
                "elevator_ratio":    float(np.random.uniform(0, 1)),
                "transfer_count":    int(np.random.randint(0, 3)),
                "walk_distance_m":   float(np.random.uniform(100, 2000)),
                "total_duration_min":float(np.random.uniform(5, 60)),
                "is_low_floor_bus":  int(np.random.choice([0, 1])),
                # 안전 (공간 데이터 기반)
                "cctv_density_50m":          float(np.random.uniform(0, 5)),
                "crosswalk_count":           int(np.random.randint(0, 10)),
                "crosswalk_signal_ratio":    float(np.random.uniform(0, 1)),
                "accident_zone_count":       int(np.random.randint(0, 3)),
                # 편의시설
                "shelter_nearby":            int(np.random.randint(0, 2)),
                "aed_nearby":                int(np.random.randint(0, 2)),
                "wheelchair_charger_nearby": int(np.random.randint(0, 2)),
                "smart_shelter_nearby":      int(np.random.randint(0, 2)),
                "smart_shelter_has_ac":      int(np.random.randint(0, 2)),
                # 부산 특화
                "dongbaekjeon_store_count_300m": int(np.random.randint(0, 30)),
                "bus_stop_count_200m":           int(np.random.randint(0, 8)),
                # 환경
                "crowd_level":  float(np.random.uniform(0, 1)),
                "weather_risk": float(np.random.uniform(0, 30)),
            }
            # 프로필별 라벨: auto_label()의 연속 점수(0~1)를 XGBRanker가 요구하는
            # 0 이상 정수 relevance 등급(0~4, 5단계)으로 이산화한다.
            # (rank:pairwise는 label_is_integer 제약이 있어 연속값을 그대로 못 씀)
            for profile in PROFILES:
                rec[f"label_{profile}"] = round(auto_label(rec, profile) * 4)
            records.append(rec)

    return pd.DataFrame(records)


def train_rankers(df: pd.DataFrame = None) -> dict:
    """
    프로필별 XGBRanker를 GroupKFold CV로 학습하고 dict로 반환한다.

    Parameters
    ----------
    df : pd.DataFrame, optional
        학습 데이터. None이면 가상 데이터로 학습.

    Returns
    -------
    dict
        profile명 → XGBRanker 딕셔너리.
    """
    if df is None:
        print("📊 가상 데이터로 학습 (실데이터 수신 후 교체 필요)")
        df = generate_synthetic_data()

    X      = df[FEATURE_COLS]
    gkf    = GroupKFold(n_splits=5)
    rankers = {}

    for profile in PROFILES:
        y      = df[f"label_{profile}"]
        groups = df.groupby("group_id").size().values

        ranker = XGBRanker(
            objective="rank:pairwise",
            max_depth=6,
            learning_rate=0.05,
            n_estimators=300,
            subsample=0.8,
            colsample_bytree=0.8,
            min_child_weight=3,
            tree_method="hist",
            random_state=42,
        )

        for tr_idx, val_idx in gkf.split(X, y, groups=df["group_id"]):
            g_tr  = df.iloc[tr_idx].groupby("group_id").size().values
            g_val = df.iloc[val_idx].groupby("group_id").size().values
            ranker.fit(
                X.iloc[tr_idx], y.iloc[tr_idx], group=g_tr,
                eval_set=[(X.iloc[val_idx], y.iloc[val_idx])],
                eval_group=[g_val],
                verbose=False,
            )

        rankers[profile] = ranker
        print(f"  [{profile}] 학습 완료")

    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    with open(MODEL_DIR / "rankers.pkl", "wb") as f:
        pickle.dump(rankers, f)
    print(f"✅ 모델 저장: {MODEL_DIR / 'rankers.pkl'}")
    return rankers


def load_rankers() -> dict:
    """저장된 모델을 로딩. 없으면 가상 데이터로 새로 학습."""
    model_path = MODEL_DIR / "rankers.pkl"
    if not model_path.exists():
        print("⚠️ 저장된 모델 없음 → 새로 학습")
        return train_rankers()
    with open(model_path, "rb") as f:
        return pickle.load(f)
