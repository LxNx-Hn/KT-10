"""부산 OD 목록에서 모델 학습용 피처 스냅샷과 빈 평가표를 만든다.

실행 전 AI 서버를 띄우고 ODsay/TMAP 키를 설정한다. 이 도구는 경로를
임의 생성하지 않으며, `/labeling/candidates`가 반환한 실제 후보만 기록한다.
"""
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

import httpx

from scoring.train import PROFILES

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


def generate(od_path: Path, output_dir: Path, server_url: str, reviewer_count: int = 9) -> dict:
    od_rows = _read_od_rows(od_path)
    reviewers = _reviewer_ids(reviewer_count)
    feature_rows: list[dict] = []
    sheet_rows: list[dict] = []
    failures: list[dict] = []
    with httpx.Client(timeout=120.0) as client:
        for index, row in enumerate(od_rows, start=1):
            payload = {
                "origin_lat": float(row["origin_lat"]),
                "origin_lng": float(row["origin_lng"]),
                "origin_name": row["origin_name"],
                "dest_lat": float(row["dest_lat"]),
                "dest_lng": float(row["dest_lng"]),
                "dest_name": row["dest_name"],
                "profile": "general",
                "weather": row.get("weather") or "normal",
                "prioritize_weather_safety": False,
                "carry_luggage": (row.get("carry_luggage") or "").lower() in {"1", "true", "y", "yes"},
                "avoid_stairs": (row.get("avoid_stairs") or "").lower() in {"1", "true", "y", "yes"},
                "low_floor_priority": (row.get("low_floor_priority") or "").lower() in {"1", "true", "y", "yes"},
            }
            response = client.post(f"{server_url.rstrip('/')}/labeling/candidates", json=payload)
            if not response.is_success:
                failures.append({"row": index, "status": response.status_code, "detail": response.text[:500]})
                continue
            data = response.json()
            group_id = str(data["group_id"])
            for candidate in data.get("candidates") or []:
                feature_rows.append({
                    "group_id": group_id,
                    "route_id": candidate["route_id"],
                    "features": candidate["features"],
                })
                for profile in PROFILES:
                    for reviewer_id in reviewers:
                        sheet_rows.append({
                            "reviewer_id": reviewer_id,
                            "group_id": group_id,
                            "route_id": candidate["route_id"],
                            "profile": profile,
                            "relevance": "",
                            "notes": "",
                            "origin": row["origin_name"],
                            "destination": row["dest_name"],
                            "route_summary": candidate.get("summary") or "",
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
    parser.add_argument("--server-url", default="http://localhost:8001")
    parser.add_argument("--reviewer-count", type=int, default=9)
    args = parser.parse_args()
    print(json.dumps(generate(
        args.od_file, args.output_dir, args.server_url, args.reviewer_count,
    ), ensure_ascii=False))


if __name__ == "__main__":
    main()
