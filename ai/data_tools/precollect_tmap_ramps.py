"""배포·데이터 갱신 단계에서 휠체어 도보구간의 TMAP 경사로를 사전 수집한다.

사용자 요청 경로에서는 실행하지 않는다. ODsay 후보의 실제 보행구간과
직접 ORS wheelchair 후보를 먼저 확인한 뒤, 정규화한 고유 구간만 TMAP
``searchOption=30``으로 수집한다. 성공 응답만 기존 collector 캐시에 남고,
오류·쿼터 응답은 정상 캐시로 저장되지 않는다.
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import json
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from uuid import uuid4

from collectors.base import Coordinate, RouteCandidate
from collectors.odsay_collector import OdsayRouteCollector
from collectors.ors_collector import OrsWheelchairRouteCollector
from collectors.tmap_collector import (
    STAIR_EXCLUDED_SEARCH_OPTION,
    TmapRouteCollector,
    write_precomputed_cache,
)
from merger.route_merger import accessibility_paths_similar

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OD_CATALOG = ROOT / "ai" / "data" / "training" / "od_catalog.csv"
DEFAULT_REPORT = ROOT / "data" / "audits" / "tmap_ramp_precollection.audit.json"
DEFAULT_ARTIFACT_DIR = ROOT / "ai" / "data" / "precomputed" / "tmap"
SCHEMA_VERSION = "tmap-ramp-precollection-v1"
REQUIRED_COLUMNS = {
    "origin_name",
    "origin_lat",
    "origin_lng",
    "dest_name",
    "dest_lat",
    "dest_lng",
}


def _read_od_rows(path: Path, limit: int | None = None) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        missing = REQUIRED_COLUMNS.difference(reader.fieldnames or [])
        if missing:
            raise ValueError("OD CSV 컬럼 누락: " + ", ".join(sorted(missing)))
        rows = list(reader)
    if not rows:
        raise ValueError("OD CSV가 비어 있습니다.")
    if limit is not None:
        if limit < 1:
            raise ValueError("limit은 1 이상이어야 합니다.")
        rows = rows[:limit]
    for index, row in enumerate(rows, start=1):
        try:
            latitudes = (float(row["origin_lat"]), float(row["dest_lat"]))
            longitudes = (float(row["origin_lng"]), float(row["dest_lng"]))
        except (TypeError, ValueError) as exc:
            raise ValueError(f"OD {index}행 좌표가 숫자가 아닙니다.") from exc
        if (
            any(not 34.8 <= value <= 35.5 for value in latitudes)
            or any(not 128.7 <= value <= 129.4 for value in longitudes)
        ):
            raise ValueError(f"OD {index}행 좌표가 부산 범위를 벗어났습니다.")
    return rows


def _coordinates(row: dict[str, str]) -> tuple[Coordinate, Coordinate]:
    return (
        Coordinate(lat=float(row["origin_lat"]), lng=float(row["origin_lng"])),
        Coordinate(lat=float(row["dest_lat"]), lng=float(row["dest_lng"])),
    )


def _segment_identity(path: list[Coordinate]) -> tuple[float, float, float, float]:
    return (
        round(path[0].lat, 7),
        round(path[0].lng, 7),
        round(path[-1].lat, 7),
        round(path[-1].lng, 7),
    )


def _identity_hash(identity: tuple[float, ...]) -> str:
    return sha256(
        json.dumps(identity, separators=(",", ":")).encode("ascii")
    ).hexdigest()[:20]


def _verified_wheelchair_path(
    path: object,
    evidence: object,
) -> list[Coordinate] | None:
    if (
        not isinstance(path, list)
        or len(path) < 2
        or not all(isinstance(point, Coordinate) for point in path)
        or not isinstance(evidence, dict)
        or evidence.get("wheelchair_constraints_applied") is not True
        or evidence.get("stairs_excluded_by_provider") is not True
    ):
        return None
    return path


def _candidate_walk_segments(candidate: RouteCandidate) -> list[list[Coordinate]]:
    if candidate.source == "ors":
        path = _verified_wheelchair_path(
            candidate.path,
            candidate.accessibility_evidence,
        )
        return [path] if path is not None else []
    segments: list[list[Coordinate]] = []
    for segment in candidate.segments or []:
        if (
            segment.get("mode") not in {"walk", "transfer"}
            or segment.get("distance_m") == 0
        ):
            continue
        path = _verified_wheelchair_path(
            segment.get("path"),
            segment.get("accessibility_evidence"),
        )
        if path is not None:
            segments.append(path)
    return segments


def _error(source: str, exc: Exception) -> dict[str, str]:
    return {
        "source": source,
        "errorType": type(exc).__name__,
        "detail": str(exc)[:300],
    }


async def _discover_segments(
    rows: list[dict[str, str]],
    *,
    candidate_limit: int,
) -> tuple[dict[tuple[float, ...], list[Coordinate]], list[dict]]:
    unique: dict[tuple[float, ...], list[Coordinate]] = {}
    failures: list[dict] = []
    for index, row in enumerate(rows, start=1):
        origin, destination = _coordinates(row)
        results = await asyncio.gather(
            OdsayRouteCollector(
                avoid_stairs=True,
                uses_wheelchair=True,
            ).collect(origin, destination, max_candidates=candidate_limit),
            OrsWheelchairRouteCollector().collect(origin, destination),
            return_exceptions=True,
        )
        succeeded = False
        for source, result in zip(("odsay", "ors"), results, strict=True):
            if isinstance(result, Exception):
                failures.append({"odIndex": index, **_error(source, result)})
                continue
            for candidate in result:
                for path in _candidate_walk_segments(candidate):
                    unique.setdefault(_segment_identity(path), path)
                    succeeded = True
        if not succeeded:
            failures.append({
                "odIndex": index,
                "source": "wheelchair-walk-segments",
                "errorType": "NoVerifiedSegments",
                "detail": "ORS wheelchair 제약이 확인된 도보구간이 없습니다.",
            })
    return unique, failures


async def _precollect_segment(
    identity: tuple[float, ...],
    ors_path: list[Coordinate],
    *,
    artifact_dir: Path,
) -> dict:
    collector = TmapRouteCollector(avoid_stairs=True)
    origin, destination = ors_path[0], ors_path[-1]
    cached = await collector.collect_cached(origin, destination)
    cache_hit = bool(cached)
    candidates = cached or await collector.collect(origin, destination)
    if not candidates:
        raise RuntimeError("TMAP 경로가 비어 있습니다.")
    candidate = candidates[0]
    if not accessibility_paths_similar(ors_path, candidate.path):
        raise RuntimeError("TMAP 경로가 ORS wheelchair 선형과 일치하지 않습니다.")
    if not isinstance(candidate.raw_response, dict):
        raise TypeError("TMAP 원본 응답을 사전가공 캐시로 내보낼 수 없습니다.")
    await asyncio.to_thread(
        write_precomputed_cache,
        origin,
        destination,
        search_option=STAIR_EXCLUDED_SEARCH_OPTION,
        payload=candidate.raw_response,
        cache_dir=artifact_dir,
    )
    ramps = candidate.accessibility_evidence.get("ramp_points")
    ramps = ramps if isinstance(ramps, list) else []
    return {
        "segmentHash": _identity_hash(identity),
        "cacheHit": cache_hit,
        "rampEvidencePointCount": len(ramps),
        "stairAlternativeRampPointCount": sum(
            isinstance(point, dict) and point.get("replaces_stairs") is True
            for point in ramps
        ),
    }


async def precollect_rows(
    rows: list[dict[str, str]],
    *,
    candidate_limit: int = 5,
    artifact_dir: Path = DEFAULT_ARTIFACT_DIR,
) -> dict:
    if not 1 <= candidate_limit <= 10:
        raise ValueError("candidate_limit은 1~10이어야 합니다.")
    segments, discovery_failures = await _discover_segments(
        rows,
        candidate_limit=candidate_limit,
    )
    results: list[dict] = []
    collection_failures: list[dict] = []
    for identity, path in segments.items():
        try:
            results.append(await _precollect_segment(
                identity,
                path,
                artifact_dir=artifact_dir,
            ))
        # OD 하나의 공급자 실패 때문에 다른 고유 구간의 갱신을 버리지 않고,
        # 전체 실패를 partial 감사 보고서와 비정상 종료코드로 보존한다.
        except Exception as exc:  # noqa: BLE001
            collection_failures.append({
                "segmentHash": _identity_hash(identity),
                **_error("tmap", exc),
            })
    failures = [*discovery_failures, *collection_failures]
    return {
        "schemaVersion": SCHEMA_VERSION,
        "capturedAt": datetime.now(UTC).isoformat(),
        "status": "complete" if not failures else "partial",
        "sourceDocumentation": (
            "https://tmapapi.tmapmobility.com/"
            "webservice/docs/tmapRoutePedestrianDoc.html"
        ),
        "artifactDirectory": str(artifact_dir.resolve()),
        "requestedOdCount": len(rows),
        "uniqueVerifiedWalkSegmentCount": len(segments),
        "validatedTmapSegmentCount": len(results),
        "networkMissCount": sum(not result["cacheHit"] for result in results),
        "knownRampSegmentCount": sum(
            result["rampEvidencePointCount"] > 0 for result in results
        ),
        "knownStairAlternativeRampSegmentCount": sum(
            result["stairAlternativeRampPointCount"] > 0 for result in results
        ),
        "results": results,
        "failures": failures,
    }


def _write_report(path: Path, report: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    try:
        temporary.write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--od-catalog", type=Path, default=DEFAULT_OD_CATALOG)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument(
        "--artifact-dir",
        type=Path,
        default=DEFAULT_ARTIFACT_DIR,
        help="검증된 TMAP 응답을 저장할 배포 이미지용 캐시 디렉터리",
    )
    parser.add_argument("--limit", type=int)
    parser.add_argument("--candidate-limit", type=int, default=5)
    parser.add_argument(
        "--allow-partial",
        action="store_true",
        help="실패가 있어도 보고서를 남기고 종료코드 0을 반환한다.",
    )
    args = parser.parse_args()
    rows = _read_od_rows(args.od_catalog, args.limit)
    report = asyncio.run(precollect_rows(
        rows,
        candidate_limit=args.candidate_limit,
        artifact_dir=args.artifact_dir,
    ))
    _write_report(args.report, report)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if report["status"] != "complete" and not args.allow_partial:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
