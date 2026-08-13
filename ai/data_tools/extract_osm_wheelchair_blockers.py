"""Geofabrik PBF에서 부산의 명시적 `highway=steps + ramp=no`를 추출한다."""
from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from shapely.geometry import LineString, shape
from shapely.ops import unary_union

from features.wheelchair_blockers import CATALOG_SCHEMA_VERSION

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PBF = (
    ROOT / "ai" / "data" / "cache" / "osmnx" / "source"
    / "south-korea-latest.osm.pbf"
)
DEFAULT_BOUNDARY = ROOT / "data" / "da" / "colab" / "hangjeongdong_부산광역시.geojson"
DEFAULT_OUTPUT = ROOT / "data" / "raw" / "busan_osm_steps_ramp_no_20260724.geojson"
DEFAULT_SOURCE_METADATA = (
    ROOT / "ai" / "data" / "cache" / "osmnx" / "busan-walk.metadata.json"
)


def _boundary(path: Path):
    payload = json.loads(path.read_text(encoding="utf-8"))
    features = payload.get("features")
    if not isinstance(features, list) or not features:
        raise ValueError("부산 경계 GeoJSON이 비어 있습니다.")
    geometries = [
        shape(feature["geometry"])
        for feature in features
        if isinstance(feature, dict) and isinstance(feature.get("geometry"), dict)
    ]
    if not geometries:
        raise ValueError("부산 경계 geometry가 없습니다.")
    return unary_union(geometries)


def extract(pbf_path: Path, boundary_path: Path) -> list[dict]:
    try:
        import osmium
    except ImportError as exc:
        raise RuntimeError(
            "PBF 갱신에는 개발 의존성 osmium이 필요합니다."
        ) from exc

    busan = _boundary(boundary_path)

    class Handler(osmium.SimpleHandler):
        def __init__(self):
            super().__init__()
            self.features: list[dict] = []

        def way(self, way) -> None:
            tags = dict(way.tags)
            if tags.get("highway") != "steps" or tags.get("ramp") != "no":
                return
            coordinates = []
            for node in way.nodes:
                try:
                    coordinates.append([node.lon, node.lat])
                except osmium.InvalidLocationError:
                    return
            if len(coordinates) < 2:
                return
            line = LineString(coordinates)
            if not busan.intersects(line):
                return
            properties = {
                "osmWayId": int(way.id),
                "highway": "steps",
                "ramp": "no",
                "source": "OpenStreetMap",
                "license": "ODbL 1.0",
            }
            step_count = tags.get("step_count")
            if isinstance(step_count, str) and step_count.isdecimal():
                properties["stepCount"] = int(step_count)
            self.features.append({
                "type": "Feature",
                "properties": properties,
                "geometry": {
                    "type": "LineString",
                    "coordinates": coordinates,
                },
            })

    handler = Handler()
    handler.apply_file(str(pbf_path), locations=True)
    return sorted(
        handler.features,
        key=lambda feature: feature["properties"]["osmWayId"],
    )


def _write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    try:
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pbf", type=Path, default=DEFAULT_PBF)
    parser.add_argument("--boundary", type=Path, default=DEFAULT_BOUNDARY)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--source-metadata",
        type=Path,
        default=DEFAULT_SOURCE_METADATA,
    )
    args = parser.parse_args()
    metadata = json.loads(args.source_metadata.read_text(encoding="utf-8"))
    features = extract(args.pbf, args.boundary)
    payload = {
        "type": "FeatureCollection",
        "schemaVersion": CATALOG_SCHEMA_VERSION,
        "generatedAt": datetime.now(UTC).isoformat(),
        "source": {
            "name": "OpenStreetMap via Geofabrik",
            "url": metadata.get("source_url"),
            "md5": metadata.get("source_md5"),
            "license": "ODbL 1.0",
            "localSnapshotPreparedAt": metadata.get("created_at"),
        },
        "filter": {"highway": "steps", "ramp": "no"},
        "featureCount": len(features),
        "features": features,
    }
    if not features:
        raise SystemExit("명시적 steps+ramp=no feature가 없어 출력하지 않습니다.")
    _write(args.output, payload)
    print(json.dumps({
        "output": str(args.output),
        "featureCount": len(features),
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
