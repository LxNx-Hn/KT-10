"""Train a reproducible profile-specific pairwise ranker from human labels.

This intentionally refuses synthetic labels. It is dependency-free so the team can
inspect every learned coefficient before a model is promoted to production.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
from collections import Counter, defaultdict
from pathlib import Path

FEATURES = (
    "accessibility", "walk_comfort", "elevator", "low_floor_bus",
    "weather_safety", "safety", "data_reliability", "time_efficiency",
)


def _sigmoid(value: float) -> float:
    return 1 / (1 + math.exp(-max(-30.0, min(30.0, value))))


def load_examples(labels_path: Path, features_path: Path) -> dict[str, list[list[float]]]:
    features = {
        row["route_id"]: row
        for line in features_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
        for row in [json.loads(line)]
    }
    votes: dict[tuple[str, str, str, str], list[str]] = defaultdict(list)
    reviewers: set[str] = set()
    with labels_path.open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            if row["preferred"] not in {"left", "right"}:
                continue
            reviewers.add(row["reviewer_id"])
            votes[(row["profile"], row["task_id"], row["left_route_id"], row["right_route_id"])].append(row["preferred"])
    if len(reviewers) < 9:
        raise ValueError(f"Need labels from 9 reviewers; found {len(reviewers)}.")
    examples: dict[str, list[list[float]]] = defaultdict(list)
    for (profile, _, left_id, right_id), choices in votes.items():
        counts = Counter(choices)
        if counts["left"] == counts["right"] or left_id not in features or right_id not in features:
            continue
        winner, loser = (left_id, right_id) if counts["left"] > counts["right"] else (right_id, left_id)
        diff = [
            (float(features[winner]["components"][name]) - float(features[loser]["components"][name])) / 100
            for name in FEATURES
        ]
        examples[profile].append(diff)
    if not examples:
        raise ValueError("No majority pairwise labels with matching route feature snapshots.")
    return examples


def fit(examples: list[list[float]], epochs: int = 400, learning_rate: float = 0.08, l2: float = 0.02) -> list[float]:
    weights = [0.0] * len(FEATURES)
    for _ in range(epochs):
        for diff in examples:
            probability = _sigmoid(sum(w * x for w, x in zip(weights, diff)))
            for i, value in enumerate(diff):
                weights[i] += learning_rate * ((1 - probability) * value - l2 * weights[i])
    return weights


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--labels", type=Path, default=Path("backend/ml/pairwise_labels.csv"))
    parser.add_argument("--features", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=Path("backend/models/pairwise_ranker.json"))
    args = parser.parse_args()
    examples = load_examples(args.labels, args.features)
    payload = {
        "model_version": "pairwise-human-v1",
        "features": FEATURES,
        "profiles": {profile: {"weights": fit(rows), "example_count": len(rows)} for profile, rows in examples.items()},
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"wrote {args.output}")


if __name__ == "__main__":
    main()
