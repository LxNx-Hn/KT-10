"""실제 라벨 학습 게이트와 XGBoost 추론 테스트."""
from __future__ import annotations

import json
from pathlib import Path
from zipfile import ZipFile

import pandas as pd
import pytest

from labeling.promote_human_candidate import promote
from scoring.artifacts import ArtifactError, file_sha256, read_ranker_artifact
from scoring.predict import predict_and_rank
from scoring.snapshots import (
    build_live_feature_snapshot,
    validate_live_feature_snapshot,
)
from scoring.train import (
    FEATURE_COLS,
    ModelNotReady,
    _group_holdout_metrics,
    _read_feature_snapshots,
    load_consented_review_training_data,
    load_human_training_data,
    train_rankers,
)


def _training_frame() -> pd.DataFrame:
    rows = []
    for profile in ["general", "elderly", "child", "youth", "disabled", "pregnant"]:
        for group in range(4):
            for route in range(3):
                features = {col: float((route + group) % 3) for col in FEATURE_COLS}
                if profile == "disabled":
                    features = {col: 0.5 for col in FEATURE_COLS}
                    features.update(stair_count=float(2 - route), elevator_ratio=float(route) / 2)
                    relevance = route
                else:
                    relevance = 2 - route
                rows.append({
                    "group_id": f"{profile}-{group}",
                    "holdout_group_id": f"{profile}-{group}",
                    "route_id": f"r-{route}",
                    "profile": profile,
                    "relevance": relevance,
                    **features,
                })
    return pd.DataFrame(rows)


@pytest.fixture(scope="module")
def rankers(tmp_path_factory):
    return train_rankers(
        _training_frame(),
        tmp_path_factory.mktemp("models") / "rankers.human-candidate.zip",
    )


def _snapshot(group_id: str, route_id: str) -> dict:
    return build_live_feature_snapshot(
        group_id=group_id,
        route_id=route_id,
        features={name: None for name in FEATURE_COLS},
        sources=["test-route-provider"],
        geometry_quality="exact",
        holdout_group_id=f"od-{group_id}",
        captured_at="2026-07-24T12:00:00+09:00",
    )


def _write_snapshots(path: Path, snapshots: list[dict]) -> None:
    path.write_text(
        "\n".join(json.dumps(row) for row in snapshots) + "\n",
        encoding="utf-8",
    )


def test_all_profiles_trained(rankers):
    assert set(rankers) == {"general", "elderly", "child", "youth", "disabled", "pregnant"}


def test_predict_top_k_probability_and_relative_fit_index(rankers):
    routes = [{col: 0.5 for col in FEATURE_COLS} for _ in range(3)]
    result = predict_and_rank(rankers, routes, "elderly", top_k=3)
    assert [item["rank"] for item in result] == [1, 2, 3]
    assert sum(item["probability"] for item in result) == pytest.approx(1.0, abs=0.01)
    assert all(0 <= item["relative_fit_score"] <= 1 for item in result)


def test_relative_fit_index_is_margin_normalization_not_probability():
    class FixedRanker:
        def predict(self, _frame):
            return [2.0, 0.0, 1.0]

    routes = [{col: 0.5 for col in FEATURE_COLS} for _ in range(3)]
    result = predict_and_rank({"general": FixedRanker()}, routes, "general", top_k=3)

    by_route = {item["route_index"]: item for item in result}
    assert by_route[0]["relative_fit_score"] == 1.0
    assert by_route[1]["relative_fit_score"] == 0.0
    assert by_route[2]["relative_fit_score"] == 0.5


def test_predict_rejects_non_finite_or_wrong_sized_model_output():
    routes = [{col: None for col in FEATURE_COLS} for _ in range(2)]

    class NonFiniteRanker:
        def predict(self, _frame):
            return [0.1, float("nan")]

    class WrongSizeRanker:
        def predict(self, _frame):
            return [0.1]

    with pytest.raises(ValueError, match="유한하지 않은"):
        predict_and_rank({"general": NonFiniteRanker()}, routes, "general")
    with pytest.raises(ValueError, match="개수"):
        predict_and_rank({"general": WrongSizeRanker()}, routes, "general")


def test_predict_preserves_input_order_for_equal_scores():
    class TiedRanker:
        def predict(self, _frame):
            return [1.0, 1.0, 1.0]

    routes = [{col: None for col in FEATURE_COLS} for _ in range(3)]

    result = predict_and_rank({"general": TiedRanker()}, routes, "general")

    assert [item["route_index"] for item in result] == [0, 1, 2]


def test_disabled_model_learns_labeled_preference(rankers):
    base = {col: 0.5 for col in FEATURE_COLS}
    routes = [
        {**base, "stair_count": 2.0, "elevator_ratio": 0.0},
        {**base, "stair_count": 0.0, "elevator_ratio": 1.0},
        {**base, "stair_count": 1.0, "elevator_ratio": 0.5},
    ]
    assert predict_and_rank(rankers, routes, "disabled", 3)[0]["route_index"] == 1


def test_human_loader_requires_nine_reviewers(tmp_path):
    snapshot = _snapshot("g1", "r1")
    labels = tmp_path / "labels.csv"
    labels.write_text(
        "reviewer_id,group_id,route_id,feature_snapshot_hash,profile,relevance\n"
        f"u1,g1,r1,{snapshot['feature_snapshot_hash']},general,4\n",
        encoding="utf-8",
    )
    features = tmp_path / "features.jsonl"
    _write_snapshots(features, [snapshot])
    with pytest.raises(ModelNotReady, match="최소 9명"):
        load_human_training_data(labels, features)


def test_human_loader_rejects_partially_labeled_route(tmp_path):
    snapshots = [_snapshot("g1", "r1"), _snapshot("g1", "r2")]
    hashes = {row["route_id"]: row["feature_snapshot_hash"] for row in snapshots}
    labels = tmp_path / "labels.csv"
    rows = [
        "reviewer_id,group_id,route_id,feature_snapshot_hash,profile,relevance"
    ]
    for profile in ("general", "elderly", "child", "youth", "disabled", "pregnant"):
        rows.extend(
            f"u{i},g1,r1,{hashes['r1']},{profile},4"
            for i in range(1, 10)
        )
        limit = 9 if profile == "pregnant" else 10
        rows.extend(
            f"u{i},g1,r2,{hashes['r2']},{profile},2"
            for i in range(1, limit)
        )
    labels.write_text("\n".join(rows) + "\n", encoding="utf-8")
    features = tmp_path / "features.jsonl"
    _write_snapshots(features, snapshots)
    with pytest.raises(ModelNotReady, match="모든 OD·경로·프로필"):
        load_human_training_data(labels, features)


def test_human_loader_rejects_stale_snapshot_hash(tmp_path):
    snapshot = _snapshot("g1", "r1")
    labels = tmp_path / "labels.csv"
    rows = [
        "reviewer_id,group_id,route_id,feature_snapshot_hash,profile,relevance"
    ]
    for profile in ("general", "elderly", "child", "youth", "disabled", "pregnant"):
        rows.extend(
            f"u{i},g1,r1,{'b' * 64},{profile},4"
            for i in range(1, 10)
        )
    labels.write_text("\n".join(rows) + "\n", encoding="utf-8")
    features = tmp_path / "features.jsonl"
    _write_snapshots(features, [snapshot])

    with pytest.raises(ValueError, match="해시"):
        load_human_training_data(labels, features)


def test_human_loader_rejects_duplicate_reviewer_label(tmp_path):
    snapshot = _snapshot("g1", "r1")
    labels = tmp_path / "labels.csv"
    rows = [
        "reviewer_id,group_id,route_id,feature_snapshot_hash,profile,relevance"
    ]
    for profile in ("general", "elderly", "child", "youth", "disabled", "pregnant"):
        rows.extend(
            f"u{i},g1,r1,{snapshot['feature_snapshot_hash']},{profile},4"
            for i in range(1, 10)
        )
    rows.append(rows[1])
    labels.write_text("\n".join(rows) + "\n", encoding="utf-8")
    features = tmp_path / "features.jsonl"
    _write_snapshots(features, [snapshot])

    with pytest.raises(ValueError, match="중복 라벨"):
        load_human_training_data(labels, features)


def test_review_loader_preserves_continuous_relevance_without_weakening_human_gate(
    tmp_path,
):
    snapshot = _snapshot("g1", "r1")
    labels = tmp_path / "labels.csv"
    rows = [
        "reviewer_id,group_id,route_id,feature_snapshot_hash,profile,relevance"
    ]
    rows.extend(
        f"u{i},g1,r1,{snapshot['feature_snapshot_hash']},general,1.125"
        for i in range(1, 10)
    )
    labels.write_text("\n".join(rows) + "\n", encoding="utf-8")
    features = tmp_path / "features.jsonl"
    _write_snapshots(features, [snapshot])

    with pytest.raises(ValueError, match="정수"):
        load_human_training_data(
            labels,
            features,
            require_reviewers_per_item=False,
        )

    loaded = load_consented_review_training_data(labels, features)
    assert loaded.loc[0, "relevance"] == pytest.approx(1.125)


def test_group_holdout_keeps_whole_od_groups_together():
    metrics = _group_holdout_metrics("general", _training_frame().query("profile == 'general'"))
    assert metrics["status"] == "evaluated"
    assert metrics["train_od_count"] + metrics["validation_od_count"] == 4
    assert 0 <= metrics["ndcg_at_3"] <= 1


def test_group_holdout_collapses_repeated_snapshots_of_same_od():
    base = _training_frame().query("profile == 'general'").copy()
    base["holdout_group_id"] = base["group_id"]
    repeated = base.copy()
    repeated["group_id"] = repeated["group_id"] + "-later-snapshot"
    frame = pd.concat([base, repeated], ignore_index=True)

    metrics = _group_holdout_metrics("general", frame)

    assert metrics["status"] == "evaluated"
    assert metrics["train_od_count"] + metrics["validation_od_count"] == 4
    assert (
        metrics["train_query_group_count"]
        + metrics["validation_query_group_count"]
        == 8
    )


def test_snapshot_requires_explicit_holdout_group_id():
    snapshot = _snapshot("g1", "r1")
    snapshot.pop("holdout_group_id")
    from scoring.snapshots import feature_snapshot_hash

    snapshot["feature_snapshot_hash"] = feature_snapshot_hash(snapshot)

    with pytest.raises(ValueError, match="holdout_group_id"):
        validate_live_feature_snapshot(snapshot, FEATURE_COLS)


def test_snapshot_v2_json_schema_requires_holdout_group_id():
    schema_path = (
        Path(__file__).resolve().parents[1]
        / "schemas"
        / "route_feature_snapshot.schema.json"
    )
    schema = json.loads(schema_path.read_text(encoding="utf-8"))

    assert schema["$id"] == "route-feature-snapshot-v2"
    assert "holdout_group_id" in schema["required"]


def test_snapshot_builder_rejects_blank_holdout_group_id():
    with pytest.raises(ValueError, match="holdout_group_id"):
        build_live_feature_snapshot(
            group_id="g1",
            holdout_group_id=" ",
            route_id="r1",
            features={name: None for name in FEATURE_COLS},
            sources=["odsay"],
            geometry_quality="exact",
            captured_at="2026-07-24T12:00:00+09:00",
        )


def test_snapshot_loader_rejects_one_group_mapped_to_multiple_holdout_groups(
    tmp_path,
):
    snapshots = [_snapshot("g1", "r1"), _snapshot("g1", "r2")]
    snapshots[1]["holdout_group_id"] = "different-physical-od"
    from scoring.snapshots import feature_snapshot_hash

    snapshots[1]["feature_snapshot_hash"] = feature_snapshot_hash(snapshots[1])
    path = tmp_path / "features.jsonl"
    _write_snapshots(path, snapshots)

    with pytest.raises(ValueError, match="정확히 하나"):
        _read_feature_snapshots(path)


def test_training_rejects_missing_holdout_group_id_instead_of_fallback(tmp_path):
    frame = _training_frame().drop(columns=["holdout_group_id"])

    with pytest.raises(ValueError, match="holdout_group_id"):
        train_rankers(frame, tmp_path / "rankers.human-candidate.zip")


def test_training_rejects_one_group_mapped_to_multiple_holdout_groups(tmp_path):
    frame = _training_frame()
    target = (
        (frame["profile"] == "general")
        & (frame["group_id"] == "general-0")
        & (frame["route_id"] == "r-1")
    )
    frame.loc[target, "holdout_group_id"] = "different-physical-od"

    with pytest.raises(ValueError, match="정확히 하나"):
        train_rankers(frame, tmp_path / "rankers.human-candidate.zip")


def test_human_training_requires_all_six_profiles(tmp_path):
    partial = _training_frame().query("profile != 'pregnant'")
    with pytest.raises(ModelNotReady, match="6개 프로필"):
        train_rankers(partial, tmp_path / "rankers.human-candidate.zip")


def test_human_training_requires_three_distinct_holdout_ods(tmp_path):
    frame = _training_frame()
    frame["holdout_group_id"] = "same-physical-od"

    with pytest.raises(ModelNotReady, match="실제 OD가 최소 3개"):
        train_rankers(
            frame,
            tmp_path / "rankers.human-candidate.zip",
        )


def test_model_loader_never_executes_pickle_payload(tmp_path):
    path = tmp_path / "untrusted.pkl"
    marker = tmp_path / "pickle-executed.txt"
    # A pickle GLOBAL/REDUCE payload would create this file if pickle.load ran.
    payload = (
        b"cos\nsystem\n(S'"
        + f'echo unsafe > "{marker}"'.encode()
        + b"'\ntR."
    )
    path.write_bytes(payload)
    from scoring.train import load_rankers

    with pytest.raises(ModelNotReady, match="artifact"):
        load_rankers(path)
    assert not marker.exists()


def test_ranker_artifact_rejects_duplicate_zip_paths(tmp_path):
    source = tmp_path / "source.zip"
    duplicated = tmp_path / "duplicated.zip"
    train_rankers(_training_frame(), source)
    with ZipFile(source, "r") as original, ZipFile(duplicated, "w") as target:
        for info in original.infolist():
            target.writestr(info, original.read(info.filename))
        with pytest.warns(UserWarning, match="Duplicate name"):
            target.writestr("manifest.json", original.read("manifest.json"))

    with pytest.raises(ArtifactError, match="중복"):
        read_ranker_artifact(duplicated, load_models=False)


def test_human_candidate_requires_manual_checksum_promotion(tmp_path):
    candidate = tmp_path / "rankers.human-candidate.zip"
    production = tmp_path / "rankers.human-validated.zip"
    train_rankers(_training_frame(), candidate)
    manifest, _ = read_ranker_artifact(candidate, load_models=False)
    assert manifest["model_tier"] == "human_candidate"

    from scoring.train import load_rankers

    with pytest.raises(ModelNotReady, match="실제 사용자 라벨"):
        load_rankers(candidate)
    report = promote(
        source=candidate,
        output=production,
        expected_source_sha256=file_sha256(candidate),
        approved_by="test-admin",
        approval_note="holdout and data lineage reviewed",
    )
    assert report["model_tier"] == "human_validated"
    assert set(load_rankers(production)) == {
        "general", "elderly", "child", "youth", "disabled", "pregnant",
    }


def test_review_mixed_artifact_self_identifies_as_unapproved(tmp_path):
    candidate = tmp_path / "rankers.review-mixed-candidate.zip"
    train_rankers(
        _training_frame(),
        candidate,
        label_origin="human_reviewers_and_consented_reviews",
        candidate_tier="review_mixed_candidate",
        training_lineage={"source": "test-review-mix"},
    )

    manifest, _ = read_ranker_artifact(candidate, load_models=False)
    assert manifest["model_tier"] == "review_mixed_candidate"
    assert manifest["candidate_status"] == "unapproved_review_mixed_candidate"
    assert manifest["production_eligible"] is False
    assert manifest["promotion"]["auto_promoted"] is False
    assert manifest["promotion"]["manual_review_required"] is True
    assert manifest["promotion"]["direct_human_promotion_allowed"] is False


@pytest.mark.parametrize(
    ("feature", "value", "message"),
    [
        ("walk_distance_m", -1.0, "0 이상"),
        ("shade_ratio", 1.1, "0~1"),
        ("transfer_count", 1.5, "정수"),
        ("is_low_floor_bus", 1, "boolean"),
        ("weather_rain", 2.0, "0, 1"),
    ],
)
def test_snapshot_rejects_semantically_invalid_model_features(
    feature,
    value,
    message,
):
    features = {name: None for name in FEATURE_COLS}
    features[feature] = value
    snapshot = build_live_feature_snapshot(
        group_id="g1",
        route_id="r1",
        features=features,
        sources=["odsay"],
        geometry_quality="exact",
        holdout_group_id="od-g1",
        captured_at="2026-07-24T12:00:00+09:00",
    )

    with pytest.raises(ValueError, match=message):
        validate_live_feature_snapshot(snapshot, FEATURE_COLS)


def test_snapshot_rejects_unknown_geometry_quality():
    snapshot = _snapshot("g1", "r1")
    snapshot["geometry_quality"] = "provider-specific-guess"
    from scoring.snapshots import feature_snapshot_hash

    snapshot["feature_snapshot_hash"] = feature_snapshot_hash(snapshot)

    with pytest.raises(ValueError, match="geometry_quality"):
        validate_live_feature_snapshot(snapshot, FEATURE_COLS)


def test_snapshot_builder_canonicalizes_duplicate_source_order():
    first = build_live_feature_snapshot(
        group_id="g1",
        route_id="r1",
        features={name: None for name in FEATURE_COLS},
        sources=["tmap", "odsay", "tmap"],
        geometry_quality="mixed",
        holdout_group_id="od-g1",
        captured_at="2026-07-24T12:00:00+09:00",
    )
    second = build_live_feature_snapshot(
        group_id="g1",
        route_id="r1",
        features={name: None for name in FEATURE_COLS},
        sources=["odsay", "tmap"],
        geometry_quality="mixed",
        holdout_group_id="od-g1",
        captured_at="2026-07-24T12:00:00+09:00",
    )

    assert first["sources"] == ["odsay", "tmap"]
    assert first["feature_snapshot_hash"] == second["feature_snapshot_hash"]
