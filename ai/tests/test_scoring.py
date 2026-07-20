"""실제 라벨 학습 게이트와 XGBoost 추론 테스트."""
from __future__ import annotations

import json

import pandas as pd
import pytest

from scoring.predict import predict_and_rank
from scoring.train import (
    FEATURE_COLS,
    ModelNotReady,
    load_human_training_data,
    train_rankers,
    _group_holdout_metrics,
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
                rows.append({"group_id": f"{profile}-{group}", "route_id": f"r-{route}", "profile": profile, "relevance": relevance, **features})
    return pd.DataFrame(rows)


@pytest.fixture(scope="module")
def rankers(tmp_path_factory):
    return train_rankers(_training_frame(), tmp_path_factory.mktemp("models") / "rankers.pkl")


def test_all_profiles_trained(rankers):
    assert set(rankers) == {"general", "elderly", "child", "youth", "disabled", "pregnant"}


def test_predict_top_k_and_probability(rankers):
    routes = [{col: 0.5 for col in FEATURE_COLS} for _ in range(3)]
    result = predict_and_rank(rankers, routes, "elderly", top_k=3)
    assert [item["rank"] for item in result] == [1, 2, 3]
    assert sum(item["probability"] for item in result) == pytest.approx(1.0, abs=0.01)


def test_disabled_model_learns_labeled_preference(rankers):
    base = {col: 0.5 for col in FEATURE_COLS}
    routes = [
        {**base, "stair_count": 2.0, "elevator_ratio": 0.0},
        {**base, "stair_count": 0.0, "elevator_ratio": 1.0},
        {**base, "stair_count": 1.0, "elevator_ratio": 0.5},
    ]
    assert predict_and_rank(rankers, routes, "disabled", 3)[0]["route_index"] == 1


def test_human_loader_requires_nine_reviewers(tmp_path):
    labels = tmp_path / "labels.csv"
    labels.write_text(
        "reviewer_id,group_id,route_id,profile,relevance\n"
        "u1,g1,r1,general,4\n",
        encoding="utf-8",
    )
    features = tmp_path / "features.jsonl"
    features.write_text(json.dumps({"group_id": "g1", "route_id": "r1", "features": {}}), encoding="utf-8")
    with pytest.raises(ModelNotReady, match="최소 9명"):
        load_human_training_data(labels, features)


def test_human_loader_rejects_partially_labeled_route(tmp_path):
    labels = tmp_path / "labels.csv"
    rows = ["reviewer_id,group_id,route_id,profile,relevance"]
    rows.extend(f"u{i},g1,r1,general,4" for i in range(1, 10))
    rows.extend(f"u{i},g1,r2,general,2" for i in range(1, 9))
    labels.write_text("\n".join(rows) + "\n", encoding="utf-8")
    features = tmp_path / "features.jsonl"
    features.write_text("\n".join([
        json.dumps({"group_id": "g1", "route_id": "r1", "features": {}}),
        json.dumps({"group_id": "g1", "route_id": "r2", "features": {}}),
    ]), encoding="utf-8")
    with pytest.raises(ModelNotReady, match="모든 OD·경로·프로필"):
        load_human_training_data(labels, features)


def test_group_holdout_keeps_whole_od_groups_together():
    metrics = _group_holdout_metrics("general", _training_frame().query("profile == 'general'"))
    assert metrics["status"] == "evaluated"
    assert metrics["train_od_count"] + metrics["validation_od_count"] == 4
    assert 0 <= metrics["ndcg_at_3"] <= 1
