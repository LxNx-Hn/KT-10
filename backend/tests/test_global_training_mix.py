import json

import pandas as pd
import pytest

from backend.ml.train_global_candidate import _load_export_report, compose


def _frame(prefix: str, count: int) -> pd.DataFrame:
    return pd.DataFrame([
        {"profile": "general", "group_id": f"{prefix}-g-{i // 3}", "route_id": f"{prefix}-r-{i}"}
        for i in range(count)
    ])


def test_review_rows_are_capped_at_configured_small_share():
    combined = compose(_frame("initial", 100), _frame("review", 100), 0.2)
    review_count = (combined["training_source"] == "consented-review").sum()
    assert review_count == 24
    assert review_count / len(combined) <= 0.2


def test_sampling_never_splits_a_ranking_group():
    combined = compose(_frame("initial", 10), _frame("review", 6), 0.2)
    reviews = combined[combined["training_source"] == "consented-review"]
    assert reviews.empty or reviews.groupby(["profile", "group_id"]).size().eq(3).all()


def test_sparse_single_route_reviews_are_not_treated_as_ranking_data():
    sparse = pd.DataFrame([
        {"profile": "general", "group_id": f"g-{i}", "route_id": f"r-{i}"}
        for i in range(9)
    ])
    with pytest.raises(ValueError, match="서로 다른 경로 후기 2개"):
        compose(_frame("initial", 100), sparse, 0.1)


def test_review_share_cannot_silently_dominate():
    with pytest.raises(ValueError):
        compose(_frame("initial", 10), _frame("review", 10), 0.5)


def test_review_export_report_counts_must_match_training_labels(tmp_path):
    report_path = tmp_path / "export_report.json"
    report_path.write_text(
        json.dumps({
            "eligible_reviews": 9,
            "ineligible_reviews": 3,
            "eligible_reviewers": 9,
        }),
        encoding="utf-8",
    )
    report = _load_export_report(
        report_path,
        raw_review_count=9,
        raw_reviewer_count=9,
    )
    assert report["ineligible_reviews"] == 3

    with pytest.raises(ValueError, match="라벨 행 수"):
        _load_export_report(
            report_path,
            raw_review_count=8,
            raw_reviewer_count=9,
        )
