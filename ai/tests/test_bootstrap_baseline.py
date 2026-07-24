"""실제 사용자 모델과 분리된 초기 평가 baseline 계약 테스트."""
from __future__ import annotations

import json

import pytest

from labeling.prepare_bootstrap_baseline import prepare
from scoring.bootstrap_baseline import (
    BOOTSTRAP_MODEL_TIER,
    EVALUATION_LABEL_ORIGIN,
    EVALUATION_LABEL_SCHEMA_VERSION,
    BootstrapTrainingBundle,
    load_bootstrap_baseline_metadata,
    load_bootstrap_baseline_rankers,
    load_bootstrap_training_data,
    train_bootstrap_baseline,
)
from scoring.snapshots import build_live_feature_snapshot
from scoring.train import FEATURE_COLS, PROFILES, ModelNotReady, load_rankers


def _snapshot_rows() -> list[dict]:
    rows = []
    for group_index in range(3):
        for route_index in range(2):
            features = {name: 0.0 for name in FEATURE_COLS}
            features.update({
                "total_duration_min": 20.0 + route_index,
                "walk_distance_m": 1000.0 + route_index * 200,
                "shade_ratio": 0.2 + route_index * 0.4,
                "shaded_walk_m": 200.0 + route_index * 520,
                "shade_building_height_coverage": 0.8,
                "is_low_floor_bus": route_index == 0,
            })
            rows.append(build_live_feature_snapshot(
                group_id=f"g{group_index}",
                route_id=f"r{route_index}",
                features=features,
                sources=["odsay"],
                geometry_quality="mixed",
                holdout_group_id=f"od-g{group_index}",
                captured_at="2026-07-24T12:00:00+09:00",
            ))
    return rows


def _label_rows(
    snapshots: list[dict],
    *,
    run_id: str = "evaluation-a",
) -> list[dict]:
    rows = []
    for snapshot in snapshots:
        route_index = int(snapshot["route_id"][1:])
        for profile in PROFILES:
            rows.append({
                "schema_version": EVALUATION_LABEL_SCHEMA_VERSION,
                "label_kind": EVALUATION_LABEL_ORIGIN,
                "evaluation_run_id": run_id,
                "evaluation_source": "test:evaluator",
                "rubric_version": "route-profile-rubric-v1",
                "prompt_hash": "a" * 64,
                "evaluated_at": "2026-07-24T12:30:00+09:00",
                "group_id": snapshot["group_id"],
                "route_id": snapshot["route_id"],
                "feature_snapshot_hash": snapshot["feature_snapshot_hash"],
                "profile": profile,
                "relevance": 4 if route_index == 0 else 1,
                "rationale": "고정된 테스트 피처에 근거한 평가",
            })
    return rows


def _write_jsonl(path, rows: list[dict]) -> None:
    path.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n",
        encoding="utf-8",
    )


def _bundle_files(tmp_path):
    snapshots = _snapshot_rows()
    features_path = tmp_path / "route_features.jsonl"
    labels_path = tmp_path / "evaluation_labels.jsonl"
    _write_jsonl(features_path, snapshots)
    _write_jsonl(labels_path, _label_rows(snapshots))
    return snapshots, features_path, labels_path


def test_bootstrap_loader_requires_complete_six_profile_matrix(tmp_path):
    snapshots, features_path, labels_path = _bundle_files(tmp_path)
    incomplete = _label_rows(snapshots)[:-1]
    _write_jsonl(labels_path, incomplete)

    with pytest.raises(ModelNotReady, match="6개 프로필"):
        load_bootstrap_training_data(labels_path, features_path)


def test_bootstrap_loader_rejects_stale_snapshot_hash(tmp_path):
    snapshots, features_path, labels_path = _bundle_files(tmp_path)
    labels = _label_rows(snapshots)
    labels[0]["feature_snapshot_hash"] = "b" * 64
    _write_jsonl(labels_path, labels)

    with pytest.raises(ValueError, match="현재 피처 스냅샷과 일치하지 않습니다"):
        load_bootstrap_training_data(labels_path, features_path)


def test_bootstrap_loader_rejects_invalid_prompt_hash(tmp_path):
    snapshots, features_path, labels_path = _bundle_files(tmp_path)
    labels = _label_rows(snapshots)
    labels[0]["prompt_hash"] = "not-a-hash"
    _write_jsonl(labels_path, labels)

    with pytest.raises(ValueError, match="prompt_hash"):
        load_bootstrap_training_data(labels_path, features_path)


def test_bootstrap_loader_rejects_human_source(tmp_path):
    snapshots, features_path, labels_path = _bundle_files(tmp_path)
    labels = _label_rows(snapshots)
    labels[0]["evaluation_source"] = "human:reviewer-1"
    _write_jsonl(labels_path, labels)

    with pytest.raises(ValueError, match="초기 평가 공급자"):
        load_bootstrap_training_data(labels_path, features_path)


def test_bootstrap_loader_rejects_evaluation_before_snapshot(tmp_path):
    snapshots, features_path, labels_path = _bundle_files(tmp_path)
    labels = _label_rows(snapshots)
    for label in labels:
        label["evaluated_at"] = "2026-07-24T11:59:59+09:00"
    _write_jsonl(labels_path, labels)

    with pytest.raises(ValueError, match="스냅샷 생성 이후"):
        load_bootstrap_training_data(labels_path, features_path)


def test_prepare_bootstrap_sheet_binds_prompt_and_snapshots(tmp_path):
    snapshots = _snapshot_rows()
    features_path = tmp_path / "route_features.jsonl"
    output_path = tmp_path / "evaluation_labels.jsonl"
    prompt_path = tmp_path / "evaluation_rubric.txt"
    _write_jsonl(features_path, snapshots)
    prompt_path.write_text("고정 피처만 평가한다.", encoding="utf-8")

    report = prepare(
        features_path=features_path,
        output_path=output_path,
        evaluation_run_id="evaluation-a",
        evaluation_source="test:evaluator",
        rubric_version="route-profile-rubric-v1",
        prompt_path=prompt_path,
    )
    rows = [
        json.loads(line)
        for line in output_path.read_text(encoding="utf-8").splitlines()
    ]

    assert report["label_row_count"] == len(snapshots) * len(PROFILES)
    assert report["ready_for_training"] is False
    assert rows[0]["feature_snapshot_hash"] == snapshots[0]["feature_snapshot_hash"]
    assert rows[0]["prompt_hash"] == report["prompt_hash"]
    assert rows[0]["evaluated_at"] is None
    assert rows[0]["relevance"] is None


def test_bootstrap_loader_preserves_provenance_and_nulls(tmp_path):
    snapshots, features_path, labels_path = _bundle_files(tmp_path)
    snapshots[0]["features"]["shade_ratio"] = None
    snapshots[0]["feature_snapshot_hash"] = build_live_feature_snapshot(
        group_id=snapshots[0]["group_id"],
        route_id=snapshots[0]["route_id"],
        features=snapshots[0]["features"],
        sources=snapshots[0]["sources"],
        geometry_quality=snapshots[0]["geometry_quality"],
        holdout_group_id=snapshots[0]["holdout_group_id"],
        captured_at=snapshots[0]["captured_at"],
    )["feature_snapshot_hash"]
    _write_jsonl(features_path, snapshots)
    _write_jsonl(labels_path, _label_rows(snapshots))

    bundle = load_bootstrap_training_data(labels_path, features_path)

    assert set(bundle.frame["profile"]) == set(PROFILES)
    assert bundle.frame["shade_ratio"].isna().any()
    assert bundle.provenance["label_origin"] == EVALUATION_LABEL_ORIGIN
    assert bundle.provenance["evaluation_sources"] == ["test:evaluator"]


def test_bootstrap_model_is_separate_and_cannot_load_as_human(tmp_path):
    _, features_path, labels_path = _bundle_files(tmp_path)
    bundle = load_bootstrap_training_data(labels_path, features_path)
    output_path = tmp_path / "rankers.bootstrap-baseline.zip"

    rankers = train_bootstrap_baseline(
        BootstrapTrainingBundle(bundle.frame, bundle.provenance),
        output_path,
    )
    metadata = load_bootstrap_baseline_metadata(output_path)

    assert set(rankers) == set(PROFILES)
    assert set(load_bootstrap_baseline_rankers(output_path)) == set(PROFILES)
    assert metadata["model_tier"] == BOOTSTRAP_MODEL_TIER
    assert metadata["label_origin"] == EVALUATION_LABEL_ORIGIN
    assert metadata["promotion"]["auto_promoted"] is False
    assert output_path.with_suffix(".metadata.json").exists()
    with pytest.raises(ModelNotReady, match="실제 사용자 라벨"):
        load_rankers(output_path)
