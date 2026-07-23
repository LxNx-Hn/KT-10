"""고정된 실제 후보 스냅샷에서 LLM judge 입력용 빈 평가표를 만든다."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from scoring.snapshots import validate_live_feature_snapshot
from scoring.train import FEATURE_COLS, PROFILES
from scoring.judge_baseline import JUDGE_LABEL_SCHEMA_VERSION, JUDGE_LABEL_ORIGIN


def prepare(
    *,
    features_path: Path,
    output_path: Path,
    judge_run_id: str,
    judge_source: str,
    rubric_version: str,
    prompt_path: Path,
) -> dict:
    if not judge_run_id.strip() or not judge_source.strip() or not rubric_version.strip():
        raise ValueError("judge_run_id, judge_source, rubric_version은 비어 있을 수 없습니다.")
    prompt_bytes = prompt_path.read_bytes()
    if not prompt_bytes:
        raise ValueError("평가 프롬프트 파일이 비어 있습니다.")
    prompt_hash = hashlib.sha256(prompt_bytes).hexdigest()

    snapshots = []
    for line_number, line in enumerate(
        features_path.read_text(encoding="utf-8").splitlines(),
        start=1,
    ):
        if not line.strip():
            continue
        try:
            snapshot = json.loads(line)
            validate_live_feature_snapshot(snapshot, FEATURE_COLS)
        except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"피처 스냅샷 {line_number}행: {exc}") from exc
        snapshots.append(snapshot)
    if not snapshots:
        raise ValueError("피처 스냅샷이 비어 있습니다.")

    rows = []
    for snapshot in snapshots:
        for profile in PROFILES:
            rows.append({
                "schema_version": JUDGE_LABEL_SCHEMA_VERSION,
                "label_kind": JUDGE_LABEL_ORIGIN,
                "judge_run_id": judge_run_id,
                "judge_source": judge_source,
                "rubric_version": rubric_version,
                "prompt_hash": prompt_hash,
                "evaluated_at": None,
                "group_id": snapshot["group_id"],
                "route_id": snapshot["route_id"],
                "feature_snapshot_hash": snapshot["feature_snapshot_hash"],
                "profile": profile,
                "relevance": None,
                "rationale": None,
            })
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        "\n".join(
            json.dumps(row, ensure_ascii=False, separators=(",", ":"))
            for row in rows
        )
        + "\n",
        encoding="utf-8",
    )
    return {
        "snapshot_count": len(snapshots),
        "profile_count": len(PROFILES),
        "label_row_count": len(rows),
        "prompt_hash": prompt_hash,
        "output": str(output_path),
        "ready_for_training": False,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="실제 후보 스냅샷용 LLM judge 빈 평가표 생성"
    )
    parser.add_argument("--features", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--judge-run-id", required=True)
    parser.add_argument("--judge-source", required=True)
    parser.add_argument("--rubric-version", required=True)
    parser.add_argument("--prompt-file", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(prepare(
        features_path=args.features,
        output_path=args.output,
        judge_run_id=args.judge_run_id,
        judge_source=args.judge_source,
        rubric_version=args.rubric_version,
        prompt_path=args.prompt_file,
    ), ensure_ascii=False))


if __name__ == "__main__":
    main()
