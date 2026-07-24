from __future__ import annotations

import csv
import json

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from ai.scoring.schema import FEATURE_COLS
from ai.scoring.snapshots import build_live_feature_snapshot
from backend.app.database import Base, RouteImpression, RouteReview
from backend.ml.export_consented_reviews import _relevance, export


def _flat_live_features(route_id: str = "route-live") -> dict:
    snapshot = build_live_feature_snapshot(
        group_id="group-live",
        holdout_group_id="od-live",
        route_id=route_id,
        features={name: None for name in FEATURE_COLS},
        sources=["test-live-provider", "test-building-shade"],
        geometry_quality="exact",
        captured_at="2026-07-24T01:00:00+00:00",
        shade_evaluated_at="2026-07-24T09:00:00+09:00",
    )
    return {
        **snapshot["features"],
        **{
            name: value
            for name, value in snapshot.items()
            if name != "features"
        },
        "training_eligible": True,
        "profile": "general",
    }


def test_observation_dimensions_do_not_infer_current_relevance_weights():
    common = {
        "user_id": "reviewer",
        "route_id": "route",
        "was_usable": True,
        "rating": 4,
        "would_reuse": True,
    }
    low_difficulty = RouteReview(
        **common,
        crowding_difficulty=1,
        transfer_information_difficulty=1,
        accessibility_facility_difficulty=1,
    )
    high_difficulty = RouteReview(
        **common,
        crowding_difficulty=5,
        transfer_information_difficulty=5,
        accessibility_facility_difficulty=5,
    )
    weights = {
        "usable_weight": 0.4,
        "rating_weight": 0.4,
        "reuse_weight": 0.2,
    }
    assert _relevance(low_difficulty, **weights) == _relevance(
        high_difficulty,
        **weights,
    )


def _database(
    path,
    *,
    eligible_count: int,
    demo_count: int = 0,
    tamper_hash: bool = False,
) -> str:
    database_url = f"sqlite+pysqlite:///{path.as_posix()}"
    engine = create_engine(database_url)
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        for index in range(eligible_count):
            features = _flat_live_features()
            if tamper_hash:
                features["feature_snapshot_hash"] = "0" * 64
            impression = RouteImpression(
                id=f"eligible-impression-{index}",
                user_id=f"eligible-user-{index}",
                route_id="route-live",
                model_version="rules-live-v1",
                profile="general",
                rank=1,
                feature_snapshot=json.dumps(features),
            )
            session.add(impression)
            session.add(RouteReview(
                id=f"eligible-review-{index}",
                user_id=f"eligible-user-{index}",
                impression_id=impression.id,
                route_id=impression.route_id,
                was_usable=True,
                rating=2,
                would_reuse=False,
                training_consent=True,
            ))
        for index in range(demo_count):
            impression = RouteImpression(
                id=f"demo-impression-{index}",
                user_id=f"demo-user-{index}",
                route_id="route-demo",
                model_version="rules-demo-v1",
                profile="general",
                rank=1,
                feature_snapshot=json.dumps({
                    "snapshot_kind": "demo_route_candidate",
                    "training_eligible": False,
                }),
            )
            session.add(impression)
            session.add(RouteReview(
                id=f"demo-review-{index}",
                user_id=f"demo-user-{index}",
                impression_id=impression.id,
                route_id=impression.route_id,
                was_usable=True,
                rating=5,
                would_reuse=True,
                training_consent=True,
            ))
        session.commit()
    engine.dispose()
    return database_url


def test_export_excludes_demo_and_preserves_live_provenance_and_continuous_label(
    tmp_path,
):
    database_url = _database(
        tmp_path / "reviews.sqlite3",
        eligible_count=9,
        demo_count=1,
    )
    output = tmp_path / "exported"

    report = export(
        database_url,
        output,
        "test-anonymization-salt",
        usable_weight=0.2,
        rating_weight=0.3,
        reuse_weight=0.5,
    )

    assert report["consented_reviews"] == 10
    assert report["eligible_reviews"] == 9
    assert report["ineligible_reviews"] == 1
    assert report["eligible_reviewers"] == 9
    assert report["excluded_reasons"] == {
        "training_eligible_not_true+snapshot_kind_not_live": 1
    }
    assert json.loads(
        (output / "export_report.json").read_text(encoding="utf-8")
    ) == report

    snapshots = [
        json.loads(line)
        for line in (output / "route_features.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    assert len(snapshots) == 1
    assert snapshots[0]["snapshot_kind"] == "live_route_candidate"
    assert snapshots[0]["shade_evaluated_at"] == "2026-07-24T09:00:00+09:00"
    assert snapshots[0]["captured_at"] == "2026-07-24T01:00:00+00:00"

    with (output / "route_labels.csv").open(
        encoding="utf-8",
        newline="",
    ) as handle:
        relevance = [
            float(row["relevance"])
            for row in csv.DictReader(handle)
        ]
    assert relevance == pytest.approx([1.1] * 9)


def test_export_minimum_counts_only_eligible_live_reviewers(tmp_path):
    database_url = _database(
        tmp_path / "insufficient.sqlite3",
        eligible_count=8,
        demo_count=2,
    )

    with pytest.raises(
        ValueError,
        match=r"eligible 후기 8건/사용자 8명, 제외 2건",
    ):
        export(
            database_url,
            tmp_path / "exported",
            "test-anonymization-salt",
            usable_weight=0.2,
            rating_weight=0.3,
            reuse_weight=0.5,
        )


def test_export_rejects_tampered_original_live_snapshot_hash(tmp_path):
    database_url = _database(
        tmp_path / "tampered.sqlite3",
        eligible_count=9,
        tamper_hash=True,
    )

    with pytest.raises(ValueError, match="feature_snapshot_hash"):
        export(
            database_url,
            tmp_path / "exported",
            "test-anonymization-salt",
            usable_weight=0.2,
            rating_weight=0.3,
            reuse_weight=0.5,
        )
