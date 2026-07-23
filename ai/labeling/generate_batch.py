"""부산 OD 목록에서 모델 학습용 피처 스냅샷과 빈 평가표를 만든다.

실행 전 AI·백엔드 서버를 띄우고 경로·건물 키를 설정한다. 이 도구는
경로를 임의 생성하지 않으며, 백엔드가 시간별 건물 그늘까지 결합한
`/api/routes/labeling-candidates` 응답만 기록한다.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
from pathlib import Path

import httpx

from scoring.snapshots import validate_live_feature_snapshot
from scoring.train import FEATURE_COLS, PROFILES

REQUIRED_OD_COLUMNS = {
    "origin_name", "origin_lat", "origin_lng",
    "dest_name", "dest_lat", "dest_lng",
}


def _read_od_rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        missing = REQUIRED_OD_COLUMNS.difference(reader.fieldnames or [])
        if missing:
            raise ValueError(f"OD CSV 컬럼 누락: {', '.join(sorted(missing))}")
        rows = list(reader)
    if not rows:
        raise ValueError("OD CSV가 비어 있습니다.")
    return rows


def _reviewer_ids(reviewer_count: int) -> list[str]:
    if reviewer_count < 9:
        raise ValueError("초기 학습에는 최소 9명의 평가자가 필요합니다.")
    return [f"reviewer_{number:02d}" for number in range(1, reviewer_count + 1)]


def generate(
    od_path: Path,
    output_dir: Path,
    server_url: str,
    reviewer_count: int = 9,
    api_token: str = "",
) -> dict:
    if len(api_token) < 32:
        raise ValueError(
            "LABELING_API_TOKEN은 32자 이상이어야 하며 채팅이나 출력에 노출하면 안 됩니다."
        )
    od_rows = _read_od_rows(od_path)
    reviewers = _reviewer_ids(reviewer_count)
    feature_rows: list[dict] = []
    sheet_rows: list[dict] = []
    failures: list[dict] = []
    with httpx.Client(timeout=120.0) as client:
        for index, row in enumerate(od_rows, start=1):
            payload = {
                "origin": {
                    "id": f"batch-origin-{index}",
                    "name": row["origin_name"],
                    "lat": float(row["origin_lat"]),
                    "lng": float(row["origin_lng"]),
                },
                "destination": {
                    "id": f"batch-destination-{index}",
                    "name": row["dest_name"],
                    "lat": float(row["dest_lat"]),
                    "lng": float(row["dest_lng"]),
                },
                "profile": "general",
                "weatherScenario": row.get("weather") or "normal",
                "options": {
                    "carryLuggage": (row.get("carry_luggage") or "").lower() in {"1", "true", "y", "yes"},
                    "stroller": (row.get("stroller") or "").lower() in {"1", "true", "y", "yes"},
                    "shadePriority": (row.get("shade_priority") or "").lower() in {"1", "true", "y", "yes"},
                    "minimizeTransfers": (row.get("minimize_transfers") or "").lower() in {"1", "true", "y", "yes"},
                    "avoidStairs": (row.get("avoid_stairs") or "").lower() in {"1", "true", "y", "yes"},
                    "lowFloorPriority": (row.get("low_floor_priority") or "").lower() in {"1", "true", "y", "yes"},
                    **(
                        {"departureAt": row["departure_at"].strip()}
                        if row.get("departure_at", "").strip()
                        else {}
                    ),
                },
                "topN": 10,
            }
            response = client.post(
                f"{server_url.rstrip('/')}/api/routes/labeling-candidates",
                json=payload,
                headers={"X-Labeling-Token": api_token},
            )
            if not response.is_success:
                failures.append({"row": index, "status": response.status_code, "detail": response.text[:500]})
                continue
            data = response.json()
            group_id = str(data["group_id"])
            for candidate in data.get("candidates") or []:
                snapshot = candidate.get("feature_snapshot")
                if not isinstance(snapshot, dict):
                    raise RuntimeError(
                        "후보 API가 고정 feature_snapshot을 반환하지 않았습니다."
                    )
                validate_live_feature_snapshot(snapshot, FEATURE_COLS)
                if (
                    str(snapshot["group_id"]) != group_id
                    or str(snapshot["route_id"]) != str(candidate["route_id"])
                ):
                    raise RuntimeError(
                        "후보 식별자와 feature_snapshot 식별자가 일치하지 않습니다."
                    )
                feature_rows.append(snapshot)
                trait_labels = (candidate.get("trait_labels") or {}).get("labels") or []
                for profile in PROFILES:
                    for reviewer_id in reviewers:
                        sheet_rows.append({
                            "reviewer_id": reviewer_id,
                            "group_id": group_id,
                            "route_id": candidate["route_id"],
                            "feature_snapshot_hash": snapshot["feature_snapshot_hash"],
                            "profile": profile,
                            "relevance": "",
                            "notes": "",
                            "origin": row["origin_name"],
                            "destination": row["dest_name"],
                            "route_summary": candidate.get("summary") or "",
                            "route_traits": " · ".join(
                                str(label.get("display_label"))
                                for label in trait_labels
                                if label.get("display_label")
                            ),
                            "duration_min": candidate.get("duration_min"),
                            "distance_m": candidate.get("distance_m"),
                            "sources": "+".join(candidate.get("sources") or []),
                        })
    if not feature_rows:
        raise RuntimeError(f"기록할 수 있는 실제 후보가 없습니다. 실패: {failures}")

    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "route_features.jsonl").write_text(
        "\n".join(json.dumps(item, ensure_ascii=False, separators=(",", ":")) for item in feature_rows) + "\n",
        encoding="utf-8",
    )
    with (output_dir / "labeling_sheet.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(sheet_rows[0]))
        writer.writeheader()
        writer.writerows(sheet_rows)
    (output_dir / "generation_report.json").write_text(
        json.dumps({
            "od_rows": len(od_rows), "candidates": len(feature_rows),
            "reviewer_count": len(reviewers), "profiles": PROFILES, "failures": failures,
        }, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return {"candidates": len(feature_rows), "label_rows": len(sheet_rows), "failures": len(failures)}


def main() -> None:
    parser = argparse.ArgumentParser(description="초기 9인 라벨링 패키지 생성")
    parser.add_argument("--od-file", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, default=Path("ai/data/training/generated/initial_batch"))
    parser.add_argument("--server-url", default="http://localhost:8002")
    parser.add_argument("--reviewer-count", type=int, default=9)
    parser.add_argument(
        "--api-token",
        default=os.getenv("LABELING_API_TOKEN", ""),
        help="기본값은 LABELING_API_TOKEN 환경변수입니다.",
    )
    args = parser.parse_args()
    print(json.dumps(generate(
        args.od_file,
        args.output_dir,
        args.server_url,
        args.reviewer_count,
        args.api_token,
    ), ensure_ascii=False))


if __name__ == "__main__":
    main()
