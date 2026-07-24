from __future__ import annotations

import csv
import json

import pytest

from labeling.collect_training_candidates import (
    CandidateCollectionError,
    _validate_candidate_payload,
    collect,
)
from scoring.snapshots import build_live_feature_snapshot
from scoring.train import FEATURE_COLS


def _write_od_catalog(path) -> None:
    rows = [
        {
            "od_id": f"od-{index}",
            "origin_name": f"출발 {index}",
            "origin_lat": 35.10 + index * 0.01,
            "origin_lng": 129.01,
            "dest_name": f"도착 {index}",
            "dest_lat": 35.15 + index * 0.01,
            "dest_lng": 129.05,
            "weather": "normal",
            "departure_at": "2026-08-03T12:00:00+09:00",
            "carry_luggage": "false",
            "stroller": "false",
            "shade_priority": "false",
            "minimize_transfers": "false",
            "avoid_stairs": "false",
            "low_floor_priority": "false",
        }
        for index in range(2)
    ]
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def _candidate_record(row):
    group_id = f"group-{row['od_id']}"
    candidates = []
    for index in range(2):
        features = {name: None for name in FEATURE_COLS}
        features["total_duration_min"] = 20.0 + index
        features["avg_slope_percent"] = 2.0 + index
        features["max_slope_percent"] = 4.0 + index
        features["min_slope_percent"] = -1.0 - index
        features["shade_ratio"] = 0.2 + index * 0.1
        features["shaded_walk_m"] = 200.0 + index * 10
        snapshot = build_live_feature_snapshot(
            group_id=group_id,
            route_id=f"route-{row['od_id']}-{index}",
            features=features,
            sources=["odsay"],
            geometry_quality="exact",
            holdout_group_id=f"holdout-{row['od_id']}",
            captured_at="2026-07-25T00:00:00+00:00",
            shade_evaluated_at="2026-07-25T01:00:00+00:00",
        )
        candidates.append({
            "route_id": snapshot["route_id"],
            "summary": f"후보 {index}",
            "duration_min": 20 + index,
            "distance_m": 1000 + index,
            "sources": ["odsay"],
            "geometry_quality": "exact",
            "segments": [{
                "mode": "walk",
                "distance_m": 1000 + index,
                "geometry_quality": "exact",
                "path": [
                    {"lat": 35.1, "lng": 129.0},
                    {"lat": 35.2, "lng": 129.1},
                ],
            }],
            "segment_geometry": [{
                "mode": "walk",
                "distance_m": 1000 + index,
                "geometry_quality": "exact",
            }],
            "trait_labels": {"labels": []},
            "feature_snapshot": snapshot,
        })
    return {
        "schema_version": "training-candidate-collection-v1",
        "od_id": row["od_id"],
        "request_fingerprint": "",
        "collected_at": "2026-07-25T02:00:00+00:00",
        "request_context": {},
        "group_id": group_id,
        "holdout_group_id": f"holdout-{row['od_id']}",
        "candidates": candidates,
    }


def test_collection_checkpoints_and_resume_without_refetch(tmp_path):
    od_path = tmp_path / "od.csv"
    output_dir = tmp_path / "collection"
    _write_od_catalog(od_path)
    calls = []

    def fake_fetcher(**kwargs):
        from labeling.collect_training_candidates import _request_fingerprint

        row = kwargs["row"]
        calls.append(row["od_id"])
        record = _candidate_record(row)
        record["request_fingerprint"] = _request_fingerprint(row)
        record["request_context"] = {
            key: str(row.get(key) or "").strip()
            for key in (
                "od_id",
                "origin_name",
                "origin_lat",
                "origin_lng",
                "dest_name",
                "dest_lat",
                "dest_lng",
                "weather",
                "departure_at",
                "carry_luggage",
                "stroller",
                "shade_priority",
                "minimize_transfers",
                "avoid_stairs",
                "low_floor_priority",
            )
        }
        return record

    first = collect(
        od_path=od_path,
        output_dir=output_dir,
        server_url="http://unused",
        api_token="x" * 32,
        workers=2,
        fetcher=fake_fetcher,
    )
    second = collect(
        od_path=od_path,
        output_dir=output_dir,
        server_url="http://unused",
        api_token="x" * 32,
        workers=2,
        fetcher=fake_fetcher,
    )

    assert sorted(calls) == ["od-0", "od-1"]
    assert first["completed_od_count"] == 2
    assert first["candidate_count"] == 4
    assert first["ready_for_evaluation"] is True
    assert second["remaining_od_count"] == 0
    features = [
        json.loads(line)
        for line in (output_dir / "route_features.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    assert len(features) == 4
    assert len({row["feature_snapshot_hash"] for row in features}) == 4
    contexts = [
        json.loads(line)
        for line in (output_dir / "candidate_context.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    assert contexts[0]["segment_geometry"] == [{
        "mode": "walk",
        "distance_m": 1000,
        "geometry_quality": "exact",
    }]


def test_collection_failure_is_not_marked_ready(tmp_path):
    od_path = tmp_path / "od.csv"
    output_dir = tmp_path / "collection"
    _write_od_catalog(od_path)

    def failing_fetcher(**kwargs):
        raise RuntimeError("provider unavailable")

    report = collect(
        od_path=od_path,
        output_dir=output_dir,
        server_url="http://unused",
        api_token="x" * 32,
        workers=1,
        fetcher=failing_fetcher,
    )

    assert report["completed_od_count"] == 0
    assert report["remaining_od_count"] == 2
    assert report["ready_for_evaluation"] is False
    failures = (output_dir / "failures.jsonl").read_text(encoding="utf-8")
    assert failures.count("provider unavailable") == 2


def test_collection_rejects_catalog_over_provider_budget(tmp_path):
    od_path = tmp_path / "od.csv"
    _write_od_catalog(od_path)

    with pytest.raises(ValueError, match="공급자 호출 예산"):
        collect(
            od_path=od_path,
            output_dir=tmp_path / "collection",
            server_url="http://unused",
            api_token="x" * 32,
            provider_unique_od_budget=1,
        )


def test_candidate_quality_gate_does_not_replace_unknown_with_zero():
    row = {
        "od_id": "od-quality",
        "origin_name": "출발",
        "origin_lat": "35.1",
        "origin_lng": "129.0",
        "dest_name": "도착",
        "dest_lat": "35.2",
        "dest_lng": "129.1",
    }
    record = _candidate_record(row)
    for candidate in record["candidates"]:
        features = candidate["feature_snapshot"]["features"]
        for name in (
            "avg_slope_percent",
            "max_slope_percent",
            "min_slope_percent",
            "shade_ratio",
            "shaded_walk_m",
        ):
            features[name] = None
        candidate["feature_snapshot"] = build_live_feature_snapshot(
            group_id=record["group_id"],
            route_id=candidate["route_id"],
            features=features,
            sources=["odsay"],
            geometry_quality="mixed",
            holdout_group_id=record["holdout_group_id"],
            captured_at="2026-07-25T00:00:00+00:00",
            shade_evaluated_at="2026-07-25T01:00:00+00:00",
        )

    with pytest.raises(
        CandidateCollectionError,
        match="경사 확인 후보 0/2, 그늘 확인 후보 0/2",
    ):
        _validate_candidate_payload(
            {
                "group_id": record["group_id"],
                "candidates": record["candidates"],
            },
            row=row,
            minimum_candidates=2,
            minimum_known_slope_candidates=2,
            minimum_known_shade_candidates=2,
            quality_retry_delay_seconds=0,
        )
