"""부산 공개 장소 좌표에서 재현 가능한 학습용 합성 OD 카탈로그를 만든다.

이 도구는 사용자 이동기록을 사용하지 않는다. 부산 동백전 공개 가맹점 좌표를
행정경계로 검증한 뒤 구·군, 직선거리 구간, 이동 상황을 균형 있게 표본화한다.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import geopandas as gpd
import numpy as np
import pandas as pd
from sklearn.cluster import KMeans
from sklearn.neighbors import BallTree

GENERATOR_VERSION = "busan-public-poi-od-v1"
EARTH_RADIUS_KM = 6371.0088

REQUIRED_SOURCE_COLUMNS = {"가맹점 명", "주소", "위도", "경도"}
REQUIRED_BOUNDARY_COLUMNS = {"sggnm", "geometry"}


@dataclass(frozen=True)
class DistanceBand:
    id: str
    minimum_km: float
    maximum_km: float
    share: float
    require_cross_district: bool = False


@dataclass(frozen=True)
class Situation:
    id: str
    weather: str
    departure_at: str
    carry_luggage: bool = False
    stroller: bool = False
    shade_priority: bool = False
    minimize_transfers: bool = False
    avoid_stairs: bool = False
    low_floor_priority: bool = False


DISTANCE_BANDS = (
    DistanceBand("short_1_5_to_4km", 1.5, 4.0, 0.35),
    DistanceBand("medium_4_to_12km", 4.0, 12.0, 0.45),
    DistanceBand("long_12_to_25km", 12.0, 25.0, 0.20, True),
)

SITUATIONS = (
    Situation("balanced_morning", "normal", "2026-08-03T08:30:00+09:00"),
    Situation(
        "heat_shade_midday",
        "heatwave",
        "2026-08-03T14:30:00+09:00",
        shade_priority=True,
    ),
    Situation("coldwave_morning", "coldwave", "2026-12-07T08:30:00+09:00"),
    Situation(
        "rain_evening",
        "rain",
        "2026-08-03T17:30:00+09:00",
        minimize_transfers=True,
    ),
    Situation("bad_air_midday", "dust", "2026-08-03T12:30:00+09:00"),
    Situation(
        "luggage_midday",
        "normal",
        "2026-08-03T12:30:00+09:00",
        carry_luggage=True,
        minimize_transfers=True,
    ),
    Situation(
        "stroller_daytime",
        "normal",
        "2026-08-03T11:00:00+09:00",
        stroller=True,
        avoid_stairs=True,
        low_floor_priority=True,
    ),
    Situation(
        "transfer_min_evening",
        "normal",
        "2026-08-03T17:30:00+09:00",
        minimize_transfers=True,
    ),
)

OUTPUT_COLUMNS = (
    "od_id",
    "origin_name",
    "origin_lat",
    "origin_lng",
    "origin_district",
    "dest_name",
    "dest_lat",
    "dest_lng",
    "dest_district",
    "straight_line_km",
    "distance_band",
    "situation_id",
    "weather",
    "departure_at",
    "carry_luggage",
    "stroller",
    "shade_priority",
    "minimize_transfers",
    "avoid_stairs",
    "low_floor_priority",
    "source_kind",
)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _allocate_counts(total: int, shares: list[float]) -> list[int]:
    if total <= 0:
        raise ValueError("OD 개수는 1개 이상이어야 합니다.")
    if not shares or any(share <= 0 for share in shares):
        raise ValueError("표본 비율은 모두 양수여야 합니다.")
    normalized = np.asarray(shares, dtype=float) / sum(shares)
    raw = normalized * total
    counts = np.floor(raw).astype(int)
    remainder = total - int(counts.sum())
    order = np.argsort(-(raw - counts), kind="stable")
    for index in order[:remainder]:
        counts[index] += 1
    return counts.tolist()


def _balanced_values(values: list[str], total: int, rng: np.random.Generator) -> list[str]:
    counts = _allocate_counts(total, [1.0] * len(values))
    result = [
        value
        for value, count in zip(values, counts, strict=True)
        for _ in range(count)
    ]
    rng.shuffle(result)
    return result


def _weighted_values(
    bands: tuple[DistanceBand, ...],
    total: int,
    rng: np.random.Generator,
) -> list[DistanceBand]:
    counts = _allocate_counts(total, [band.share for band in bands])
    result = [
        band
        for band, count in zip(bands, counts, strict=True)
        for _ in range(count)
    ]
    rng.shuffle(result)
    return result


def load_public_pois(source_path: Path, boundary_path: Path) -> pd.DataFrame:
    """공개 장소를 부산 행정경계로 검증하고 좌표 중복을 제거한다."""
    source = pd.read_csv(source_path, encoding="utf-8-sig")
    missing = REQUIRED_SOURCE_COLUMNS.difference(source.columns)
    if missing:
        raise ValueError("장소 원본 컬럼 누락: " + ", ".join(sorted(missing)))
    source = source.copy()
    source["위도"] = pd.to_numeric(source["위도"], errors="coerce")
    source["경도"] = pd.to_numeric(source["경도"], errors="coerce")
    source["가맹점 명"] = source["가맹점 명"].fillna("").astype(str).str.strip()
    source = source[
        source["위도"].between(-90, 90)
        & source["경도"].between(-180, 180)
        & source["가맹점 명"].ne("")
    ].copy()
    if source.empty:
        raise ValueError("유효한 장소명과 좌표가 없습니다.")

    boundaries = gpd.read_file(boundary_path)
    missing_boundary = REQUIRED_BOUNDARY_COLUMNS.difference(boundaries.columns)
    if missing_boundary:
        raise ValueError(
            "행정경계 컬럼 누락: " + ", ".join(sorted(missing_boundary))
        )
    if boundaries.crs is None:
        raise ValueError("행정경계 CRS가 없습니다.")
    boundaries = boundaries.to_crs("EPSG:4326")[["sggnm", "geometry"]]

    points = gpd.GeoDataFrame(
        source,
        geometry=gpd.points_from_xy(source["경도"], source["위도"]),
        crs="EPSG:4326",
    )
    joined = gpd.sjoin(points, boundaries, how="inner", predicate="within")
    joined = (
        joined.sort_values(["sggnm", "가맹점 명", "위도", "경도"])
        .drop_duplicates(["위도", "경도"], keep="first")
        .rename(columns={
            "가맹점 명": "name",
            "위도": "lat",
            "경도": "lng",
            "sggnm": "district",
        })
    )
    result = joined[["name", "lat", "lng", "district"]].reset_index(drop=True)
    if result.empty:
        raise ValueError("부산 행정경계 안의 공개 장소가 없습니다.")
    if result["district"].isna().any():
        raise ValueError("행정구역이 확인되지 않은 장소가 포함되었습니다.")
    return result


def select_spatial_anchors(
    pois: pd.DataFrame,
    *,
    anchors_per_district: int,
    seed: int,
) -> pd.DataFrame:
    """각 구·군의 장소 분포를 대표하는 실제 POI를 결정적으로 선택한다."""
    if anchors_per_district < 2:
        raise ValueError("구·군별 앵커는 최소 2개여야 합니다.")
    required = {"name", "lat", "lng", "district"}
    missing = required.difference(pois.columns)
    if missing:
        raise ValueError("장소 풀 컬럼 누락: " + ", ".join(sorted(missing)))
    anchors = []
    for district, district_rows in pois.groupby("district", sort=True):
        district_rows = district_rows.sort_values(
            ["lat", "lng", "name"]
        ).reset_index(drop=True)
        if len(district_rows) < anchors_per_district:
            raise ValueError(
                f"{district}: 앵커 후보가 {anchors_per_district}개보다 적습니다."
            )
        mean_latitude = float(district_rows["lat"].mean())
        projected = np.column_stack([
            district_rows["lng"].to_numpy(dtype=float)
            * math.cos(math.radians(mean_latitude)),
            district_rows["lat"].to_numpy(dtype=float),
        ])
        district_seed = int.from_bytes(
            hashlib.sha256(f"{seed}:{district}".encode("utf-8")).digest()[:4],
            "big",
        )
        model = KMeans(
            n_clusters=anchors_per_district,
            random_state=district_seed,
            n_init=10,
        ).fit(projected)
        selected_indices: set[int] = set()
        for center in sorted(
            model.cluster_centers_.tolist(),
            key=lambda value: (value[1], value[0]),
        ):
            distances = np.square(projected - np.asarray(center)).sum(axis=1)
            for candidate_index in np.argsort(distances, kind="stable"):
                normalized_index = int(candidate_index)
                if normalized_index not in selected_indices:
                    selected_indices.add(normalized_index)
                    break
        if len(selected_indices) != anchors_per_district:
            raise RuntimeError(f"{district}: 공간 앵커 수가 일치하지 않습니다.")
        anchors.append(district_rows.iloc[sorted(selected_indices)])
    result = (
        pd.concat(anchors, ignore_index=True)
        .sort_values(["district", "lat", "lng", "name"])
        .reset_index(drop=True)
    )
    if result.duplicated(["lat", "lng"]).any():
        raise RuntimeError("선택된 공간 앵커 좌표가 중복되었습니다.")
    return result


def _format_bool(value: bool) -> str:
    return "true" if value else "false"


def _od_id(origin: pd.Series, destination: pd.Series, situation_id: str) -> str:
    stable = "|".join([
        f"{float(origin['lat']):.7f}",
        f"{float(origin['lng']):.7f}",
        f"{float(destination['lat']):.7f}",
        f"{float(destination['lng']):.7f}",
        situation_id,
    ])
    return "od-" + hashlib.sha256(stable.encode("utf-8")).hexdigest()[:20]


def generate_catalog_rows(
    pois: pd.DataFrame,
    *,
    count: int,
    seed: int,
    distance_bands: tuple[DistanceBand, ...] = DISTANCE_BANDS,
    situations: tuple[Situation, ...] = SITUATIONS,
) -> list[dict[str, Any]]:
    """주어진 장소 풀에서 중복 없는 방향성 OD를 생성한다."""
    required = {"name", "lat", "lng", "district"}
    missing = required.difference(pois.columns)
    if missing:
        raise ValueError("장소 풀 컬럼 누락: " + ", ".join(sorted(missing)))
    if pois.empty or pois["district"].nunique() < 2:
        raise ValueError("서로 다른 행정구역의 장소가 필요합니다.")
    if len(pois) < 2:
        raise ValueError("장소가 최소 2개 필요합니다.")

    frame = pois.copy().reset_index(drop=True)
    frame["lat"] = pd.to_numeric(frame["lat"], errors="raise")
    frame["lng"] = pd.to_numeric(frame["lng"], errors="raise")
    if not np.isfinite(frame[["lat", "lng"]].to_numpy(dtype=float)).all():
        raise ValueError("장소 좌표에는 유한한 숫자만 허용됩니다.")
    if frame.duplicated(["lat", "lng"]).any():
        raise ValueError("장소 풀에 중복 좌표가 있습니다.")

    rng = np.random.default_rng(seed)
    districts = sorted(frame["district"].astype(str).unique().tolist())
    origin_districts = _balanced_values(districts, count, rng)
    selected_bands = _weighted_values(distance_bands, count, rng)
    selected_situations = _balanced_values(
        [situation.id for situation in situations],
        count,
        rng,
    )
    situation_by_id = {situation.id: situation for situation in situations}
    district_indices = {
        district: frame.index[frame["district"].astype(str) == district].to_numpy()
        for district in districts
    }
    coordinates_rad = np.radians(frame[["lat", "lng"]].to_numpy(dtype=float))
    latitudes = frame["lat"].to_numpy(dtype=float)
    longitudes = frame["lng"].to_numpy(dtype=float)
    district_values = frame["district"].astype(str).to_numpy()
    tree = BallTree(coordinates_rad, metric="haversine")
    used_pairs: set[tuple[float, float, float, float]] = set()
    rows: list[dict[str, Any]] = []

    for row_index, (origin_district, band, situation_id) in enumerate(
        zip(origin_districts, selected_bands, selected_situations, strict=True),
        start=1,
    ):
        origin_pool = district_indices[origin_district]
        selected: tuple[pd.Series, pd.Series, float] | None = None
        for origin_index in rng.permutation(origin_pool):
            neighbor_indices, neighbor_distances = tree.query_radius(
                coordinates_rad[[origin_index]],
                r=band.maximum_km / EARTH_RADIUS_KM,
                return_distance=True,
                sort_results=False,
            )
            candidate_indices = neighbor_indices[0]
            candidate_km = neighbor_distances[0] * EARTH_RADIUS_KM
            allowed = (
                (candidate_km >= band.minimum_km)
                & (candidate_km < band.maximum_km)
            )
            if band.require_cross_district:
                allowed &= district_values[candidate_indices] != origin_district
            eligible_positions = np.flatnonzero(allowed)
            if not len(eligible_positions):
                continue
            selected_destination: tuple[int, float] | None = None
            checks = min(32, len(eligible_positions))
            for position in rng.choice(
                eligible_positions,
                size=checks,
                replace=False,
            ):
                destination_index = int(candidate_indices[position])
                pair_key = (
                    round(float(latitudes[origin_index]), 7),
                    round(float(longitudes[origin_index]), 7),
                    round(float(latitudes[destination_index]), 7),
                    round(float(longitudes[destination_index]), 7),
                )
                if pair_key not in used_pairs:
                    selected_destination = (
                        destination_index,
                        float(candidate_km[position]),
                    )
                    break
            if selected_destination is None:
                continue
            destination_index, distance_km = selected_destination
            selected = (
                frame.iloc[int(origin_index)],
                frame.iloc[destination_index],
                distance_km,
            )
            break
        if selected is None:
            raise RuntimeError(
                f"{row_index}번째 OD를 만들 수 없습니다: "
                f"{origin_district}/{band.id}"
            )

        origin, destination, distance_km = selected
        pair_key = (
            round(float(origin["lat"]), 7),
            round(float(origin["lng"]), 7),
            round(float(destination["lat"]), 7),
            round(float(destination["lng"]), 7),
        )
        used_pairs.add(pair_key)
        situation = situation_by_id[situation_id]
        rows.append({
            "od_id": _od_id(origin, destination, situation.id),
            "origin_name": f"{origin['name']} ({origin['district']})",
            "origin_lat": round(float(origin["lat"]), 7),
            "origin_lng": round(float(origin["lng"]), 7),
            "origin_district": str(origin["district"]),
            "dest_name": f"{destination['name']} ({destination['district']})",
            "dest_lat": round(float(destination["lat"]), 7),
            "dest_lng": round(float(destination["lng"]), 7),
            "dest_district": str(destination["district"]),
            "straight_line_km": round(distance_km, 4),
            "distance_band": band.id,
            "situation_id": situation.id,
            "weather": situation.weather,
            "departure_at": situation.departure_at,
            "carry_luggage": _format_bool(situation.carry_luggage),
            "stroller": _format_bool(situation.stroller),
            "shade_priority": _format_bool(situation.shade_priority),
            "minimize_transfers": _format_bool(situation.minimize_transfers),
            "avoid_stairs": _format_bool(situation.avoid_stairs),
            "low_floor_priority": _format_bool(situation.low_floor_priority),
            "source_kind": "synthetic_od_from_public_poi",
        })

    if len(rows) != count:
        raise RuntimeError(f"OD 생성 수 불일치: 예상 {count}, 실제 {len(rows)}")
    if len({row["od_id"] for row in rows}) != count:
        raise RuntimeError("OD 식별자가 중복되었습니다.")
    return rows


def write_catalog(
    *,
    source_path: Path,
    boundary_path: Path,
    output_path: Path,
    metadata_path: Path,
    count: int,
    seed: int,
    anchors_per_district: int = 20,
) -> dict[str, Any]:
    pois = load_public_pois(source_path, boundary_path)
    anchors = select_spatial_anchors(
        pois,
        anchors_per_district=anchors_per_district,
        seed=seed,
    )
    rows = generate_catalog_rows(anchors, count=count, seed=seed)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(OUTPUT_COLUMNS))
        writer.writeheader()
        writer.writerows(rows)

    distances = [float(row["straight_line_km"]) for row in rows]
    metadata = {
        "schema_version": "synthetic-od-catalog-v1",
        "generator_version": GENERATOR_VERSION,
        "purpose": "프로필별 경로 순위 모델의 후보 수집용 합성 OD",
        "contains_user_trip_history": False,
        "coordinate_crs": "EPSG:4326",
        "seed": seed,
        "od_count": len(rows),
        "unique_directional_od_count": len({
            (
                row["origin_lat"],
                row["origin_lng"],
                row["dest_lat"],
                row["dest_lng"],
            )
            for row in rows
        }),
        "public_poi_count_after_boundary_and_coordinate_dedup": len(pois),
        "anchor_count": len(anchors),
        "anchors_per_district": anchors_per_district,
        "unique_endpoint_count": len({
            (row["origin_lat"], row["origin_lng"])
            for row in rows
        } | {
            (row["dest_lat"], row["dest_lng"])
            for row in rows
        }),
        "source": {
            "path": source_path.as_posix(),
            "sha256": _sha256_file(source_path),
        },
        "boundary": {
            "path": boundary_path.as_posix(),
            "sha256": _sha256_file(boundary_path),
        },
        "origin_district_counts": dict(sorted(Counter(
            str(row["origin_district"]) for row in rows
        ).items())),
        "destination_district_counts": dict(sorted(Counter(
            str(row["dest_district"]) for row in rows
        ).items())),
        "distance_band_counts": dict(sorted(Counter(
            str(row["distance_band"]) for row in rows
        ).items())),
        "situation_counts": dict(sorted(Counter(
            str(row["situation_id"]) for row in rows
        ).items())),
        "straight_line_km": {
            "minimum": min(distances),
            "median": round(float(np.median(distances)), 4),
            "maximum": max(distances),
        },
        "sampling_contract": {
            "distance_bands": [
                {
                    "id": band.id,
                    "minimum_km_inclusive": band.minimum_km,
                    "maximum_km_exclusive": band.maximum_km,
                    "share": band.share,
                    "require_cross_district": band.require_cross_district,
                }
                for band in DISTANCE_BANDS
            ],
            "situations": [
                {
                    key: value
                    for key, value in situation.__dict__.items()
                }
                for situation in SITUATIONS
            ],
        },
    }
    metadata_path.parent.mkdir(parents=True, exist_ok=True)
    metadata_path.write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return metadata


def _default_source() -> Path:
    matches = [
        path
        for path in Path("data/raw").glob("*.csv")
        if path.stat().st_size > 10_000_000
    ]
    if len(matches) != 1:
        raise ValueError(
            "대용량 장소 CSV를 하나로 식별하지 못했습니다. --source를 지정하세요."
        )
    return matches[0]


def main() -> None:
    parser = argparse.ArgumentParser(
        description="부산 공개 장소 기반 합성 OD 카탈로그 생성"
    )
    parser.add_argument("--source", type=Path)
    parser.add_argument(
        "--boundary",
        type=Path,
        default=Path("data/da/colab/hangjeongdong_부산광역시.geojson"),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("ai/data/training/od_800.csv"),
    )
    parser.add_argument(
        "--metadata",
        type=Path,
        default=Path("ai/data/training/od_800.metadata.json"),
    )
    parser.add_argument("--count", type=int, default=800)
    parser.add_argument("--seed", type=int, default=20260725)
    parser.add_argument("--anchors-per-district", type=int, default=20)
    args = parser.parse_args()
    metadata = write_catalog(
        source_path=args.source or _default_source(),
        boundary_path=args.boundary,
        output_path=args.output,
        metadata_path=args.metadata,
        count=args.count,
        seed=args.seed,
        anchors_per_district=args.anchors_per_district,
    )
    print(json.dumps({
        "output": str(args.output),
        "metadata": str(args.metadata),
        "od_count": metadata["od_count"],
        "origin_district_counts": metadata["origin_district_counts"],
        "distance_band_counts": metadata["distance_band_counts"],
        "situation_counts": metadata["situation_counts"],
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
