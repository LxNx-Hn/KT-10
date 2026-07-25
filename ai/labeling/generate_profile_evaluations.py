"""고정된 실제 후보 스냅샷을 프로필별로 비교해 baseline 라벨을 만든다.

평가는 동일 후보군 안에서만 수행한다. 미확인 피처는 비교와 분모에서
제외하며 0으로 대체하지 않는다. 동백전 가맹점 수는 생활정보이므로 이
평가와 학습 입력에 사용하지 않는다.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import shutil
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from scoring.bootstrap_baseline import (
    EVALUATION_LABEL_ORIGIN,
    EVALUATION_LABEL_SCHEMA_VERSION,
)
from scoring.schema import AUXILIARY_FEATURE_COLS
from scoring.snapshots import validate_live_feature_snapshot
from scoring.train import FEATURE_COLS, PROFILES

DEFAULT_RUBRIC_PATH = Path(__file__).with_name(
    "profile_evaluation_rubric.json"
)


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line_number, line in enumerate(
        path.read_text(encoding="utf-8").splitlines(),
        start=1,
    ):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
            validate_live_feature_snapshot(row, FEATURE_COLS)
        except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"피처 스냅샷 {line_number}행: {exc}") from exc
        rows.append(row)
    if not rows:
        raise ValueError("피처 스냅샷이 비어 있습니다.")
    return rows


def _load_rubric(path: Path) -> tuple[dict[str, Any], str]:
    payload = path.read_bytes()
    rubric = json.loads(payload)
    if rubric.get("schema_version") != "route-profile-rubric-v2":
        raise ValueError("지원하지 않는 프로필 평가 rubric입니다.")
    if rubric.get("missing_value_policy") != "exclude_from_comparison":
        raise ValueError("미확인 값은 비교에서 제외하는 정책이어야 합니다.")
    if set(rubric.get("profiles") or {}) != set(PROFILES):
        raise ValueError("rubric에는 6개 프로필이 정확히 한 번씩 필요합니다.")
    criteria = [
        *(rubric.get("shared_situation_criteria") or []),
        *(
            criterion
            for profile in PROFILES
            for criterion in rubric["profiles"][profile]
        ),
    ]
    forbidden = set(AUXILIARY_FEATURE_COLS)
    used_forbidden = sorted(
        forbidden.intersection(
            str(criterion.get("feature")) for criterion in criteria
        )
    )
    if used_forbidden:
        raise ValueError(
            "생활정보 피처는 프로필 평가에 사용할 수 없습니다: "
            + ", ".join(used_forbidden)
        )
    for criterion in criteria:
        feature = criterion.get("feature")
        if feature != "peak_slope_percent" and feature not in FEATURE_COLS:
            raise ValueError(f"알 수 없는 평가 피처입니다: {feature}")
        if criterion.get("direction") not in {"min", "max"}:
            raise ValueError(f"{feature}: direction은 min 또는 max여야 합니다.")
        weight = criterion.get("weight")
        if (
            isinstance(weight, bool)
            or not isinstance(weight, (int, float))
            or not math.isfinite(float(weight))
            or float(weight) <= 0
        ):
            raise ValueError(f"{feature}: weight는 양의 유한한 수여야 합니다.")
    return rubric, _sha256(payload)


def _criterion_value(
    features: dict[str, Any],
    feature: str,
) -> float | None:
    if feature == "peak_slope_percent":
        maximum = features.get("max_slope_percent")
        minimum = features.get("min_slope_percent")
        if maximum is None or minimum is None:
            return None
        return max(abs(float(maximum)), abs(float(minimum)))
    value = features.get(feature)
    if value is None:
        return None
    if isinstance(value, bool):
        return float(value)
    return float(value)


def _format_value(feature: str, value: float) -> str:
    if feature.endswith("_ratio"):
        return f"{value * 100:.1f}%"
    if feature.endswith("_m") or feature == "walk_distance_m":
        return f"{value:.0f}m"
    if "slope_percent" in feature:
        return f"{value:.1f}%"
    if feature == "total_duration_min":
        return f"{value:.0f}분"
    if feature.endswith("_count") or feature in {
        "transfer_count",
        "stair_count",
        "crosswalk_count",
    }:
        return f"{value:.0f}"
    return f"{value:.2f}"


def _active_criteria(
    snapshots: list[dict[str, Any]],
    criteria: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    active: list[dict[str, Any]] = []
    for criterion in criteria:
        values = {
            snapshot["route_id"]: _criterion_value(
                snapshot["features"],
                criterion["feature"],
            )
            for snapshot in snapshots
        }
        known = [value for value in values.values() if value is not None]
        if len(known) < 2:
            continue
        minimum = min(known)
        maximum = max(known)
        if abs(maximum - minimum) <= 1e-12:
            continue
        active.append({
            **criterion,
            "values": values,
            "minimum": minimum,
            "maximum": maximum,
        })
    return active


def _route_score(
    route_id: str,
    criteria: list[dict[str, Any]],
) -> tuple[float, list[dict[str, Any]]]:
    weighted_sum = 0.0
    observed_weight = 0.0
    evidence: list[dict[str, Any]] = []
    for criterion in criteria:
        value = criterion["values"][route_id]
        if value is None:
            continue
        span = criterion["maximum"] - criterion["minimum"]
        normalized = (value - criterion["minimum"]) / span
        utility = (
            normalized
            if criterion["direction"] == "max"
            else 1.0 - normalized
        )
        weight = float(criterion["weight"])
        weighted_sum += utility * weight
        observed_weight += weight
        evidence.append({
            "feature": criterion["feature"],
            "label": criterion["label"],
            "value": value,
            "utility": utility,
            "weight": weight,
            "influence": weight * abs(utility - 0.5),
        })
    if observed_weight == 0:
        return 0.5, []
    return weighted_sum / observed_weight, evidence


def _relevance(
    score: float,
    minimum: float,
    maximum: float,
    thresholds: dict[str, Any],
) -> int:
    if abs(maximum - minimum) <= 1e-12:
        return 3
    relative = (score - minimum) / (maximum - minimum)
    for label in (4, 3, 2, 1):
        if relative + 1e-12 >= float(thresholds[str(label)]):
            return label
    raise ValueError("relevance threshold 계약이 0을 포함하지 않습니다.")


def _rationale(
    relevance: int,
    evidence: list[dict[str, Any]],
) -> str:
    if not evidence:
        return (
            "후보군에서 비교 가능한 확인 피처의 차이가 없었습니다. "
            "미확인 값은 평가에서 제외했습니다."
        )
    ordered = sorted(
        evidence,
        key=lambda item: (
            item["utility"] if relevance <= 2 else -item["utility"],
            -item["influence"],
            item["feature"],
        ),
    )
    selected = ordered[:2]
    details = ", ".join(
        f"{item['label']} {_format_value(item['feature'], item['value'])}"
        for item in selected
    )
    judgment = "부담이 확인됐습니다" if relevance <= 2 else "상대적으로 유리합니다"
    return (
        f"동일 후보군의 확인 피처 중 {details} 기준이 {judgment}. "
        "미확인 값은 평가에서 제외했습니다."
    )


def generate(
    *,
    features_path: Path,
    labels_output_path: Path,
    report_output_path: Path,
    frozen_features_output_path: Path | None,
    rubric_path: Path,
    evaluation_run_id: str,
    evaluation_source: str,
) -> dict[str, Any]:
    if not evaluation_run_id.strip():
        raise ValueError("evaluation_run_id는 비어 있을 수 없습니다.")
    source_parts = evaluation_source.split(":", 1)
    if (
        len(source_parts) != 2
        or not all(part.strip() for part in source_parts)
        or source_parts[0].casefold() in {"human", "user", "reviewer"}
    ):
        raise ValueError("evaluation_source는 provider:evaluator 형식이어야 합니다.")

    snapshots = _read_jsonl(features_path)
    rubric, rubric_hash = _load_rubric(rubric_path)
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    route_keys: set[tuple[str, str]] = set()
    holdout_mapping: dict[str, str] = {}
    for snapshot in snapshots:
        group_id = str(snapshot["group_id"])
        route_id = str(snapshot["route_id"])
        route_key = (group_id, route_id)
        if route_key in route_keys:
            raise ValueError(f"중복 경로 스냅샷: {group_id}/{route_id}")
        route_keys.add(route_key)
        holdout_group_id = str(snapshot["holdout_group_id"])
        previous_holdout = holdout_mapping.setdefault(group_id, holdout_group_id)
        if previous_holdout != holdout_group_id:
            raise ValueError(f"{group_id}: holdout_group_id가 일관되지 않습니다.")
        groups[group_id].append(snapshot)
    invalid_groups = [
        group_id for group_id, rows in groups.items() if len(rows) < 2
    ]
    if invalid_groups:
        raise ValueError("후보가 1개뿐인 OD가 있습니다: " + ", ".join(invalid_groups[:5]))

    evaluated_at = datetime.now(UTC)
    latest_capture = max(
        datetime.fromisoformat(str(row["captured_at"]).replace("Z", "+00:00"))
        for row in snapshots
    )
    if evaluated_at < latest_capture:
        raise ValueError("현재 시각이 최신 피처 스냅샷 생성시각보다 이릅니다.")
    evaluated_at_text = evaluated_at.isoformat()

    label_rows: list[dict[str, Any]] = []
    distribution: dict[str, Counter[int]] = {
        profile: Counter() for profile in PROFILES
    }
    shared = rubric["shared_situation_criteria"]
    thresholds = rubric["relevance_thresholds"]
    for group_id in sorted(groups):
        group = sorted(groups[group_id], key=lambda row: str(row["route_id"]))
        for profile in PROFILES:
            criteria = _active_criteria(
                group,
                [*rubric["profiles"][profile], *shared],
            )
            scored: list[
                tuple[dict[str, Any], float, list[dict[str, Any]]]
            ] = []
            for snapshot in group:
                score, evidence = _route_score(
                    str(snapshot["route_id"]),
                    criteria,
                )
                scored.append((snapshot, score, evidence))
            minimum = min(item[1] for item in scored)
            maximum = max(item[1] for item in scored)
            for snapshot, score, evidence in scored:
                relevance = _relevance(
                    score,
                    minimum,
                    maximum,
                    thresholds,
                )
                distribution[profile][relevance] += 1
                label_rows.append({
                    "schema_version": EVALUATION_LABEL_SCHEMA_VERSION,
                    "label_kind": EVALUATION_LABEL_ORIGIN,
                    "evaluation_run_id": evaluation_run_id,
                    "evaluation_source": evaluation_source,
                    "rubric_version": rubric["schema_version"],
                    "prompt_hash": rubric_hash,
                    "evaluated_at": evaluated_at_text,
                    "group_id": group_id,
                    "route_id": str(snapshot["route_id"]),
                    "feature_snapshot_hash": str(
                        snapshot["feature_snapshot_hash"]
                    ),
                    "profile": profile,
                    "relevance": relevance,
                    "rationale": _rationale(relevance, evidence),
                })

    labels_output_path.parent.mkdir(parents=True, exist_ok=True)
    labels_output_path.write_text(
        "\n".join(
            json.dumps(
                row,
                ensure_ascii=False,
                separators=(",", ":"),
                allow_nan=False,
            )
            for row in label_rows
        )
        + "\n",
        encoding="utf-8",
    )
    if frozen_features_output_path is not None:
        frozen_features_output_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(features_path, frozen_features_output_path)

    known_counts = Counter()
    for snapshot in snapshots:
        for feature in FEATURE_COLS:
            if snapshot["features"].get(feature) is not None:
                known_counts[feature] += 1
    report = {
        "schema_version": "profile-evaluation-report-v1",
        "evaluation_run_id": evaluation_run_id,
        "evaluation_source": evaluation_source,
        "rubric_version": rubric["schema_version"],
        "rubric_sha256": rubric_hash,
        "evaluated_at": evaluated_at_text,
        "od_count": len(groups),
        "route_count": len(snapshots),
        "profile_count": len(PROFILES),
        "label_count": len(label_rows),
        "label_distribution": {
            profile: {
                str(label): distribution[profile][label]
                for label in range(1, 5)
            }
            for profile in PROFILES
        },
        "known_feature_counts": {
            feature: known_counts[feature] for feature in FEATURE_COLS
        },
        "missing_value_policy": "exclude_from_comparison",
        "auxiliary_features_excluded": list(AUXILIARY_FEATURE_COLS),
        "features_sha256": _sha256(features_path.read_bytes()),
        "labels_sha256": _sha256(labels_output_path.read_bytes()),
    }
    report_output_path.parent.mkdir(parents=True, exist_ok=True)
    report_output_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    return report


def main() -> None:
    parser = argparse.ArgumentParser(
        description="실제 경로 후보의 프로필별 baseline 평가 라벨 생성"
    )
    parser.add_argument("--features", type=Path, required=True)
    parser.add_argument("--labels-output", type=Path, required=True)
    parser.add_argument("--report-output", type=Path, required=True)
    parser.add_argument("--freeze-features-output", type=Path)
    parser.add_argument(
        "--rubric",
        type=Path,
        default=DEFAULT_RUBRIC_PATH,
    )
    parser.add_argument("--evaluation-run-id", required=True)
    parser.add_argument(
        "--evaluation-source",
        default="local:profile-rubric",
    )
    args = parser.parse_args()
    report = generate(
        features_path=args.features,
        labels_output_path=args.labels_output,
        report_output_path=args.report_output,
        frozen_features_output_path=args.freeze_features_output,
        rubric_path=args.rubric,
        evaluation_run_id=args.evaluation_run_id,
        evaluation_source=args.evaluation_source,
    )
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
