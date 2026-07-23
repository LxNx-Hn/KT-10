"""9명 초기 라벨에 동의 후기 데이터를 제한적으로 섞어 후보 전역 모델을 만든다.

후기 데이터 비중은 실행 시 팀이 명시하며 결과는 candidate 파일에만 저장한다.
평가·전문가 승인 전 운영 human-validated artifact를 자동 덮어쓰지 않는다.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import pandas as pd


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


def _load_export_report(
    path: Path,
    raw_review_count: int,
    raw_reviewer_count: int,
) -> dict:
    if not path.exists():
        raise ValueError(
            "동의 후기 exporter의 export_report.json이 필요합니다."
        )
    try:
        report = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("동의 후기 export report를 읽을 수 없습니다.") from exc
    if not isinstance(report, dict):
        raise ValueError("동의 후기 export report는 JSON 객체여야 합니다.")
    eligible = report.get("eligible_reviews")
    ineligible = report.get("ineligible_reviews")
    eligible_reviewers = report.get("eligible_reviewers")
    if (
        not isinstance(eligible, int)
        or isinstance(eligible, bool)
        or eligible < 0
        or not isinstance(ineligible, int)
        or isinstance(ineligible, bool)
        or ineligible < 0
        or not isinstance(eligible_reviewers, int)
        or isinstance(eligible_reviewers, bool)
        or eligible_reviewers < 0
    ):
        raise ValueError(
            "동의 후기 export report에 유효한 "
            "eligible/ineligible/reviewer count가 없습니다."
        )
    if eligible != raw_review_count:
        raise ValueError(
            "동의 후기 export report의 eligible count와 라벨 행 수가 다릅니다."
        )
    if eligible_reviewers != raw_reviewer_count:
        raise ValueError(
            "동의 후기 export report의 reviewer count와 라벨 평가자 수가 다릅니다."
        )
    return report


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
    # 서버 런타임은 학습 패키지를 설치하지 않는다. 이 도구를 실제로 실행할
    # 때만 ai/requirements.txt의 XGBoost 학습 모듈을 불러온다.
    from ai.scoring.train import (
        load_consented_review_training_data,
        load_human_training_data,
        train_rankers,
    )

    parser = argparse.ArgumentParser()
    parser.add_argument("--initial-labels", type=Path, default=Path("ai/data/training/route_labels.csv"))
    parser.add_argument("--initial-features", type=Path, default=Path("ai/data/training/route_features.jsonl"))
    parser.add_argument("--review-labels", type=Path, default=Path("ai/data/training/generated/reviews/route_labels.csv"))
    parser.add_argument("--review-features", type=Path, default=Path("ai/data/training/generated/reviews/route_features.jsonl"))
    parser.add_argument(
        "--review-export-report",
        type=Path,
        default=Path(
            "ai/data/training/generated/reviews/export_report.json"
        ),
    )
    parser.add_argument("--review-share", type=float, required=True, help="팀이 승인한 후기 행 비중(0 이상 0.5 미만)")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("ai/data/rankers.review-mixed-candidate.zip"),
    )
    args = parser.parse_args()
    initial = load_human_training_data(args.initial_labels, args.initial_features)
    raw_reviews = pd.read_csv(args.review_labels, dtype=str)
    raw_review_count = len(raw_reviews)
    export_report = _load_export_report(
        args.review_export_report,
        raw_review_count,
        int(raw_reviews["reviewer_id"].nunique()),
    )
    reviews = load_consented_review_training_data(
        args.review_labels,
        args.review_features,
    )
    combined = compose(initial, reviews, args.review_share)
    actual_share = float((combined.get("training_source") == "consented-review").mean()) if "training_source" in combined else 0.0
    train_rankers(
        combined,
        args.output,
        label_origin="human_reviewers_and_consented_reviews",
        candidate_tier="review_mixed_candidate",
        training_lineage={
            "source": "initial_human_plus_consented_reviews",
            "requested_review_share": args.review_share,
            "actual_review_row_share": actual_share,
            "review_export_report": export_report,
            "automatic_promotion_allowed": False,
            "production_eligible": False,
            "requires_separate_manual_review": True,
        },
    )
    print(f"후보 모델 저장: {args.output} (후기 행 비중 {actual_share:.1%})")


if __name__ == "__main__":
    main()
