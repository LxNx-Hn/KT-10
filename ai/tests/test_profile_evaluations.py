"""프로필 평가 라벨 생성 계약 테스트."""
from __future__ import annotations

import json

import pytest

from labeling.generate_profile_evaluations import (
    DEFAULT_RUBRIC_PATH,
    generate,
)
from scoring.snapshots import build_live_feature_snapshot, feature_snapshot_hash
from scoring.train import FEATURE_COLS, PROFILES


def _features(**updates):
    values = {feature: None for feature in FEATURE_COLS}
    values.update({
        "transfer_count": 0,
        "walk_distance_m": 500.0,
        "total_duration_min": 20.0,
        "shade_ratio": 0.2,
        "shaded_walk_m": 100.0,
        "shade_building_height_coverage": 0.8,
        "weather_heatwave": 0.0,
        "weather_coldwave": 0.0,
        "weather_rain": 0.0,
        "weather_bad_air": 0.0,
    })
    values.update(updates)
    return values


def _snapshot(group_id, route_id, features):
    return build_live_feature_snapshot(
        group_id=group_id,
        holdout_group_id=f"od-{group_id}",
        route_id=route_id,
        features=features,
        sources=["route-provider"],
        geometry_quality="exact",
        captured_at="2026-07-24T12:00:00+09:00",
    )


def _write_jsonl(path, rows):
    path.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n",
        encoding="utf-8",
    )


def _generate(tmp_path, rows):
    features = tmp_path / "features.jsonl"
    labels = tmp_path / "labels.jsonl"
    report = tmp_path / "report.json"
    frozen = tmp_path / "frozen.jsonl"
    _write_jsonl(features, rows)
    result = generate(
        features_path=features,
        labels_output_path=labels,
        report_output_path=report,
        frozen_features_output_path=frozen,
        rubric_path=DEFAULT_RUBRIC_PATH,
        evaluation_run_id="evaluation-test",
        evaluation_source="test:profile-rubric",
    )
    return result, labels, report, frozen


def test_generates_complete_six_profile_matrix_and_provenance(tmp_path):
    rows = [
        _snapshot(
            "g1",
            "fast",
            _features(total_duration_min=10.0, walk_distance_m=200.0),
        ),
        _snapshot(
            "g1",
            "slow",
            _features(total_duration_min=30.0, walk_distance_m=800.0),
        ),
    ]

    report, labels_path, report_path, frozen = _generate(tmp_path, rows)
    labels = [
        json.loads(line)
        for line in labels_path.read_text(encoding="utf-8").splitlines()
    ]

    assert report["od_count"] == 1
    assert report["route_count"] == 2
    assert report["label_count"] == 2 * len(PROFILES)
    assert set(row["profile"] for row in labels) == set(PROFILES)
    assert all(1 <= row["relevance"] <= 4 for row in labels)
    assert all(row["prompt_hash"] == report["rubric_sha256"] for row in labels)
    assert frozen.read_bytes() != b""
    assert json.loads(report_path.read_text(encoding="utf-8")) == report


def test_missing_value_is_not_replaced_with_zero_or_hard_rejected(tmp_path):
    rows = [
        _snapshot(
            "g1",
            "unknown-slope",
            _features(
                avg_slope_percent=None,
                max_slope_percent=None,
                min_slope_percent=None,
            ),
        ),
        _snapshot(
            "g1",
            "known-slope",
            _features(
                avg_slope_percent=3.0,
                max_slope_percent=5.0,
                min_slope_percent=-4.0,
            ),
        ),
    ]

    _, labels_path, _, _ = _generate(tmp_path, rows)
    labels = [
        json.loads(line)
        for line in labels_path.read_text(encoding="utf-8").splitlines()
    ]

    assert all(row["relevance"] != 0 for row in labels)
    assert all(
        "미확인 값은 평가에서 제외" in row["rationale"]
        for row in labels
    )


def test_dongbaekjeon_is_explicitly_excluded_from_evaluation(tmp_path):
    rows = [
        _snapshot("g1", "few", _features()),
        _snapshot("g1", "many", _features()),
    ]
    for index, row in enumerate(rows):
        row["features"]["dongbaekjeon_store_count_200m"] = 1 + index * 999
        row["feature_snapshot_hash"] = feature_snapshot_hash(row)

    report, labels_path, _, _ = _generate(tmp_path, rows)
    labels = [
        json.loads(line)
        for line in labels_path.read_text(encoding="utf-8").splitlines()
    ]

    assert report["auxiliary_features_excluded"] == [
        "dongbaekjeon_store_count_200m"
    ]
    by_profile = {}
    for row in labels:
        by_profile.setdefault(row["profile"], []).append(row["relevance"])
    assert all(len(set(values)) == 1 for values in by_profile.values())


def test_rejects_human_source_identity(tmp_path):
    features = tmp_path / "features.jsonl"
    _write_jsonl(
        features,
        [
            _snapshot("g1", "a", _features()),
            _snapshot("g1", "b", _features(total_duration_min=30.0)),
        ],
    )

    with pytest.raises(ValueError, match="provider:evaluator"):
        generate(
            features_path=features,
            labels_output_path=tmp_path / "labels.jsonl",
            report_output_path=tmp_path / "report.json",
            frozen_features_output_path=None,
            rubric_path=DEFAULT_RUBRIC_PATH,
            evaluation_run_id="evaluation-test",
            evaluation_source="human:reviewer",
        )
