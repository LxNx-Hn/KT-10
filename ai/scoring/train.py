"""9명 이상의 실제 라벨로 프로필별 XGBRanker를 학습한다.

운영 코드에는 합성 라벨 생성 경로가 없다. 라벨과 당시 경로 피처 스냅샷을
분리 보관하고, 동일 OD(group_id)는 항상 같은 평가 분할에 남도록 한다.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

import numpy as np
import pandas as pd
from xgboost import XGBRanker
from sklearn.metrics import ndcg_score

from .artifacts import ArtifactError, read_ranker_artifact, write_ranker_artifact
from .schema import FEATURE_COLS, MIN_REVIEWERS
from .snapshots import validate_live_feature_snapshot

PROFILES = ["general", "elderly", "child", "youth", "disabled", "pregnant"]
MODEL_DIR = Path("ai/data")
TRAINING_DIR = MODEL_DIR / "training"
DEFAULT_LABELS = TRAINING_DIR / "route_labels.csv"
DEFAULT_FEATURES = TRAINING_DIR / "route_features.jsonl"
MODEL_PATH = MODEL_DIR / "rankers.human-validated.zip"
HUMAN_CANDIDATE_PATH = MODEL_DIR / "rankers.human-candidate.zip"


class ModelNotReady(RuntimeError):
    """필수 실제 라벨 또는 검증된 모델이 아직 없는 상태."""


def _read_feature_snapshots(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise ModelNotReady(f"경로 피처 스냅샷 파일이 없습니다: {path}")
    rows = []
    for line_number, line in enumerate(
        path.read_text(encoding="utf-8").splitlines(),
        start=1,
    ):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
            validate_live_feature_snapshot(row, FEATURE_COLS)
        except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
            raise ValueError(
                f"경로 피처 스냅샷 {line_number}행: {exc}"
            ) from exc
        rows.append(row)
    if not rows:
        raise ModelNotReady("경로 피처 스냅샷이 비어 있습니다.")
    flat_rows = []
    for row in rows:
        features = row.get("features") or {}
        flat_rows.append({
            "group_id": str(row["group_id"]),
            "holdout_group_id": str(
                row.get("holdout_group_id") or row["group_id"]
            ),
            "route_id": str(row["route_id"]),
            "feature_snapshot_hash": str(row["feature_snapshot_hash"]),
            **{name: features.get(name) for name in FEATURE_COLS},
        })
    result = pd.DataFrame(flat_rows).drop_duplicates(["group_id", "route_id"], keep=False)
    if len(result) != len(flat_rows):
        raise ValueError("group_id와 route_id가 중복된 피처 스냅샷이 있습니다.")
    return result


def _load_training_data(
    labels_path: Path = DEFAULT_LABELS,
    features_path: Path = DEFAULT_FEATURES,
    min_reviewers: int = MIN_REVIEWERS,
    require_reviewers_per_item: bool = True,
    *,
    relevance_contract: Literal["integer_ordinal", "continuous_review"],
) -> pd.DataFrame:
    """검증된 개별 라벨을 OD·경로·프로필별 중앙값 relevance로 집계한다."""
    if not labels_path.exists():
        raise ModelNotReady(f"라벨 파일이 없습니다: {labels_path}")
    labels = pd.read_csv(labels_path, dtype=str)
    required = {
        "reviewer_id",
        "group_id",
        "route_id",
        "feature_snapshot_hash",
        "profile",
        "relevance",
    }
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
    relevance_is_finite = np.isfinite(labels["relevance"].to_numpy(dtype=float))
    if not relevance_is_finite.all() or not labels["relevance"].between(0, 4).all():
        raise ValueError("relevance는 0~4 범위의 유한한 숫자여야 합니다.")
    if (
        relevance_contract == "integer_ordinal"
        and not (labels["relevance"] % 1 == 0).all()
    ):
        raise ValueError("사람 라벨 relevance는 0~4 범위의 정수여야 합니다.")
    duplicate_label = labels.duplicated(
        ["reviewer_id", "group_id", "route_id", "profile"],
        keep=False,
    )
    if duplicate_label.any():
        row = labels.loc[duplicate_label].iloc[0]
        raise ValueError(
            "동일 평가자의 중복 라벨이 있습니다: "
            f"{row['reviewer_id']}/{row['group_id']}/"
            f"{row['route_id']}/{row['profile']}"
        )
    hash_counts = labels.groupby(
        ["group_id", "route_id", "profile"]
    )["feature_snapshot_hash"].nunique()
    if (hash_counts != 1).any():
        group_id, route_id, profile = hash_counts[hash_counts != 1].index[0]
        raise ValueError(
            "한 평가 항목에 서로 다른 피처 스냅샷 해시가 섞였습니다: "
            f"{group_id}/{route_id}/{profile}"
        )

    snapshots = _read_feature_snapshots(features_path)
    snapshot_routes = set(zip(snapshots["group_id"], snapshots["route_id"]))
    label_routes = set(zip(labels["group_id"], labels["route_id"]))
    if snapshot_routes != label_routes:
        raise ValueError(
            "라벨과 피처 스냅샷의 경로 집합이 일치하지 않습니다. "
            f"라벨만 {len(label_routes - snapshot_routes)}건, "
            f"스냅샷만 {len(snapshot_routes - label_routes)}건"
        )
    if require_reviewers_per_item:
        actual_items = set(zip(
            labels["group_id"],
            labels["route_id"],
            labels["profile"],
        ))
        expected_items = {
            (group_id, route_id, profile)
            for group_id, route_id in snapshot_routes
            for profile in PROFILES
        }
        if actual_items != expected_items:
            raise ModelNotReady(
                "모든 경로 스냅샷에 6개 프로필 평가가 필요합니다. "
                f"누락 {len(expected_items - actual_items)}건, "
                f"알 수 없는 평가 {len(actual_items - expected_items)}건"
            )
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
        .agg(
            relevance=("relevance", "median"),
            reviewer_count=("reviewer_id", "nunique"),
            feature_snapshot_hash=("feature_snapshot_hash", "first"),
        )
    )
    merged = aggregated.merge(
        snapshots,
        on=["group_id", "route_id"],
        how="left",
        validate="many_to_one",
        suffixes=("_label", "_snapshot"),
        indicator=True,
    )
    if (merged["_merge"] != "both").any():
        raise ValueError("라벨에 대응하는 경로 피처 스냅샷이 없습니다.")
    stale = (
        merged["feature_snapshot_hash_label"]
        != merged["feature_snapshot_hash_snapshot"]
    )
    if stale.any():
        row = merged.loc[stale].iloc[0]
        raise ValueError(
            "라벨이 현재 피처 스냅샷 해시와 일치하지 않습니다: "
            f"{row['group_id']}/{row['route_id']}"
        )
    return merged.sort_values(["profile", "group_id", "route_id"]).reset_index(drop=True)


def load_human_training_data(
    labels_path: Path = DEFAULT_LABELS,
    features_path: Path = DEFAULT_FEATURES,
    min_reviewers: int = MIN_REVIEWERS,
    require_reviewers_per_item: bool = True,
) -> pd.DataFrame:
    """사람이 직접 매긴 0~4 정수 서열 라벨만 불러온다."""
    return _load_training_data(
        labels_path,
        features_path,
        min_reviewers,
        require_reviewers_per_item,
        relevance_contract="integer_ordinal",
    )


def load_consented_review_training_data(
    labels_path: Path,
    features_path: Path,
    min_reviewers: int = MIN_REVIEWERS,
) -> pd.DataFrame:
    """동의 후기에서 계산한 0~4 유한 연속 relevance를 반올림 없이 불러온다."""
    return _load_training_data(
        labels_path,
        features_path,
        min_reviewers,
        False,
        relevance_contract="continuous_review",
    )


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
    holdout_column = (
        "holdout_group_id"
        if "holdout_group_id" in frame.columns
        else "group_id"
    )
    groups = sorted(
        frame[holdout_column].unique(),
        key=lambda value: hashlib.sha256(
            f"{profile}:{value}".encode()
        ).hexdigest(),
    )
    if len(groups) < 3:
        return {"status": "insufficient_groups", "train_od_count": len(groups), "validation_od_count": 0}
    validation_count = max(1, round(len(groups) * 0.2))
    validation_groups = set(groups[:validation_count])
    train = frame[
        ~frame[holdout_column].isin(validation_groups)
    ].sort_values("group_id")
    valid = frame[
        frame[holdout_column].isin(validation_groups)
    ].sort_values("group_id")
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
        "train_od_count": int(train[holdout_column].nunique()),
        "validation_od_count": int(valid[holdout_column].nunique()),
        "train_query_group_count": int(train["group_id"].nunique()),
        "validation_query_group_count": int(valid["group_id"].nunique()),
        "ndcg_at_3": round(sum(ndcg_values) / len(ndcg_values), 6),
        "pairwise_accuracy": round(correct_pairs / compared_pairs, 6) if compared_pairs else None,
        "compared_pairs": compared_pairs,
    }


def train_rankers(
    df: pd.DataFrame | None = None,
    output_path: Path = HUMAN_CANDIDATE_PATH,
    *,
    label_origin: str = "human_reviewers",
    training_lineage: dict | None = None,
    candidate_tier: Literal[
        "human_candidate", "review_mixed_candidate"
    ] = "human_candidate",
) -> dict:
    """실제 라벨로 수동 승인 전 candidate artifact를 만든다."""
    if (
        candidate_tier == "human_candidate"
        and label_origin != "human_reviewers"
    ):
        raise ValueError(
            "human_candidate tier에는 human_reviewers 라벨만 허용됩니다."
        )
    if (
        candidate_tier == "review_mixed_candidate"
        and label_origin != "human_reviewers_and_consented_reviews"
    ):
        raise ValueError(
            "review_mixed_candidate tier에는 사람 라벨과 동의 후기 혼합 출처가 필요합니다."
        )
    frame = load_human_training_data() if df is None else df.copy()
    missing = {"group_id", "profile", "relevance", *FEATURE_COLS}.difference(frame.columns)
    if missing:
        raise ValueError(f"학습 데이터 컬럼 누락: {', '.join(sorted(missing))}")
    invalid_profiles = sorted(set(frame["profile"]) - set(PROFILES))
    if invalid_profiles:
        raise ValueError(f"지원하지 않는 프로필 라벨: {', '.join(invalid_profiles)}")
    missing_profiles = sorted(set(PROFILES) - set(frame["profile"]))
    if missing_profiles:
        raise ModelNotReady(
            "운영 모델에는 6개 프로필이 모두 필요합니다: "
            + ", ".join(missing_profiles)
        )

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
            "od_count": int(
                profile_df.get(
                    "holdout_group_id",
                    profile_df["group_id"],
                ).nunique()
            ),
            "query_group_count": int(profile_df["group_id"].nunique()),
            "reviewer_count_min": int(profile_df.get("reviewer_count", pd.Series([0])).min()),
            "group_holdout": validation,
        }

    if not rankers:
        raise ModelNotReady("학습 가능한 프로필 라벨이 없습니다.")
    candidate_status = (
        "unapproved_review_mixed_candidate"
        if candidate_tier == "review_mixed_candidate"
        else "unapproved_human_candidate"
    )
    metadata = {
        "model_tier": candidate_tier,
        "label_origin": label_origin,
        "model_version": (
            f"xgboost-{candidate_tier.replace('_', '-')}-"
            f"{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}"
        ),
        "trained_at": datetime.now(UTC).isoformat(),
        "feature_columns": FEATURE_COLS,
        "metrics": metrics,
        "minimum_reviewers": MIN_REVIEWERS,
        "candidate_status": candidate_status,
        "production_eligible": False,
        "training_lineage": training_lineage or {
            "source": "human_labeling_sheet",
            "reviewer_gate": MIN_REVIEWERS,
        },
        "promotion": {
            "auto_promoted": False,
            "manual_review_required": True,
            "direct_human_promotion_allowed": (
                candidate_tier == "human_candidate"
            ),
            "production_model_path": str(MODEL_PATH),
        },
    }
    write_ranker_artifact(output_path, metadata=metadata, rankers=rankers)
    return rankers


def load_rankers(path: Path = MODEL_PATH) -> dict:
    if not path.exists():
        raise ModelNotReady(
            "검증된 실제 라벨 모델이 없습니다. route_labels.csv와 route_features.jsonl을 완성한 뒤 학습하세요."
        )
    try:
        payload, profiles = read_ranker_artifact(path, load_models=True)
    except ArtifactError as exc:
        raise ModelNotReady(f"검증된 실제 라벨 모델 artifact가 올바르지 않습니다: {exc}") from exc
    if payload.get("feature_columns") != FEATURE_COLS:
        raise ModelNotReady("모델 피처 스키마가 현재 코드와 일치하지 않습니다. 재학습이 필요합니다.")
    if payload.get("model_tier") != "human_validated" or payload.get("label_origin") != "human_reviewers":
        raise ModelNotReady("운영 경로에는 실제 사용자 라벨로 검증된 모델만 사용할 수 있습니다.")
    if set(profiles) != set(PROFILES):
        raise ModelNotReady("운영 모델에는 6개 프로필 모델이 모두 필요합니다.")
    return profiles


def load_model_metadata(path: Path = MODEL_PATH) -> dict:
    """모델 객체를 제외한 버전·학습시각·검증 요약을 반환한다."""
    if not path.exists():
        raise ModelNotReady("검증된 실제 라벨 모델이 없습니다.")
    try:
        payload, _ = read_ranker_artifact(path, load_models=False)
    except ArtifactError as exc:
        raise ModelNotReady(f"검증된 실제 라벨 모델 artifact가 올바르지 않습니다: {exc}") from exc
    if payload.get("model_tier") != "human_validated":
        raise ModelNotReady("운영 모델은 관리자 승인된 human_validated tier여야 합니다.")
    return {
        "model_tier": payload.get("model_tier"),
        "label_origin": payload.get("label_origin"),
        "model_version": payload.get("model_version"),
        "trained_at": payload.get("trained_at"),
        "metrics": payload.get("metrics") or {},
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="실제 라벨 기반 XGBRanker 학습")
    parser.add_argument("--labels", type=Path, default=DEFAULT_LABELS)
    parser.add_argument("--features", type=Path, default=DEFAULT_FEATURES)
    parser.add_argument("--output", type=Path, default=HUMAN_CANDIDATE_PATH)
    args = parser.parse_args()
    data = load_human_training_data(args.labels, args.features)
    models = train_rankers(data, args.output)
    print(
        f"후보 학습 완료: {args.output} ({', '.join(models)}). "
        "관리자 검토·수동 승격 전에는 운영에 사용되지 않습니다."
    )


if __name__ == "__main__":
    main()
