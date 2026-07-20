"""9명 이상의 실제 라벨로 프로필별 XGBRanker를 학습한다.

운영 코드에는 합성 라벨 생성 경로가 없다. 라벨과 당시 경로 피처 스냅샷을
분리 보관하고, 동일 OD(group_id)는 항상 같은 평가 분할에 남도록 한다.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import pickle
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd
from xgboost import XGBRanker
from sklearn.metrics import ndcg_score

PROFILES = ["general", "elderly", "child", "youth", "disabled", "pregnant"]
MODEL_DIR = Path("ai/data")
TRAINING_DIR = MODEL_DIR / "training"
DEFAULT_LABELS = TRAINING_DIR / "route_labels.csv"
DEFAULT_FEATURES = TRAINING_DIR / "route_features.jsonl"
MODEL_PATH = MODEL_DIR / "rankers.pkl"
MIN_REVIEWERS = 9

FEATURE_COLS = [
    "avg_slope_percent", "max_slope_percent", "min_slope_percent", "slope_iqr",
    "stair_count", "elevator_ratio", "transfer_count",
    "walk_distance_m", "total_duration_min", "is_low_floor_bus",
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
]


class ModelNotReady(RuntimeError):
    """필수 실제 라벨 또는 검증된 모델이 아직 없는 상태."""


def _read_feature_snapshots(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise ModelNotReady(f"경로 피처 스냅샷 파일이 없습니다: {path}")
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if not rows:
        raise ModelNotReady("경로 피처 스냅샷이 비어 있습니다.")
    flat_rows = []
    for row in rows:
        features = row.get("features") or {}
        flat_rows.append({
            "group_id": str(row["group_id"]),
            "route_id": str(row["route_id"]),
            **{name: features.get(name) for name in FEATURE_COLS},
        })
    result = pd.DataFrame(flat_rows).drop_duplicates(["group_id", "route_id"], keep=False)
    if len(result) != len(flat_rows):
        raise ValueError("group_id와 route_id가 중복된 피처 스냅샷이 있습니다.")
    return result


def load_human_training_data(
    labels_path: Path = DEFAULT_LABELS,
    features_path: Path = DEFAULT_FEATURES,
    min_reviewers: int = MIN_REVIEWERS,
    require_reviewers_per_item: bool = True,
) -> pd.DataFrame:
    """개별 라벨을 OD·경로·프로필별 중앙값 relevance로 집계한다."""
    if not labels_path.exists():
        raise ModelNotReady(f"라벨 파일이 없습니다: {labels_path}")
    labels = pd.read_csv(labels_path, dtype=str)
    required = {"reviewer_id", "group_id", "route_id", "profile", "relevance"}
    missing = required.difference(labels.columns)
    if missing:
        raise ValueError(f"라벨 컬럼 누락: {', '.join(sorted(missing))}")
    labels = labels.dropna(subset=list(required)).copy()
    if labels.empty:
        raise ModelNotReady("실제 사용자 라벨이 비어 있습니다.")
    reviewers = labels["reviewer_id"].nunique()
    if reviewers < min_reviewers:
        raise ModelNotReady(f"최소 {min_reviewers}명의 라벨이 필요합니다. 현재 {reviewers}명입니다.")
    invalid_profiles = sorted(set(labels["profile"]) - set(PROFILES))
    if invalid_profiles:
        raise ValueError(f"지원하지 않는 프로필 라벨: {', '.join(invalid_profiles)}")
    labels["relevance"] = pd.to_numeric(labels["relevance"], errors="raise")
    if not labels["relevance"].between(0, 4).all():
        raise ValueError("relevance는 0~4 범위여야 합니다.")

    if require_reviewers_per_item:
        reviewer_counts = labels.groupby(["group_id", "route_id", "profile"])["reviewer_id"].nunique()
        incomplete = reviewer_counts[reviewer_counts < min_reviewers]
        if not incomplete.empty:
            sample = ", ".join(
                f"{group}/{route}/{profile}={count}명"
                for (group, route, profile), count in incomplete.head(5).items()
            )
            raise ModelNotReady(f"모든 OD·경로·프로필에 최소 {min_reviewers}명의 평가가 필요합니다: {sample}")

    aggregated = (
        labels.groupby(["group_id", "route_id", "profile"], as_index=False)
        .agg(relevance=("relevance", "median"), reviewer_count=("reviewer_id", "nunique"))
    )
    snapshots = _read_feature_snapshots(features_path)
    merged = aggregated.merge(snapshots, on=["group_id", "route_id"], how="inner", validate="many_to_one")
    if merged.empty:
        raise ModelNotReady("라벨과 일치하는 경로 피처 스냅샷이 없습니다.")
    return merged.sort_values(["profile", "group_id", "route_id"]).reset_index(drop=True)


def _validate_profile_frame(profile: str, frame: pd.DataFrame) -> None:
    if frame["group_id"].nunique() < 2:
        raise ModelNotReady(f"{profile}: 서로 다른 OD가 최소 2개 필요합니다.")
    invalid_groups = frame.groupby("group_id").size()
    if (invalid_groups < 2).any():
        ids = ", ".join(map(str, invalid_groups[invalid_groups < 2].index[:5]))
        raise ValueError(f"{profile}: 후보가 1개뿐인 OD가 있습니다: {ids}")
    if frame["relevance"].nunique() < 2:
        raise ModelNotReady(f"{profile}: 서로 다른 relevance 라벨이 필요합니다.")


def _new_ranker() -> XGBRanker:
    return XGBRanker(
        objective="rank:pairwise",
        eval_metric="ndcg@3",
        max_depth=5,
        learning_rate=0.04,
        n_estimators=250,
        subsample=0.85,
        colsample_bytree=0.85,
        min_child_weight=2,
        tree_method="hist",
        n_jobs=1,
        random_state=42,
    )


def _group_holdout_metrics(profile: str, frame: pd.DataFrame) -> dict:
    """OD 그룹을 분리한 결정적 20% holdout 진단. 최종 모델은 이후 전체 자료로 재학습한다."""
    groups = sorted(frame["group_id"].unique(), key=lambda value: hashlib.sha256(f"{profile}:{value}".encode()).hexdigest())
    if len(groups) < 3:
        return {"status": "insufficient_groups", "train_od_count": len(groups), "validation_od_count": 0}
    validation_count = max(1, round(len(groups) * 0.2))
    validation_groups = set(groups[:validation_count])
    train = frame[~frame["group_id"].isin(validation_groups)].sort_values("group_id")
    valid = frame[frame["group_id"].isin(validation_groups)].sort_values("group_id")
    model = _new_ranker()
    model.fit(
        train[FEATURE_COLS].apply(pd.to_numeric, errors="coerce"),
        train["relevance"].astype(float),
        group=train.groupby("group_id", sort=False).size().to_numpy(),
        verbose=False,
    )
    predictions = model.predict(valid[FEATURE_COLS].apply(pd.to_numeric, errors="coerce"))
    valid = valid.assign(_prediction=predictions)
    ndcg_values: list[float] = []
    correct_pairs = 0
    compared_pairs = 0
    for _, group in valid.groupby("group_id", sort=False):
        truth = group["relevance"].astype(float).to_numpy()
        predicted = group["_prediction"].astype(float).to_numpy()
        ndcg_values.append(float(ndcg_score([truth], [predicted], k=min(3, len(group)))))
        for left in range(len(group)):
            for right in range(left + 1, len(group)):
                truth_diff = truth[left] - truth[right]
                if truth_diff == 0:
                    continue
                compared_pairs += 1
                correct_pairs += int((predicted[left] - predicted[right]) * truth_diff > 0)
    return {
        "status": "evaluated",
        "train_od_count": int(train["group_id"].nunique()),
        "validation_od_count": int(valid["group_id"].nunique()),
        "ndcg_at_3": round(sum(ndcg_values) / len(ndcg_values), 6),
        "pairwise_accuracy": round(correct_pairs / compared_pairs, 6) if compared_pairs else None,
        "compared_pairs": compared_pairs,
    }


def train_rankers(df: pd.DataFrame | None = None, output_path: Path = MODEL_PATH) -> dict:
    """실제 라벨 데이터로만 프로필별 모델을 학습하고 버전 메타데이터와 저장한다."""
    frame = load_human_training_data() if df is None else df.copy()
    missing = {"group_id", "profile", "relevance", *FEATURE_COLS}.difference(frame.columns)
    if missing:
        raise ValueError(f"학습 데이터 컬럼 누락: {', '.join(sorted(missing))}")

    rankers: dict[str, XGBRanker] = {}
    metrics: dict[str, dict] = {}
    for profile in PROFILES:
        profile_df = frame[frame["profile"] == profile].sort_values("group_id").reset_index(drop=True)
        if profile_df.empty:
            continue
        _validate_profile_frame(profile, profile_df)
        X = profile_df[FEATURE_COLS].apply(pd.to_numeric, errors="coerce")
        y = profile_df["relevance"].astype(float)
        groups = profile_df.groupby("group_id", sort=False).size().to_numpy()
        validation = _group_holdout_metrics(profile, profile_df)
        ranker = _new_ranker()
        ranker.fit(X, y, group=groups, verbose=False)
        rankers[profile] = ranker
        metrics[profile] = {
            "route_count": int(len(profile_df)),
            "od_count": int(profile_df["group_id"].nunique()),
            "reviewer_count_min": int(profile_df.get("reviewer_count", pd.Series([0])).min()),
            "group_holdout": validation,
        }

    if not rankers:
        raise ModelNotReady("학습 가능한 프로필 라벨이 없습니다.")
    payload = {
        "model_version": f"xgboost-human-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}",
        "trained_at": datetime.now(UTC).isoformat(),
        "feature_columns": FEATURE_COLS,
        "profiles": rankers,
        "metrics": metrics,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("wb") as handle:
        pickle.dump(payload, handle)
    return rankers


def load_rankers(path: Path = MODEL_PATH) -> dict:
    if not path.exists():
        raise ModelNotReady(
            "검증된 실제 라벨 모델이 없습니다. route_labels.csv와 route_features.jsonl을 완성한 뒤 학습하세요."
        )
    with path.open("rb") as handle:
        payload = pickle.load(handle)
    if not isinstance(payload, dict) or payload.get("feature_columns") != FEATURE_COLS:
        raise ModelNotReady("모델 피처 스키마가 현재 코드와 일치하지 않습니다. 재학습이 필요합니다.")
    profiles = payload.get("profiles")
    if not isinstance(profiles, dict) or not profiles:
        raise ModelNotReady("모델 파일에 프로필 모델이 없습니다.")
    return profiles


def load_model_metadata(path: Path = MODEL_PATH) -> dict:
    """모델 객체를 제외한 버전·학습시각·검증 요약을 반환한다."""
    if not path.exists():
        raise ModelNotReady("검증된 실제 라벨 모델이 없습니다.")
    with path.open("rb") as handle:
        payload = pickle.load(handle)
    return {
        "model_version": payload.get("model_version"),
        "trained_at": payload.get("trained_at"),
        "metrics": payload.get("metrics") or {},
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="실제 라벨 기반 XGBRanker 학습")
    parser.add_argument("--labels", type=Path, default=DEFAULT_LABELS)
    parser.add_argument("--features", type=Path, default=DEFAULT_FEATURES)
    parser.add_argument("--output", type=Path, default=MODEL_PATH)
    args = parser.parse_args()
    data = load_human_training_data(args.labels, args.features)
    models = train_rankers(data, args.output)
    print(f"학습 완료: {args.output} ({', '.join(models)})")


if __name__ == "__main__":
    main()
