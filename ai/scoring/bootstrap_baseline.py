"""초기 평가 라벨로 운영 모델과 분리된 baseline ranker를 학습한다.

이 모듈은 실제 사용자 라벨을 대체하지 않는다. 고정된 실제 후보 피처
스냅샷과 출처가 명시된 초기 평가 라벨만 받아 별도 모델 파일을 만든다.
"""
from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd

from scoring.artifacts import ArtifactError, read_ranker_artifact, write_ranker_artifact
from scoring.snapshots import validate_live_feature_snapshot
from scoring.train import (
    FEATURE_COLS,
    MODEL_PATH,
    MONOTONIC_CONSTRAINTS,
    PROFILES,
    RANKER_PARAMETERS,
    ModelNotReady,
    _group_holdout_metrics,
    _new_ranker,
    _validate_holdout_group_mapping,
    _validate_profile_frame,
)

EVALUATION_LABEL_SCHEMA_VERSION = "bootstrap-evaluation-label-v1"
BOOTSTRAP_MODEL_TIER = "bootstrap_baseline"
EVALUATION_LABEL_ORIGIN = "bootstrap_evaluation"
BOOTSTRAP_TRAINING_DIR = Path("ai/data/training/bootstrap_baseline")
DEFAULT_EVALUATION_LABELS = BOOTSTRAP_TRAINING_DIR / "evaluation_labels.jsonl"
DEFAULT_BOOTSTRAP_FEATURES = BOOTSTRAP_TRAINING_DIR / "route_features.jsonl"
BOOTSTRAP_MODEL_PATH = Path("ai/data/rankers.bootstrap-baseline.zip")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True)
class BootstrapTrainingBundle:
    frame: pd.DataFrame
    provenance: dict[str, Any]


def _read_jsonl(path: Path, description: str) -> list[dict[str, Any]]:
    if not path.exists():
        raise ModelNotReady(f"{description} 파일이 없습니다: {path}")
    rows: list[dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{description} {line_number}행 JSON이 올바르지 않습니다.") from exc
        if not isinstance(row, dict):
            raise ValueError(f"{description} {line_number}행은 JSON 객체여야 합니다.")
        rows.append(row)
    if not rows:
        raise ModelNotReady(f"{description}이 비어 있습니다.")
    return rows


def _validate_evaluation_label(row: dict[str, Any], line_number: int) -> None:
    required = {
        "schema_version",
        "label_kind",
        "evaluation_run_id",
        "evaluation_source",
        "rubric_version",
        "prompt_hash",
        "evaluated_at",
        "group_id",
        "route_id",
        "feature_snapshot_hash",
        "profile",
        "relevance",
        "rationale",
    }
    missing = required.difference(row)
    if missing:
        raise ValueError(
            f"초기 평가 라벨 {line_number}행 컬럼 누락: {', '.join(sorted(missing))}"
        )
    if row["schema_version"] != EVALUATION_LABEL_SCHEMA_VERSION:
        raise ValueError(
            f"초기 평가 라벨 {line_number}행 schema_version은 "
            f"{EVALUATION_LABEL_SCHEMA_VERSION}이어야 합니다."
        )
    if row["label_kind"] != EVALUATION_LABEL_ORIGIN:
        raise ValueError(
            f"초기 평가 라벨 {line_number}행 label_kind는 "
            f"{EVALUATION_LABEL_ORIGIN}이어야 합니다."
        )
    for field in (
        "evaluation_run_id",
        "evaluation_source",
        "rubric_version",
        "group_id",
        "route_id",
        "rationale",
    ):
        if not isinstance(row[field], str) or not row[field].strip():
            raise ValueError(
                f"초기 평가 라벨 {line_number}행 {field}가 비어 있습니다."
            )
    source_parts = row["evaluation_source"].split(":", 1)
    if (
        len(source_parts) != 2
        or not all(part.strip() for part in source_parts)
        or source_parts[0].casefold() in {"human", "user", "reviewer"}
    ):
        raise ValueError(
            f"초기 평가 라벨 {line_number}행 evaluation_source는 "
            "provider:evaluator 형식의 초기 평가 공급자 식별자여야 합니다."
        )
    if not _SHA256_RE.fullmatch(str(row["prompt_hash"])):
        raise ValueError(
            f"초기 평가 라벨 {line_number}행 prompt_hash는 SHA-256 hex여야 합니다."
        )
    if not _SHA256_RE.fullmatch(str(row["feature_snapshot_hash"])):
        raise ValueError(
            f"초기 평가 라벨 {line_number}행 feature_snapshot_hash는 "
            "SHA-256 hex여야 합니다."
        )
    try:
        evaluated_at = datetime.fromisoformat(str(row["evaluated_at"]).replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(
            f"초기 평가 라벨 {line_number}행 evaluated_at이 올바르지 않습니다."
        ) from exc
    if evaluated_at.tzinfo is None:
        raise ValueError(
            f"초기 평가 라벨 {line_number}행 evaluated_at에는 UTC 오프셋이 필요합니다."
        )
    if row["profile"] not in PROFILES:
        raise ValueError(f"지원하지 않는 프로필 라벨: {row['profile']}")
    if isinstance(row["relevance"], bool):
        raise ValueError(
            f"초기 평가 라벨 {line_number}행 relevance는 0~4 정수여야 합니다."
        )
    try:
        relevance = float(row["relevance"])
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"초기 평가 라벨 {line_number}행 relevance는 0~4 정수여야 합니다."
        ) from exc
    if relevance not in {0.0, 1.0, 2.0, 3.0, 4.0}:
        raise ValueError(
            f"초기 평가 라벨 {line_number}행 relevance는 0~4 정수여야 합니다."
        )


def _provenance(labels: pd.DataFrame) -> dict[str, Any]:
    runs = []
    for evaluation_run_id, group in labels.groupby("evaluation_run_id", sort=True):
        runs.append({
            "evaluation_run_id": str(evaluation_run_id),
            "evaluation_source": str(group["evaluation_source"].iloc[0]),
            "rubric_version": str(group["rubric_version"].iloc[0]),
            "prompt_hash": str(group["prompt_hash"].iloc[0]),
            "evaluated_from": str(group["evaluated_at"].min()),
            "evaluated_to": str(group["evaluated_at"].max()),
            "label_count": int(len(group)),
        })
    return {
        "label_origin": EVALUATION_LABEL_ORIGIN,
        "evaluation_run_count": len(runs),
        "evaluation_sources": sorted(
            labels["evaluation_source"].unique().tolist()
        ),
        "rubric_versions": sorted(labels["rubric_version"].unique().tolist()),
        "prompt_hashes": sorted(labels["prompt_hash"].unique().tolist()),
        "runs": runs,
    }


def load_bootstrap_training_data(
    labels_path: Path = DEFAULT_EVALUATION_LABELS,
    features_path: Path = DEFAULT_BOOTSTRAP_FEATURES,
) -> BootstrapTrainingBundle:
    """완전한 초기 평가 행렬과 해시가 일치하는 실제 후보 스냅샷을 결합한다."""
    snapshot_rows = _read_jsonl(features_path, "경로 피처 스냅샷")
    seen_routes: set[tuple[str, str]] = set()
    flat_snapshots: list[dict[str, Any]] = []
    for line_number, snapshot in enumerate(snapshot_rows, start=1):
        try:
            validate_live_feature_snapshot(snapshot, FEATURE_COLS)
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"경로 피처 스냅샷 {line_number}행: {exc}") from exc
        route_key = (str(snapshot["group_id"]), str(snapshot["route_id"]))
        if route_key in seen_routes:
            raise ValueError(
                f"중복 경로 피처 스냅샷: {route_key[0]}/{route_key[1]}"
            )
        seen_routes.add(route_key)
        flat_snapshots.append({
            "group_id": route_key[0],
            "holdout_group_id": str(snapshot["holdout_group_id"]),
            "route_id": route_key[1],
            "feature_snapshot_hash": str(snapshot["feature_snapshot_hash"]),
            "snapshot_captured_at": str(snapshot["captured_at"]),
            **{name: snapshot["features"][name] for name in FEATURE_COLS},
        })
    snapshots = pd.DataFrame(flat_snapshots)
    _validate_holdout_group_mapping(snapshots)

    label_rows = _read_jsonl(labels_path, "초기 평가 라벨")
    for line_number, row in enumerate(label_rows, start=1):
        _validate_evaluation_label(row, line_number)
    labels = pd.DataFrame(label_rows)
    labels["group_id"] = labels["group_id"].astype(str)
    labels["route_id"] = labels["route_id"].astype(str)
    labels["relevance"] = labels["relevance"].astype(int)
    labels["evaluated_at"] = pd.to_datetime(labels["evaluated_at"], utc=True)

    duplicate_keys = ["evaluation_run_id", "group_id", "route_id", "profile"]
    duplicates = labels.duplicated(duplicate_keys, keep=False)
    if duplicates.any():
        sample = labels.loc[duplicates, duplicate_keys].iloc[0]
        raise ValueError(
            "동일 평가 실행의 중복 라벨: "
            f"{sample['evaluation_run_id']}/{sample['group_id']}/"
            f"{sample['route_id']}/{sample['profile']}"
        )

    for evaluation_run_id, group in labels.groupby(
        "evaluation_run_id",
        sort=False,
    ):
        for field in ("evaluation_source", "rubric_version", "prompt_hash"):
            if group[field].nunique() != 1:
                raise ValueError(
                    f"{evaluation_run_id}: 한 실행에서 {field}는 동일해야 합니다."
                )
        actual = set(zip(group["group_id"], group["route_id"], group["profile"]))
        expected = {
            (group_id, route_id, profile)
            for group_id, route_id in seen_routes
            for profile in PROFILES
        }
        missing = expected - actual
        extra = actual - expected
        if missing or extra:
            raise ModelNotReady(
                f"{evaluation_run_id}: 모든 실제 후보와 6개 프로필을 "
                "평가해야 합니다. "
                f"누락 {len(missing)}건, 알 수 없는 후보 {len(extra)}건"
            )

    merged = labels.merge(
        snapshots,
        on=["group_id", "route_id"],
        how="left",
        validate="many_to_one",
        suffixes=("_label", "_snapshot"),
        indicator=True,
    )
    if (merged["_merge"] != "both").any():
        raise ValueError("초기 평가 라벨에 스냅샷이 없는 경로가 있습니다.")
    stale = (
        merged["feature_snapshot_hash_label"]
        != merged["feature_snapshot_hash_snapshot"]
    )
    if stale.any():
        row = merged.loc[stale].iloc[0]
        raise ValueError(
            "초기 평가 라벨이 현재 피처 스냅샷과 일치하지 않습니다: "
            f"{row['group_id']}/{row['route_id']}"
        )
    captured_at = pd.to_datetime(merged["snapshot_captured_at"], utc=True)
    evaluated_before_capture = merged["evaluated_at"] < captured_at
    if evaluated_before_capture.any():
        row = merged.loc[evaluated_before_capture].iloc[0]
        raise ValueError(
            "초기 평가는 피처 스냅샷 생성 이후여야 합니다: "
            f"{row['group_id']}/{row['route_id']}"
        )

    aggregated = (
        merged.groupby(["group_id", "route_id", "profile"], as_index=False)
        .agg(
            relevance=("relevance", "median"),
            evaluation_count=("evaluation_run_id", "nunique"),
            holdout_group_id=("holdout_group_id", "first"),
            **{name: (name, "first") for name in FEATURE_COLS},
        )
        .sort_values(["profile", "group_id", "route_id"])
        .reset_index(drop=True)
    )
    missing_profiles = sorted(set(PROFILES) - set(aggregated["profile"]))
    if missing_profiles:
        raise ModelNotReady(
            "초기 평가 baseline에는 6개 프로필이 모두 필요합니다: "
            + ", ".join(missing_profiles)
        )
    return BootstrapTrainingBundle(
        frame=aggregated,
        provenance=_provenance(labels),
    )


def _metadata_path(model_path: Path) -> Path:
    return model_path.with_suffix(".metadata.json")


def train_bootstrap_baseline(
    bundle: BootstrapTrainingBundle | None = None,
    output_path: Path = BOOTSTRAP_MODEL_PATH,
    *,
    labels_path: Path = DEFAULT_EVALUATION_LABELS,
    features_path: Path = DEFAULT_BOOTSTRAP_FEATURES,
) -> dict[str, Any]:
    """초기 평가 baseline을 학습하며 운영 모델은 변경하지 않는다."""
    data = bundle or load_bootstrap_training_data(labels_path, features_path)
    frame = data.frame.copy()
    missing = {"group_id", "profile", "relevance", *FEATURE_COLS}.difference(frame.columns)
    if missing:
        raise ValueError(f"학습 데이터 컬럼 누락: {', '.join(sorted(missing))}")

    rankers: dict[str, Any] = {}
    metrics: dict[str, dict[str, Any]] = {}
    for profile in PROFILES:
        profile_df = (
            frame[frame["profile"] == profile]
            .sort_values("group_id")
            .reset_index(drop=True)
        )
        if profile_df["holdout_group_id"].nunique() < 3:
            raise ModelNotReady(
                f"{profile}: 초기 평가 baseline의 OD-group holdout에는 "
                "서로 다른 OD가 최소 3개 필요합니다."
            )
        _validate_profile_frame(profile, profile_df)
        validation = _group_holdout_metrics(profile, profile_df)
        if validation.get("status") != "evaluated":
            raise ModelNotReady(f"{profile}: OD-group holdout을 계산하지 못했습니다.")
        model = _new_ranker()
        model.fit(
            profile_df[FEATURE_COLS].apply(pd.to_numeric, errors="coerce"),
            profile_df["relevance"].astype(float),
            group=profile_df.groupby("group_id", sort=False).size().to_numpy(),
            verbose=False,
        )
        rankers[profile] = model
        metrics[profile] = {
            "route_count": int(len(profile_df)),
            "od_count": int(profile_df["holdout_group_id"].nunique()),
            "query_group_count": int(profile_df["group_id"].nunique()),
            "evaluation_count_min": int(
                profile_df["evaluation_count"].min()
            ),
            "group_holdout": validation,
        }

    trained_at = datetime.now(UTC).isoformat()
    metadata = {
        "model_tier": BOOTSTRAP_MODEL_TIER,
        "label_origin": EVALUATION_LABEL_ORIGIN,
        "model_version": (
            "xgboost-bootstrap-baseline-"
            + datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        ),
        "trained_at": trained_at,
        "feature_columns": FEATURE_COLS,
        "monotonic_constraints": MONOTONIC_CONSTRAINTS,
        "ranker_parameters": RANKER_PARAMETERS,
        "metrics": metrics,
        "training_provenance": data.provenance,
        "promotion": {
            "auto_promoted": False,
            "production_model_path": str(MODEL_PATH),
        },
    }
    manifest = write_ranker_artifact(
        output_path,
        metadata=metadata,
        rankers=rankers,
    )
    _metadata_path(output_path).write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return rankers


def _load_payload(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise ModelNotReady(f"초기 평가 baseline 모델이 없습니다: {path}")
    try:
        payload, profiles = read_ranker_artifact(path, load_models=True)
    except ArtifactError as exc:
        raise ModelNotReady(
            f"초기 평가 baseline artifact가 올바르지 않습니다: {exc}"
        ) from exc
    if payload.get("model_tier") != BOOTSTRAP_MODEL_TIER:
        raise ModelNotReady("모델이 bootstrap_baseline tier가 아닙니다.")
    if payload.get("label_origin") != EVALUATION_LABEL_ORIGIN:
        raise ModelNotReady("모델의 라벨 출처가 bootstrap_evaluation이 아닙니다.")
    if payload.get("feature_columns") != FEATURE_COLS:
        raise ModelNotReady(
            "초기 평가 baseline 피처 스키마가 현재 코드와 일치하지 않습니다."
        )
    if payload.get("monotonic_constraints") != MONOTONIC_CONSTRAINTS:
        raise ModelNotReady(
            "초기 평가 baseline의 환승 단조 제약이 현재 코드와 일치하지 않습니다."
        )
    if set(profiles) != set(PROFILES):
        raise ModelNotReady(
            "초기 평가 baseline에 6개 프로필 모델이 모두 필요합니다."
        )
    return {**payload, "profiles": profiles}


def load_bootstrap_baseline_rankers(
    path: Path = BOOTSTRAP_MODEL_PATH,
) -> dict[str, Any]:
    """명시적으로 요청한 경우에만 초기 평가 baseline ranker를 반환한다."""
    return _load_payload(path)["profiles"]


def load_bootstrap_baseline_metadata(
    path: Path = BOOTSTRAP_MODEL_PATH,
) -> dict[str, Any]:
    """모델 객체를 제외한 초기 평가 provenance와 검증 결과를 반환한다."""
    payload = _load_payload(path)
    return {key: value for key, value in payload.items() if key != "profiles"}


def main() -> None:
    parser = argparse.ArgumentParser(
        description="초기 평가 라벨 기반 비운영 baseline XGBRanker 학습"
    )
    parser.add_argument("--labels", type=Path, default=DEFAULT_EVALUATION_LABELS)
    parser.add_argument("--features", type=Path, default=DEFAULT_BOOTSTRAP_FEATURES)
    parser.add_argument("--output", type=Path, default=BOOTSTRAP_MODEL_PATH)
    args = parser.parse_args()
    bundle = load_bootstrap_training_data(args.labels, args.features)
    models = train_bootstrap_baseline(bundle, args.output)
    print(
        f"초기 평가 baseline 학습 완료: {args.output} ({', '.join(models)}). "
        f"운영 모델 {MODEL_PATH}은 변경하지 않았습니다."
    )


if __name__ == "__main__":
    main()
