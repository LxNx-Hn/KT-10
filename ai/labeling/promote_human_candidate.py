"""검토가 끝난 human candidate를 관리자 승인 운영 artifact로 승격한다."""
from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

from scoring.artifacts import (
    ArtifactError,
    file_sha256,
    read_ranker_artifact,
    write_ranker_artifact,
)
from scoring.train import (
    FEATURE_COLS,
    HUMAN_CANDIDATE_PATH,
    MODEL_PATH,
    PROFILES,
)


def promote(
    *,
    source: Path,
    output: Path,
    expected_source_sha256: str,
    approved_by: str,
    approval_note: str,
) -> dict:
    actual_sha256 = file_sha256(source)
    if actual_sha256 != expected_source_sha256.lower():
        raise ValueError("검토한 candidate SHA-256과 현재 파일이 일치하지 않습니다.")
    if not approved_by.strip() or not approval_note.strip():
        raise ValueError("승인자와 승인 근거는 비어 있을 수 없습니다.")
    try:
        manifest, rankers = read_ranker_artifact(source, load_models=True)
    except ArtifactError as exc:
        raise ValueError(f"candidate artifact가 올바르지 않습니다: {exc}") from exc
    if manifest.get("model_tier") != "human_candidate":
        raise ValueError("human_candidate tier만 이 절차로 승격할 수 있습니다.")
    if manifest.get("label_origin") != "human_reviewers":
        raise ValueError(
            "운영 승격에는 human_reviewers 라벨 출처만 허용됩니다. "
            "후기 혼합 후보는 별도 검토·재라벨링이 필요합니다."
        )
    if manifest.get("feature_columns") != FEATURE_COLS or set(rankers) != set(PROFILES):
        raise ValueError("candidate 피처 또는 6개 프로필 계약이 현재 코드와 다릅니다.")
    metrics = manifest.get("metrics")
    if not isinstance(metrics, dict) or set(metrics) != set(PROFILES):
        raise ValueError("candidate에 6개 프로필 검증 지표가 없습니다.")
    for profile in PROFILES:
        profile_metrics = metrics.get(profile)
        holdout = (
            profile_metrics.get("group_holdout")
            if isinstance(profile_metrics, dict)
            else None
        )
        try:
            od_count = int(profile_metrics.get("od_count", 0))
            validation_od_count = int(
                holdout.get("validation_od_count", 0)
            )
        except (AttributeError, TypeError, ValueError) as exc:
            raise ValueError(
                f"{profile}: OD-group holdout 지표 형식이 올바르지 않습니다."
            ) from exc
        if (
            not isinstance(holdout, dict)
            or holdout.get("status") != "evaluated"
            or od_count < 3
            or validation_od_count < 1
        ):
            raise ValueError(
                f"{profile}: 검증된 OD-group holdout 지표가 없습니다."
            )

    promoted_at = datetime.now(UTC).isoformat()
    metadata = {
        key: value
        for key, value in manifest.items()
        if key not in {"artifact_schema_version", "profiles", "models", "promotion"}
    }
    metadata.update({
        "model_tier": "human_validated",
        "model_version": (
            "xgboost-human-validated-"
            + datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        ),
        "promotion": {
            "auto_promoted": False,
            "approved_by": approved_by.strip(),
            "approval_note": approval_note.strip(),
            "promoted_at": promoted_at,
            "source_path": str(source),
            "source_sha256": actual_sha256,
            "source_model_version": manifest.get("model_version"),
        },
    })
    promoted_manifest = write_ranker_artifact(
        output,
        metadata=metadata,
        rankers=rankers,
    )
    return {
        "output": str(output),
        "model_tier": promoted_manifest["model_tier"],
        "model_version": promoted_manifest["model_version"],
        "source_sha256": actual_sha256,
        "promoted_at": promoted_at,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="관리자 검토가 끝난 human candidate 수동 승격"
    )
    parser.add_argument("--source", type=Path, default=HUMAN_CANDIDATE_PATH)
    parser.add_argument("--output", type=Path, default=MODEL_PATH)
    parser.add_argument("--expected-source-sha256", required=True)
    parser.add_argument("--approved-by", required=True)
    parser.add_argument("--approval-note", required=True)
    args = parser.parse_args()
    print(json.dumps(promote(
        source=args.source,
        output=args.output,
        expected_source_sha256=args.expected_source_sha256,
        approved_by=args.approved_by,
        approval_note=args.approval_note,
    ), ensure_ascii=False))


if __name__ == "__main__":
    main()
