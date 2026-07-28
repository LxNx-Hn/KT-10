"""운영 API에서 후보 3·5·7·10개의 cold/warm 응답시간을 비교한다."""
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
import random
import statistics
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OD_CATALOG = ROOT / "ai" / "data" / "training" / "od_catalog.csv"


class BenchmarkRequestError(RuntimeError):
    def __init__(self, message: str, seconds: float):
        super().__init__(message)
        self.seconds = seconds


def _percentile(values: list[float], percentile: float) -> float:
    ordered = sorted(values)
    if not ordered:
        raise ValueError("백분위수를 계산할 표본이 없습니다.")
    position = (len(ordered) - 1) * percentile
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = position - lower
    return ordered[lower] + (ordered[upper] - ordered[lower]) * fraction


def _place(row: dict[str, str], prefix: str) -> dict:
    return {
        "id": f"benchmark-{row['od_id']}-{prefix}",
        "name": row[f"{prefix}_name"],
        "lat": float(row[f"{prefix}_lat"]),
        "lng": float(row[f"{prefix}_lng"]),
    }


def _recommend(
    base_url: str,
    row: dict[str, str],
    candidate_count: int,
    timeout_seconds: float,
) -> tuple[float, list]:
    payload = {
        "origin": _place(row, "origin"),
        "destination": _place(row, "dest"),
        "profile": "general",
        "weatherScenario": "normal",
        "options": {},
        "topN": candidate_count,
    }
    request = Request(
        f"{base_url.rstrip('/')}/api/routes/recommend",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    started = time.perf_counter()
    try:
        with urlopen(request, timeout=timeout_seconds) as response:
            data = json.load(response)
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise BenchmarkRequestError(
            f"HTTP {exc.code}: {detail[:500]}",
            time.perf_counter() - started,
        ) from exc
    except (TimeoutError, URLError) as exc:
        raise BenchmarkRequestError(
            f"서버 연결 실패: {type(exc).__name__}",
            time.perf_counter() - started,
        ) from exc
    elapsed = time.perf_counter() - started
    if not isinstance(data, list) or not data:
        raise RuntimeError("추천 응답이 비어 있거나 배열이 아닙니다.")
    return elapsed, data


def _summary(samples: list[dict]) -> dict:
    succeeded = [sample for sample in samples if sample["ok"]]
    seconds = [float(sample["seconds"]) for sample in succeeded]
    failures = [sample for sample in samples if not sample["ok"]]
    if not seconds:
        return {
            "samples": len(samples),
            "successfulSamples": 0,
            "failedSamples": len(failures),
            "successRate": 0.0,
            "p50Seconds": None,
            "p95Seconds": None,
            "minSeconds": None,
            "maxSeconds": None,
            "meanSeconds": None,
            "returnedCandidateP50": None,
            "exactGeometryP50": None,
            "terrainReadyP50": None,
            "shadeReadyP50": None,
        }
    return {
        "samples": len(samples),
        "successfulSamples": len(succeeded),
        "failedSamples": len(failures),
        "successRate": round(len(succeeded) / len(samples), 4),
        "p50Seconds": round(statistics.median(seconds), 3),
        "p95Seconds": round(_percentile(seconds, 0.95), 3),
        "minSeconds": round(min(seconds), 3),
        "maxSeconds": round(max(seconds), 3),
        "meanSeconds": round(statistics.fmean(seconds), 3),
        "returnedCandidateP50": round(statistics.median(
            [int(sample["returnedCandidates"]) for sample in succeeded]
        ), 1),
        "exactGeometryP50": round(statistics.median(
            [int(sample["exactGeometryCount"]) for sample in succeeded]
        ), 1),
        "terrainReadyP50": round(statistics.median(
            [int(sample["terrainReadyCount"]) for sample in succeeded]
        ), 1),
        "shadeReadyP50": round(statistics.median(
            [int(sample["shadeReadyCount"]) for sample in succeeded]
        ), 1),
    }


def _sample(
    base_url: str,
    row: dict[str, str],
    candidate_count: int,
    timeout_seconds: float,
) -> dict:
    try:
        elapsed, routes = _recommend(
            base_url,
            row,
            candidate_count,
            timeout_seconds,
        )
        exact_count = sum(
            (item.get("route") or {}).get("geometryQuality") == "exact"
            for item in routes
            if isinstance(item, dict)
        )
        terrain_count = sum(
            ((item.get("route") or {}).get("terrain") or {}).get("status")
            == "estimated_90m"
            for item in routes
            if isinstance(item, dict)
        )
        shade_count = sum(
            (
                ((item.get("route") or {}).get("shade") or {}).get("status")
                == "estimated_public"
                and ((item.get("route") or {}).get("shade") or {}).get(
                    "shadeRatio"
                ) is not None
            )
            for item in routes
            if isinstance(item, dict)
        )
        quality_complete = (
            exact_count == len(routes)
            and terrain_count == len(routes)
            and shade_count == len(routes)
        )
        sample = {
            "odId": row["od_id"],
            "ok": quality_complete,
            "seconds": round(elapsed, 6),
            "returnedCandidates": len(routes),
            "exactGeometryCount": exact_count,
            "terrainReadyCount": terrain_count,
            "shadeReadyCount": shade_count,
        }
        if not quality_complete:
            sample["error"] = "경로 품질 계약 불충족"
        return sample
    except BenchmarkRequestError as exc:
        return {
            "odId": row["od_id"],
            "ok": False,
            "seconds": round(exc.seconds, 6),
            "error": str(exc),
        }


def _load_catalog(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    required = {
        "od_id",
        "origin_name",
        "origin_lat",
        "origin_lng",
        "dest_name",
        "dest_lat",
        "dest_lng",
    }
    if not rows or not required.issubset(rows[0]):
        raise SystemExit("OD catalog에 필요한 좌표 열이 없습니다.")
    return rows


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://localhost:8080")
    parser.add_argument("--od-catalog", type=Path, default=DEFAULT_OD_CATALOG)
    parser.add_argument("--candidate-counts", default="3,5,7,10")
    parser.add_argument("--cold-runs", type=int, default=20)
    parser.add_argument("--warm-runs", type=int, default=20)
    parser.add_argument("--timeout-seconds", type=float, default=120)
    parser.add_argument("--seed", type=int, default=20260726)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    counts = [int(value.strip()) for value in args.candidate_counts.split(",")]
    if (
        not counts
        or any(value < 1 or value > 10 for value in counts)
        or args.cold_runs < 2
        or args.warm_runs < 2
    ):
        raise SystemExit("후보 수는 1~10, cold/warm 표본 수는 각각 2 이상이어야 합니다.")

    catalog = _load_catalog(args.od_catalog)
    required_rows = len(counts) * args.cold_runs
    if len(catalog) < required_rows:
        raise SystemExit(
            f"서로 다른 cold OD가 {required_rows}개 필요하지만 "
            f"catalog에는 {len(catalog)}개만 있습니다."
        )
    random.Random(args.seed).shuffle(catalog)

    report: dict = {
        "schemaVersion": 2,
        "baseUrl": args.base_url,
        "candidateCounts": counts,
        "requestMode": (
            "90m 경사와 공공 건물 그늘을 모두 포함한 기본 경로 추천."
        ),
        "coldDefinition": (
            "이 실행에서 각 OD에 보내는 첫 요청. "
            "완전 cold 측정은 실행 전 캐시 초기 상태와 함께 판정."
        ),
        "warmDefinition": "같은 실행에서 첫 요청을 마친 OD의 반복 요청.",
        "results": [],
    }
    cursor = 0
    for candidate_count in counts:
        rows = catalog[cursor:cursor + args.cold_runs]
        cursor += args.cold_runs
        cold_samples = []
        for index, row in enumerate(rows, start=1):
            sample = _sample(
                args.base_url,
                row,
                candidate_count,
                args.timeout_seconds,
            )
            cold_samples.append(sample)
            print(
                f"[{candidate_count}] cold {index}/{args.cold_runs} "
                f"{'ok' if sample['ok'] else 'failed'} "
                f"{sample['seconds']:.3f}s",
                file=sys.stderr,
                flush=True,
            )

        warm_samples = []
        for index in range(args.warm_runs):
            row = rows[index % len(rows)]
            sample = _sample(
                args.base_url,
                row,
                candidate_count,
                args.timeout_seconds,
            )
            warm_samples.append(sample)
            print(
                f"[{candidate_count}] warm {index + 1}/{args.warm_runs} "
                f"{'ok' if sample['ok'] else 'failed'} "
                f"{sample['seconds']:.3f}s",
                file=sys.stderr,
                flush=True,
            )

        report["results"].append({
            "requestedCandidates": candidate_count,
            "cold": _summary(cold_samples),
            "warm": _summary(warm_samples),
            "coldSamples": cold_samples,
            "warmSamples": warm_samples,
        })

    rendered = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)


if __name__ == "__main__":
    main()
