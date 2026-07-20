"""동의한 실제 후기를 AI 전역 재학습 형식으로 익명화해 내보낸다.

개인화에는 로그인 사용자의 후기를 사용할 수 있지만, 이 스크립트는
training_consent=true인 후기만 전역 모델 후보 데이터로 포함한다.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
from pathlib import Path

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from backend.app.database import RouteImpression, RouteReview
from backend.app.personalization import reward_target
from ai.scoring.train import FEATURE_COLS, MIN_REVIEWERS


def _reviewer_id(user_id: str, salt: str) -> str:
    return hashlib.sha256(f"{salt}:{user_id}".encode("utf-8")).hexdigest()[:20]


def _relevance(
    review: RouteReview, *, usable_weight: float, rating_weight: float, reuse_weight: float,
) -> float:
    return 4 * reward_target(
        was_usable=review.was_usable,
        rating=review.rating,
        would_reuse=review.would_reuse,
        usable_weight=usable_weight,
        rating_weight=rating_weight,
        reuse_weight=reuse_weight,
    )


def export(
    database_url: str, output_dir: Path, salt: str, *,
    usable_weight: float, rating_weight: float, reuse_weight: float,
) -> dict:
    engine = create_engine(database_url, pool_pre_ping=True)
    with Session(engine) as session:
        rows = session.execute(
            select(RouteReview, RouteImpression)
            .join(RouteImpression, RouteReview.impression_id == RouteImpression.id)
            .where(RouteReview.training_consent.is_(True))
            .order_by(RouteReview.created_at)
        ).all()
    reviewers = {review.user_id for review, _ in rows}
    if len(reviewers) < MIN_REVIEWERS:
        raise ValueError(f"전역 재학습에는 동의한 사용자 {MIN_REVIEWERS}명이 필요합니다. 현재 {len(reviewers)}명입니다.")

    labels = []
    snapshots: dict[tuple[str, str], dict] = {}
    for review, impression in rows:
        features = json.loads(impression.feature_snapshot)
        group_id = str(features.get("group_id") or "")
        if not group_id:
            continue
        versioned_group = f"{group_id}@{impression.model_version}"
        versioned_route = f"{impression.route_id}@{impression.model_version}"
        snapshot = {
            "group_id": versioned_group,
            "route_id": versioned_route,
            "features": {name: features.get(name) for name in FEATURE_COLS},
            "model_version": impression.model_version,
        }
        key = (versioned_group, versioned_route)
        if key in snapshots and snapshots[key]["features"] != snapshot["features"]:
            raise ValueError(f"동일 모델/경로의 피처 스냅샷이 서로 다릅니다: {versioned_route}")
        snapshots[key] = snapshot
        labels.append({
            "reviewer_id": _reviewer_id(review.user_id, salt),
            "group_id": versioned_group,
            "route_id": versioned_route,
            "profile": impression.profile,
            "relevance": _relevance(
                review, usable_weight=usable_weight,
                rating_weight=rating_weight, reuse_weight=reuse_weight,
            ),
            "notes": "consented-route-review",
        })

    output_dir.mkdir(parents=True, exist_ok=True)
    labels_path = output_dir / "route_labels.csv"
    with labels_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["reviewer_id", "group_id", "route_id", "profile", "relevance", "notes"])
        writer.writeheader()
        writer.writerows(labels)
    features_path = output_dir / "route_features.jsonl"
    features_path.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False, separators=(",", ":")) for row in snapshots.values()) + "\n",
        encoding="utf-8",
    )
    return {"reviews": len(labels), "reviewers": len(reviewers), "routes": len(snapshots)}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database-url", default=os.getenv("DATABASE_URL", ""))
    parser.add_argument("--output-dir", type=Path, default=Path("ai/data/training/generated/reviews"))
    parser.add_argument("--anonymization-salt", default=os.getenv("TRAINING_ANONYMIZATION_SALT", ""))
    parser.add_argument("--usable-weight", type=float, required=True)
    parser.add_argument("--rating-weight", type=float, required=True)
    parser.add_argument("--reuse-weight", type=float, required=True)
    args = parser.parse_args()
    if not args.database_url.startswith("postgresql"):
        raise SystemExit("PostgreSQL DATABASE_URL이 필요합니다.")
    if len(args.anonymization_salt) < 16:
        raise SystemExit("16자 이상의 TRAINING_ANONYMIZATION_SALT가 필요합니다.")
    print(json.dumps(export(
        args.database_url, args.output_dir, args.anonymization_salt,
        usable_weight=args.usable_weight, rating_weight=args.rating_weight,
        reuse_weight=args.reuse_weight,
    ), ensure_ascii=False))


if __name__ == "__main__":
    main()
