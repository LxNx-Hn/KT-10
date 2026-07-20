"""9명 초기 라벨에 동의 후기 데이터를 제한적으로 섞어 후보 전역 모델을 만든다.

후기 데이터 비중은 실행 시 팀이 명시하며 결과는 candidate 파일에만 저장한다.
평가·전문가 승인 전 운영 rankers.pkl을 자동 덮어쓰지 않는다.
"""
from __future__ import annotations

import argparse
import hashlib
from pathlib import Path

import pandas as pd

from ai.scoring.train import load_human_training_data, train_rankers


def _rankable_review_groups(frame: pd.DataFrame) -> pd.DataFrame:
    counts = frame.groupby(["profile", "group_id"])["route_id"].nunique()
    valid = set(counts[counts >= 2].index)
    return frame[
        frame.apply(lambda row: (row["profile"], row["group_id"]) in valid, axis=1)
    ].copy()


def _deterministic_group_sample(frame: pd.DataFrame, maximum_rows: int) -> pd.DataFrame:
    selected: list[pd.DataFrame] = []
    used = 0
    groups = list(frame.groupby(["profile", "group_id"], sort=False))
    groups.sort(key=lambda item: hashlib.sha256(f"{item[0][0]}:{item[0][1]}".encode()).hexdigest())
    for _, group in groups:
        if used + len(group) <= maximum_rows:
            selected.append(group)
            used += len(group)
    return pd.concat(selected, ignore_index=True) if selected else frame.iloc[0:0].copy()


def compose(initial: pd.DataFrame, reviews: pd.DataFrame, review_share: float) -> pd.DataFrame:
    if not 0 <= review_share < 0.5:
        raise ValueError("review_share는 0 이상 0.5 미만이어야 합니다.")
    if review_share == 0 or reviews.empty:
        return initial
    rankable = _rankable_review_groups(reviews)
    if rankable.empty:
        raise ValueError("같은 OD·프로필에서 서로 다른 경로 후기 2개 이상이 누적된 그룹이 없습니다.")
    maximum_review_rows = int(len(initial) * review_share / (1 - review_share))
    selected = _deterministic_group_sample(rankable, maximum_review_rows)
    return pd.concat([initial.assign(training_source="initial-team"), selected.assign(training_source="consented-review")], ignore_index=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--initial-labels", type=Path, default=Path("ai/data/training/route_labels.csv"))
    parser.add_argument("--initial-features", type=Path, default=Path("ai/data/training/route_features.jsonl"))
    parser.add_argument("--review-labels", type=Path, default=Path("ai/data/training/generated/reviews/route_labels.csv"))
    parser.add_argument("--review-features", type=Path, default=Path("ai/data/training/generated/reviews/route_features.jsonl"))
    parser.add_argument("--review-share", type=float, required=True, help="팀이 승인한 후기 행 비중(0 이상 0.5 미만)")
    parser.add_argument("--output", type=Path, default=Path("ai/data/rankers.candidate.pkl"))
    args = parser.parse_args()
    initial = load_human_training_data(args.initial_labels, args.initial_features)
    reviews = load_human_training_data(
        args.review_labels, args.review_features, require_reviewers_per_item=False,
    )
    combined = compose(initial, reviews, args.review_share)
    train_rankers(combined, args.output)
    actual_share = float((combined.get("training_source") == "consented-review").mean()) if "training_source" in combined else 0.0
    print(f"후보 모델 저장: {args.output} (후기 행 비중 {actual_share:.1%})")


if __name__ == "__main__":
    main()
