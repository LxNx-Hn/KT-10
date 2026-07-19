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

PROFILES   = ["general", "elderly", "child", "disabled"]
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
    # 편의시설 (공간 데이터 기반 — extractor.py 출력)
    "shelter_nearby", "aed_nearby", "wheelchair_charger_nearby",
    "smart_shelter_nearby", "smart_shelter_has_ac",
    # 부산 특화 (공간 데이터 기반 — extractor.py 출력)
    "dongbaekjeon_store_count_200m", "bus_stop_count_200m",
    # 환경 (수동 입력)
    "crowd_level", "weather_risk",
]


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
                # 편의시설
                "shelter_nearby":            int(np.random.randint(0, 2)),
                "aed_nearby":                int(np.random.randint(0, 2)),
                "wheelchair_charger_nearby": int(np.random.randint(0, 2)),
                "smart_shelter_nearby":      int(np.random.randint(0, 2)),
                "smart_shelter_has_ac":      int(np.random.randint(0, 2)),
                # 부산 특화
                "dongbaekjeon_store_count_200m": int(np.random.randint(0, 30)),
                "bus_stop_count_200m":           int(np.random.randint(0, 8)),
                # 환경
                "crowd_level":  float(np.random.uniform(0, 1)),
                "weather_risk": float(np.random.uniform(0, 30)),
            }
            # 프로필별 라벨: 해당 프로필에 유리한 피처일수록 높은 순위
            rec["label_general"]  = int((-rec["avg_slope_percent"] * 0.1 + np.random.randn()) > 0)
            rec["label_elderly"]  = int((-rec["stair_count"] + rec["elevator_ratio"] * 2 + np.random.randn()) > 0)
            rec["label_child"]    = int((rec["crosswalk_signal_ratio"] * 2 - rec["crosswalk_count"] * 0.2 + np.random.randn()) > 0)
            rec["label_disabled"] = int((-rec["stair_count"] * 2 + rec["elevator_ratio"] * 3 + rec["is_low_floor_bus"] * 2 + np.random.randn()) > 0)
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
