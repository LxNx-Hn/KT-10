"""공식 엘리베이터 동선 출구에 OSM 출입구 좌표를 결합한다.

부산교통공사 원본은 접근 가능한 출구번호와 내부 이동경로를 제공하지만
좌표는 제공하지 않는다. 이 스크립트는 그 공식 출구 집합만 대상으로
OpenStreetMap ``railway=subway_entrance`` 노드 좌표를 결합한다. 공식 원본에
없는 출구를 접근 가능하다고 추론하지 않는다.
"""
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
import re
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
AI_ROOT = ROOT / "ai"
RAW_DIR = ROOT / "data" / "raw"
OUTPUT = RAW_DIR / "busan_subway_accessible_exit_coordinates_20260813.csv"
OVERPASS_URLS = (
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
)
RETRIEVED_AT = "2026-08-13"


def _entrances() -> dict[tuple[str, str], list[tuple[float, float, int]]]:
    query = (
        "[out:json];"
        "node(34.7,128.7,35.5,129.4)[railway=subway_entrance];"
        "out body;"
    )
    last_error: Exception | None = None
    elements = []
    for url in OVERPASS_URLS:
        request = Request(
            url,
            data=urlencode({"data": query}).encode("ascii"),
            headers={"User-Agent": "KT10-accessibility-data/1.0"},
        )
        try:
            with urlopen(request, timeout=90) as response:  # noqa: S310 - fixed HTTPS URLs
                elements = json.load(response).get("elements", [])
            break
        except (OSError, TimeoutError, ValueError) as exc:
            last_error = exc
    else:
        raise RuntimeError("Overpass 출입구 좌표를 가져오지 못했습니다.") from last_error
    result: dict[tuple[str, str], list[tuple[float, float, int]]] = {}
    for node in elements:
        tags = node.get("tags") if isinstance(node, dict) else None
        if not isinstance(tags, dict):
            continue
        description = tags.get("description:ko") or tags.get("description")
        exit_no = str(tags.get("ref") or "")
        matched = re.match(r"(.+?)역\s*(\d+)번", str(description or ""))
        if not matched or not exit_no.isdigit():
            continue
        key = (re.sub(r"\s+", "", matched.group(1)), exit_no)
        coordinate = (float(node["lat"]), float(node["lon"]), int(node["id"]))
        if coordinate not in result.setdefault(key, []):
            result[key].append(coordinate)
    return result


def build_rows() -> tuple[list[dict[str, object]], list[tuple[int, str, str]]]:
    import sys

    sys.path.insert(0, str(AI_ROOT))
    from preprocessing.load_layers import (  # noqa: PLC0415
        _STATION_ELEVATOR_ALIASES,
        _accessible_elevator_exits,
        _station_base_name,
    )

    source = pd.read_csv(
        RAW_DIR / "busan_subway_elevator_routes_20251231.csv",
        encoding="utf-8-sig",
    )
    source["station_line"] = pd.to_numeric(source["호선"]).astype(int)
    source["station_name"] = source["역명"].map(_station_base_name)
    source["station_name"] = [
        _STATION_ELEVATOR_ALIASES.get(
            (line, re.sub(rf"^{line}", "", name)),
            re.sub(rf"^{line}", "", name),
        )
        for line, name in zip(source["station_line"], source["station_name"])
    ]
    entrances = _entrances()
    rows: list[dict[str, object]] = []
    missing: list[tuple[int, str, str]] = []
    for (line, station), group in source.groupby(
        ["station_line", "station_name"],
        sort=True,
    ):
        for exit_no in sorted(_accessible_elevator_exits(group), key=int):
            coordinates = entrances.get((re.sub(r"\s+", "", station), exit_no))
            if not coordinates:
                missing.append((int(line), station, exit_no))
                continue
            for lat, lng, node_id in sorted(coordinates, key=lambda item: item[2]):
                rows.append({
                    "station_line": int(line),
                    "station_name": station,
                    "exit_no": exit_no,
                    "lat": f"{lat:.7f}",
                    "lng": f"{lng:.7f}",
                    "osm_node_id": node_id,
                    "coordinate_source": "OpenStreetMap",
                    "coordinate_license": "ODbL 1.0",
                    "coordinate_retrieved_at": RETRIEVED_AT,
                    "accessibility_evidence_source": (
                        "부산교통공사 도시철도 엘리베이터 이동경로 2025-12-31"
                    ),
                })
    return rows, missing


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()
    rows, missing = build_rows()
    if not rows:
        raise RuntimeError("결합된 접근 가능 출구 좌표가 없습니다.")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    print(f"wrote={len(rows)} missing={len(missing)} output={args.output}")
    for item in missing:
        print(f"missing line={item[0]} station={item[1]} exit={item[2]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
