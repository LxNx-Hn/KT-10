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
from collections import Counter
from pathlib import Path

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from backend.app.database import RouteImpression, RouteReview
from backend.app.personalization import reward_target
from ai.scoring.snapshots import (
    LIVE_SNAPSHOT_KIND,
    build_live_feature_snapshot,
    validate_live_feature_snapshot,
)
from ai.scoring.schema import FEATURE_COLS, MIN_REVIEWERS


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


def _parse_impression_features(impression: RouteImpression) -> dict:
    try:
        features = json.loads(impression.feature_snapshot)
    except (TypeError, json.JSONDecodeError) as exc:
        raise ValueError(
            f"후기 impression 피처 JSON이 손상되었습니다: {impression.id}"
        ) from exc
    if not isinstance(features, dict):
        raise ValueError(
            f"후기 impression 피처는 JSON 객체여야 합니다: {impression.id}"
        )
    return features


def _ineligible_reasons(features: dict) -> tuple[str, ...]:
    reasons = []
    if features.get("training_eligible") is not True:
        reasons.append("training_eligible_not_true")
    if features.get("snapshot_kind") != LIVE_SNAPSHOT_KIND:
        reasons.append("snapshot_kind_not_live")
    return tuple(reasons)


def _verified_original_snapshot(features: dict) -> dict:
    required_provenance = {
        "group_id",
        "holdout_group_id",
        "route_id",
        "snapshot_schema_version",
        "snapshot_kind",
        "captured_at",
        "shade_evaluated_at",
        "sources",
        "feature_snapshot_hash",
    }
    missing_provenance = sorted(
        name
        for name in required_provenance
        if features.get(name) in (None, "", [])
    )
    missing_features = sorted(set(FEATURE_COLS).difference(features))
    if missing_provenance or missing_features:
        details = [
            *(f"provenance:{name}" for name in missing_provenance),
            *(f"feature:{name}" for name in missing_features),
        ]
        raise ValueError(
            "eligible 후기 피처에 검증 가능한 live 스냅샷 정보가 없습니다: "
            + ", ".join(details)
        )
    snapshot = {
        "snapshot_schema_version": features["snapshot_schema_version"],
        "snapshot_kind": features["snapshot_kind"],
        "captured_at": features["captured_at"],
        "shade_evaluated_at": features["shade_evaluated_at"],
        "group_id": features["group_id"],
        "holdout_group_id": features["holdout_group_id"],
        "route_id": features["route_id"],
        "sources": features["sources"],
        "geometry_quality": features.get("geometry_quality"),
        "features": {name: features[name] for name in FEATURE_COLS},
        "feature_snapshot_hash": features["feature_snapshot_hash"],
    }
    # 해시, 숫자 범위, 시간대, source 및 live 스냅샷 계약을 원본 그대로 검증한다.
    validate_live_feature_snapshot(snapshot, FEATURE_COLS)
    return snapshot


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

    labels = []
    snapshots: dict[tuple[str, str], dict] = {}
    eligible_reviewers: set[str] = set()
    excluded_reasons: Counter[str] = Counter()
    for review, impression in rows:
        features = _parse_impression_features(impression)
        reasons = _ineligible_reasons(features)
        if reasons:
            excluded_reasons["+".join(reasons)] += 1
            continue

        original_snapshot = _verified_original_snapshot(features)
        if original_snapshot["route_id"] != impression.route_id:
            raise ValueError(
                "eligible 후기의 스냅샷 route_id와 impression route_id가 다릅니다."
            )
        group_id = str(original_snapshot["group_id"])
        versioned_group = f"{group_id}@{impression.model_version}"
        versioned_route = f"{impression.route_id}@{impression.model_version}"
        snapshot = build_live_feature_snapshot(
            group_id=versioned_group,
            route_id=versioned_route,
            features=original_snapshot["features"],
            sources=original_snapshot["sources"],
            geometry_quality=original_snapshot.get("geometry_quality"),
            captured_at=str(original_snapshot["captured_at"]),
            holdout_group_id=str(original_snapshot["holdout_group_id"]),
            shade_evaluated_at=str(original_snapshot["shade_evaluated_at"]),
        )
        validate_live_feature_snapshot(snapshot, FEATURE_COLS)
        key = (versioned_group, versioned_route)
        if key in snapshots and snapshots[key] != snapshot:
            raise ValueError(f"동일 모델/경로의 피처 스냅샷이 서로 다릅니다: {versioned_route}")
        snapshots[key] = snapshot
        eligible_reviewers.add(review.user_id)
        labels.append({
            "reviewer_id": _reviewer_id(review.user_id, salt),
            "group_id": versioned_group,
            "route_id": versioned_route,
            "feature_snapshot_hash": snapshot["feature_snapshot_hash"],
            "profile": impression.profile,
            "relevance": _relevance(
                review, usable_weight=usable_weight,
                rating_weight=rating_weight, reuse_weight=reuse_weight,
            ),
            "notes": "consented-route-review",
        })

    ineligible_review_count = sum(excluded_reasons.values())
    if len(eligible_reviewers) < MIN_REVIEWERS:
        raise ValueError(
            "전역 재학습에는 eligible live 후기 사용자 "
            f"{MIN_REVIEWERS}명이 필요합니다. "
            f"현재 eligible 후기 {len(labels)}건/"
            f"사용자 {len(eligible_reviewers)}명, "
            f"제외 {ineligible_review_count}건입니다."
        )

    output_dir.mkdir(parents=True, exist_ok=True)
    labels_path = output_dir / "route_labels.csv"
    with labels_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=[
            "reviewer_id",
            "group_id",
            "route_id",
            "feature_snapshot_hash",
            "profile",
            "relevance",
            "notes",
        ])
        writer.writeheader()
        writer.writerows(labels)
    features_path = output_dir / "route_features.jsonl"
    features_path.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False, separators=(",", ":")) for row in snapshots.values()) + "\n",
        encoding="utf-8",
    )
    report = {
        "consented_reviews": len(rows),
        "eligible_reviews": len(labels),
        "ineligible_reviews": ineligible_review_count,
        "eligible_reviewers": len(eligible_reviewers),
        "routes": len(snapshots),
        "excluded_reasons": dict(sorted(excluded_reasons.items())),
        # 기존 자동화가 읽는 키는 eligible 집합 의미로 유지한다.
        "reviews": len(labels),
        "reviewers": len(eligible_reviewers),
    }
    (output_dir / "export_report.json").write_text(
        json.dumps(
            report,
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return report


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
