"""대규모 Judge 학습용 실제 경로 후보를 체크포인트 방식으로 수집한다.

성공한 OD는 즉시 JSONL에 추가하므로 프로세스나 외부 API가 중단되어도
다음 실행에서 완료 항목을 건너뛴다. 최종 피처 파일은 성공 체크포인트에서
검증 후 다시 생성하며, 부분 수집을 완료로 표시하지 않는다.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import time
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable

import httpx

from scoring.snapshots import validate_live_feature_snapshot
from scoring.train import FEATURE_COLS

COLLECTION_SCHEMA_VERSION = "judge-candidate-collection-v1"
RETRIABLE_STATUS_CODES = {408, 425, 429, 500, 502, 503, 504}
REQUIRED_OD_COLUMNS = {
    "origin_name",
    "origin_lat",
    "origin_lng",
    "dest_name",
    "dest_lat",
    "dest_lng",
}
SEMANTIC_OD_COLUMNS = (
    "od_id",
    "origin_name",
    "origin_lat",
    "origin_lng",
    "dest_name",
    "dest_lat",
    "dest_lng",
    "weather",
    "departure_at",
    "carry_luggage",
    "stroller",
    "shade_priority",
    "minimize_transfers",
    "avoid_stairs",
    "low_floor_priority",
)
TRUE_VALUES = {"1", "true", "y", "yes"}


class CandidateCollectionError(RuntimeError):
    """한 OD의 후보 수집이 재시도 후에도 완료되지 않은 경우."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        retriable: bool = False,
        retry_delay_seconds: float | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.retriable = retriable
        self.retry_delay_seconds = retry_delay_seconds


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _read_od_rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        missing = REQUIRED_OD_COLUMNS.difference(reader.fieldnames or [])
        if missing:
            raise ValueError("OD CSV 컬럼 누락: " + ", ".join(sorted(missing)))
        rows = list(reader)
    if not rows:
        raise ValueError("OD CSV가 비어 있습니다.")
    seen_ids: set[str] = set()
    for row_number, row in enumerate(rows, start=1):
        od_id = (row.get("od_id") or "").strip() or _derived_od_id(row)
        if od_id in seen_ids:
            raise ValueError(f"OD 식별자 중복: {od_id}")
        seen_ids.add(od_id)
        row["od_id"] = od_id
        try:
            latitudes = (float(row["origin_lat"]), float(row["dest_lat"]))
            longitudes = (float(row["origin_lng"]), float(row["dest_lng"]))
        except (TypeError, ValueError) as exc:
            raise ValueError(f"OD {row_number}행 좌표가 숫자가 아닙니다.") from exc
        if (
            any(not -90 <= value <= 90 for value in latitudes)
            or any(not -180 <= value <= 180 for value in longitudes)
        ):
            raise ValueError(f"OD {row_number}행 좌표 범위가 올바르지 않습니다.")
    return rows


def _derived_od_id(row: dict[str, str]) -> str:
    stable = "|".join(str(row.get(column) or "").strip() for column in SEMANTIC_OD_COLUMNS[1:7])
    return "od-" + hashlib.sha256(stable.encode("utf-8")).hexdigest()[:20]


def _request_fingerprint(row: dict[str, str]) -> str:
    payload = {
        column: str(row.get(column) or "").strip()
        for column in SEMANTIC_OD_COLUMNS
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _as_bool(value: str | None) -> bool:
    return str(value or "").strip().casefold() in TRUE_VALUES


def _request_payload(row: dict[str, str]) -> dict[str, Any]:
    od_id = row["od_id"]
    options = {
        "carryLuggage": _as_bool(row.get("carry_luggage")),
        "stroller": _as_bool(row.get("stroller")),
        "shadePriority": _as_bool(row.get("shade_priority")),
        "minimizeTransfers": _as_bool(row.get("minimize_transfers")),
        "avoidStairs": _as_bool(row.get("avoid_stairs")),
        "lowFloorPriority": _as_bool(row.get("low_floor_priority")),
    }
    departure_at = str(row.get("departure_at") or "").strip()
    if departure_at:
        options["departureAt"] = departure_at
    return {
        "origin": {
            "id": f"catalog-origin-{od_id}",
            "name": row["origin_name"],
            "lat": float(row["origin_lat"]),
            "lng": float(row["origin_lng"]),
        },
        "destination": {
            "id": f"catalog-destination-{od_id}",
            "name": row["dest_name"],
            "lat": float(row["dest_lat"]),
            "lng": float(row["dest_lng"]),
        },
        "profile": "general",
        "weatherScenario": str(row.get("weather") or "").strip() or "normal",
        "options": options,
        "topN": 10,
    }


def _validate_candidate_payload(
    data: Any,
    *,
    row: dict[str, str],
    minimum_candidates: int,
    minimum_known_slope_candidates: int,
    minimum_known_shade_candidates: int,
    quality_retry_delay_seconds: float,
) -> dict[str, Any]:
    if not isinstance(data, dict):
        raise CandidateCollectionError("후보 API 응답이 JSON 객체가 아닙니다.")
    group_id = str(data.get("group_id") or "").strip()
    candidates = data.get("candidates")
    if not group_id or not isinstance(candidates, list):
        raise CandidateCollectionError("후보 API 그룹 또는 후보 배열이 올바르지 않습니다.")
    if len(candidates) < minimum_candidates:
        raise CandidateCollectionError(
            f"비교 가능한 후보가 부족합니다: {len(candidates)}개 "
            f"(최소 {minimum_candidates}개)"
        )

    compact_candidates: list[dict[str, Any]] = []
    route_ids: set[str] = set()
    holdout_group_ids: set[str] = set()
    known_slope_candidates = 0
    known_shade_candidates = 0
    for candidate_index, candidate in enumerate(candidates, start=1):
        if not isinstance(candidate, dict):
            raise CandidateCollectionError(
                f"{candidate_index}번째 후보가 JSON 객체가 아닙니다."
            )
        route_id = str(candidate.get("route_id") or "").strip()
        snapshot = candidate.get("feature_snapshot")
        if not route_id or route_id in route_ids or not isinstance(snapshot, dict):
            raise CandidateCollectionError("후보 식별자 또는 피처 스냅샷이 올바르지 않습니다.")
        try:
            validate_live_feature_snapshot(snapshot, FEATURE_COLS)
        except (KeyError, TypeError, ValueError) as exc:
            raise CandidateCollectionError(
                f"{route_id} 피처 스냅샷 검증 실패: {exc}"
            ) from exc
        if (
            str(snapshot["group_id"]) != group_id
            or str(snapshot["route_id"]) != route_id
        ):
            raise CandidateCollectionError(
                f"{route_id} 후보와 스냅샷 식별자가 일치하지 않습니다."
            )
        route_ids.add(route_id)
        holdout_group_ids.add(str(snapshot["holdout_group_id"]))
        features = snapshot["features"]
        known_slope_candidates += int(all(
            features.get(name) is not None
            for name in (
                "avg_slope_percent",
                "max_slope_percent",
                "min_slope_percent",
            )
        ))
        known_shade_candidates += int(all(
            features.get(name) is not None
            for name in ("shade_ratio", "shaded_walk_m")
        ))
        compact_candidates.append({
            "route_id": route_id,
            "summary": candidate.get("summary"),
            "duration_min": candidate.get("duration_min"),
            "distance_m": candidate.get("distance_m"),
            "sources": candidate.get("sources"),
            "geometry_quality": candidate.get("geometry_quality"),
            "segment_geometry": [
                {
                    "mode": segment.get("mode"),
                    "distance_m": segment.get("distance_m"),
                    "geometry_quality": segment.get("geometry_quality"),
                }
                for segment in candidate.get("segments") or []
                if isinstance(segment, dict)
            ],
            "trait_labels": candidate.get("trait_labels"),
            "feature_snapshot": snapshot,
        })
    if len(holdout_group_ids) != 1:
        raise CandidateCollectionError("같은 OD 후보의 holdout 그룹이 일치하지 않습니다.")
    quality_failures = []
    if known_slope_candidates < minimum_known_slope_candidates:
        quality_failures.append(
            f"경사 확인 후보 {known_slope_candidates}/{minimum_known_slope_candidates}"
        )
    if known_shade_candidates < minimum_known_shade_candidates:
        quality_failures.append(
            f"그늘 확인 후보 {known_shade_candidates}/{minimum_known_shade_candidates}"
        )
    if quality_failures:
        raise CandidateCollectionError(
            "후보 품질 기준 미달: " + ", ".join(quality_failures),
            retriable=True,
            retry_delay_seconds=quality_retry_delay_seconds,
        )

    return {
        "schema_version": COLLECTION_SCHEMA_VERSION,
        "od_id": row["od_id"],
        "request_fingerprint": _request_fingerprint(row),
        "collected_at": _utc_now(),
        "request_context": {
            column: str(row.get(column) or "").strip()
            for column in SEMANTIC_OD_COLUMNS
        },
        "group_id": group_id,
        "holdout_group_id": next(iter(holdout_group_ids)),
        "quality_contract": {
            "minimum_candidates": minimum_candidates,
            "minimum_known_slope_candidates": minimum_known_slope_candidates,
            "minimum_known_shade_candidates": minimum_known_shade_candidates,
        },
        "quality_observed": {
            "candidate_count": len(compact_candidates),
            "known_slope_candidate_count": known_slope_candidates,
            "known_shade_candidate_count": known_shade_candidates,
        },
        "candidates": compact_candidates,
    }


def _retry_delay_seconds(response: httpx.Response | None, attempt: int) -> float:
    if response is not None:
        retry_after = response.headers.get("Retry-After")
        if retry_after:
            try:
                return min(30.0, max(0.0, float(retry_after)))
            except ValueError:
                pass
    return min(30.0, float(2 ** max(0, attempt - 1)))


def _fetch_candidate_group(
    *,
    row: dict[str, str],
    server_url: str,
    api_token: str,
    timeout_seconds: float,
    max_attempts: int,
    minimum_candidates: int,
    minimum_known_slope_candidates: int,
    minimum_known_shade_candidates: int,
    quality_retry_delay_seconds: float,
) -> dict[str, Any]:
    endpoint = f"{server_url.rstrip('/')}/api/routes/labeling-candidates"
    last_error: CandidateCollectionError | None = None
    with httpx.Client(timeout=timeout_seconds) as client:
        for attempt in range(1, max_attempts + 1):
            response: httpx.Response | None = None
            try:
                response = client.post(
                    endpoint,
                    json=_request_payload(row),
                    headers={"X-Labeling-Token": api_token},
                )
                if not response.is_success:
                    detail = response.text[:1000].replace(api_token, "[REDACTED]")
                    retriable = response.status_code in RETRIABLE_STATUS_CODES
                    last_error = CandidateCollectionError(
                        f"후보 API HTTP {response.status_code}: {detail}",
                        status_code=response.status_code,
                        retriable=retriable,
                    )
                    if not retriable:
                        raise last_error
                else:
                    try:
                        data = response.json()
                    except json.JSONDecodeError as exc:
                        last_error = CandidateCollectionError(
                            "후보 API 응답이 유효한 JSON이 아닙니다.",
                            retriable=True,
                        )
                    else:
                        try:
                            return _validate_candidate_payload(
                                data,
                                row=row,
                                minimum_candidates=minimum_candidates,
                                minimum_known_slope_candidates=minimum_known_slope_candidates,
                                minimum_known_shade_candidates=minimum_known_shade_candidates,
                                quality_retry_delay_seconds=quality_retry_delay_seconds,
                            )
                        except CandidateCollectionError as exc:
                            last_error = CandidateCollectionError(
                                str(exc),
                                retriable=True,
                                retry_delay_seconds=exc.retry_delay_seconds,
                            )
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                last_error = CandidateCollectionError(
                    f"후보 API 연결 실패: {type(exc).__name__}",
                    retriable=True,
                )
            if (
                last_error is not None
                and last_error.retriable
                and attempt < max_attempts
            ):
                time.sleep(
                    last_error.retry_delay_seconds
                    if last_error.retry_delay_seconds is not None
                    else _retry_delay_seconds(response, attempt)
                )
                continue
            break
    raise last_error or CandidateCollectionError("알 수 없는 후보 수집 실패")


def _append_jsonl(path: Path, item: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(
            json.dumps(item, ensure_ascii=False, separators=(",", ":")) + "\n"
        )
        handle.flush()
        os.fsync(handle.fileno())


def _write_json(path: Path, item: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(item, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _load_checkpoint(path: Path) -> dict[str, dict[str, Any]]:
    if not path.exists():
        return {}
    records: dict[str, dict[str, Any]] = {}
    for line_number, line in enumerate(
        path.read_text(encoding="utf-8").splitlines(),
        start=1,
    ):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"수집 체크포인트 {line_number}행 JSON 오류") from exc
        if (
            not isinstance(record, dict)
            or record.get("schema_version") != COLLECTION_SCHEMA_VERSION
            or not str(record.get("od_id") or "").strip()
        ):
            raise ValueError(f"수집 체크포인트 {line_number}행 계약 오류")
        od_id = str(record["od_id"])
        if od_id in records:
            raise ValueError(f"수집 체크포인트 OD 중복: {od_id}")
        records[od_id] = record
    return records


def _verify_checkpoint_against_catalog(
    records: dict[str, dict[str, Any]],
    rows_by_id: dict[str, dict[str, str]],
    *,
    minimum_candidates: int,
    minimum_known_slope_candidates: int,
    minimum_known_shade_candidates: int,
    quality_retry_delay_seconds: float,
) -> None:
    unknown = set(records) - set(rows_by_id)
    if unknown:
        raise ValueError(
            "현재 OD 카탈로그에 없는 체크포인트가 있습니다: "
            + ", ".join(sorted(unknown)[:5])
        )
    for od_id, record in records.items():
        expected = _request_fingerprint(rows_by_id[od_id])
        if record.get("request_fingerprint") != expected:
            raise ValueError(
                f"{od_id}: 체크포인트와 현재 OD 요청 내용이 다릅니다."
            )
        reconstructed = {
            "group_id": record.get("group_id"),
            "candidates": record.get("candidates"),
        }
        _validate_candidate_payload(
            reconstructed,
            row=rows_by_id[od_id],
            minimum_candidates=minimum_candidates,
            minimum_known_slope_candidates=minimum_known_slope_candidates,
            minimum_known_shade_candidates=minimum_known_shade_candidates,
            quality_retry_delay_seconds=quality_retry_delay_seconds,
        )


def materialize_collection(
    *,
    checkpoint_path: Path,
    output_dir: Path,
    expected_od_count: int,
) -> dict[str, Any]:
    """검증된 체크포인트에서 중복 없는 피처·Judge 문맥 파일을 만든다."""
    records = _load_checkpoint(checkpoint_path)
    feature_rows: list[dict[str, Any]] = []
    context_rows: list[dict[str, Any]] = []
    seen_routes: set[tuple[str, str]] = set()
    for od_id in sorted(records):
        record = records[od_id]
        for candidate in record["candidates"]:
            snapshot = candidate["feature_snapshot"]
            validate_live_feature_snapshot(snapshot, FEATURE_COLS)
            route_key = (str(record["group_id"]), str(candidate["route_id"]))
            if route_key in seen_routes:
                raise ValueError(
                    "중복 후보 스냅샷: " + "/".join(route_key)
                )
            seen_routes.add(route_key)
            feature_rows.append(snapshot)
            context_rows.append({
                "od_id": od_id,
                "request_context": record["request_context"],
                "group_id": record["group_id"],
                "holdout_group_id": record["holdout_group_id"],
                "route_id": candidate["route_id"],
                "feature_snapshot_hash": snapshot["feature_snapshot_hash"],
                "summary": candidate.get("summary"),
                "duration_min": candidate.get("duration_min"),
                "distance_m": candidate.get("distance_m"),
                "sources": candidate.get("sources"),
                "geometry_quality": candidate.get("geometry_quality"),
                "segment_geometry": candidate.get("segment_geometry"),
                "trait_labels": candidate.get("trait_labels"),
            })

    output_dir.mkdir(parents=True, exist_ok=True)
    feature_path = output_dir / "route_features.jsonl"
    context_path = output_dir / "candidate_context.jsonl"
    feature_path.write_text(
        "".join(
            json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n"
            for row in feature_rows
        ),
        encoding="utf-8",
    )
    context_path.write_text(
        "".join(
            json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n"
            for row in context_rows
        ),
        encoding="utf-8",
    )
    report = {
        "schema_version": "judge-candidate-materialization-v1",
        "expected_od_count": expected_od_count,
        "completed_od_count": len(records),
        "candidate_count": len(feature_rows),
        "minimum_candidates_per_completed_od": min(
            (len(record["candidates"]) for record in records.values()),
            default=0,
        ),
        "maximum_candidates_per_completed_od": max(
            (len(record["candidates"]) for record in records.values()),
            default=0,
        ),
        "ready_for_judge": len(records) == expected_od_count,
        "route_features": str(feature_path),
        "candidate_context": str(context_path),
    }
    _write_json(output_dir / "collection_report.json", report)
    return report


FetchFunction = Callable[..., dict[str, Any]]
ProgressFunction = Callable[[dict[str, Any]], None]


def collect(
    *,
    od_path: Path,
    output_dir: Path,
    server_url: str,
    api_token: str,
    workers: int = 2,
    timeout_seconds: float = 180.0,
    max_attempts: int = 4,
    minimum_candidates: int = 2,
    minimum_known_slope_candidates: int = 2,
    minimum_known_shade_candidates: int = 2,
    quality_retry_delay_seconds: float = 45.0,
    provider_unique_od_budget: int = 900,
    limit: int | None = None,
    fetcher: FetchFunction = _fetch_candidate_group,
    on_progress: ProgressFunction | None = None,
) -> dict[str, Any]:
    if len(api_token.strip()) < 32:
        raise ValueError("LABELING_API_TOKEN은 32자 이상이어야 합니다.")
    if not 1 <= workers <= 8:
        raise ValueError("workers는 1~8 범위여야 합니다.")
    if (
        timeout_seconds <= 0
        or max_attempts < 1
        or minimum_candidates < 2
        or minimum_known_slope_candidates < 0
        or minimum_known_shade_candidates < 0
        or minimum_known_slope_candidates > minimum_candidates
        or minimum_known_shade_candidates > minimum_candidates
        or quality_retry_delay_seconds < 0
        or provider_unique_od_budget < 1
    ):
        raise ValueError("timeout, max_attempts, minimum_candidates 설정이 올바르지 않습니다.")
    all_rows = _read_od_rows(od_path)
    selected_rows = all_rows[:limit] if limit is not None else all_rows
    if not selected_rows:
        raise ValueError("수집할 OD가 없습니다.")
    if len(selected_rows) > provider_unique_od_budget:
        raise ValueError(
            "선택한 고유 OD 수가 공급자 호출 예산을 초과합니다: "
            f"{len(selected_rows)} > {provider_unique_od_budget}"
        )
    rows_by_id = {row["od_id"]: row for row in selected_rows}
    checkpoint_path = output_dir / "candidate_groups.jsonl"
    failure_path = output_dir / "failures.jsonl"
    progress_path = output_dir / "progress.json"
    completed = _load_checkpoint(checkpoint_path)
    _verify_checkpoint_against_catalog(
        completed,
        rows_by_id,
        minimum_candidates=minimum_candidates,
        minimum_known_slope_candidates=minimum_known_slope_candidates,
        minimum_known_shade_candidates=minimum_known_shade_candidates,
        quality_retry_delay_seconds=quality_retry_delay_seconds,
    )
    pending = [row for row in selected_rows if row["od_id"] not in completed]
    failed_ids: set[str] = set()

    def progress_payload() -> dict[str, Any]:
        return {
            "schema_version": "judge-candidate-progress-v1",
            "updated_at": _utc_now(),
            "catalog_od_count": len(all_rows),
            "selected_od_count": len(selected_rows),
            "provider_unique_od_budget": provider_unique_od_budget,
            "completed_od_count": len(completed),
            "failed_od_count_this_run": len(failed_ids),
            "remaining_od_count": len(selected_rows) - len(completed),
            "ready_for_materialization": len(completed) == len(selected_rows),
        }

    _write_json(progress_path, progress_payload())
    if on_progress:
        on_progress(progress_payload())

    future_rows: dict[Future[dict[str, Any]], dict[str, str]] = {}
    pending_iterator = iter(pending)
    with ThreadPoolExecutor(max_workers=workers) as executor:
        for _ in range(min(workers, len(pending))):
            row = next(pending_iterator, None)
            if row is None:
                break
            future_rows[executor.submit(
                fetcher,
                row=row,
                server_url=server_url,
                api_token=api_token,
                timeout_seconds=timeout_seconds,
                max_attempts=max_attempts,
                minimum_candidates=minimum_candidates,
                minimum_known_slope_candidates=minimum_known_slope_candidates,
                minimum_known_shade_candidates=minimum_known_shade_candidates,
                quality_retry_delay_seconds=quality_retry_delay_seconds,
            )] = row

        while future_rows:
            done, _ = wait(future_rows, return_when=FIRST_COMPLETED)
            for future in done:
                row = future_rows.pop(future)
                try:
                    record = future.result()
                    if record["od_id"] != row["od_id"]:
                        raise CandidateCollectionError(
                            "수집 결과 OD 식별자가 요청과 다릅니다."
                        )
                    _append_jsonl(checkpoint_path, record)
                    completed[row["od_id"]] = record
                except Exception as exc:
                    failed_ids.add(row["od_id"])
                    status_code = (
                        exc.status_code
                        if isinstance(exc, CandidateCollectionError)
                        else None
                    )
                    _append_jsonl(failure_path, {
                        "failed_at": _utc_now(),
                        "od_id": row["od_id"],
                        "request_fingerprint": _request_fingerprint(row),
                        "error_type": type(exc).__name__,
                        "status_code": status_code,
                        "detail": str(exc)[:1000].replace(api_token, "[REDACTED]"),
                    })
                update = progress_payload()
                _write_json(progress_path, update)
                if on_progress:
                    on_progress(update)
                next_row = next(pending_iterator, None)
                if next_row is not None:
                    future_rows[executor.submit(
                        fetcher,
                        row=next_row,
                        server_url=server_url,
                        api_token=api_token,
                        timeout_seconds=timeout_seconds,
                        max_attempts=max_attempts,
                        minimum_candidates=minimum_candidates,
                        minimum_known_slope_candidates=minimum_known_slope_candidates,
                        minimum_known_shade_candidates=minimum_known_shade_candidates,
                        quality_retry_delay_seconds=quality_retry_delay_seconds,
                    )] = next_row

    report = materialize_collection(
        checkpoint_path=checkpoint_path,
        output_dir=output_dir,
        expected_od_count=len(selected_rows),
    )
    report.update({
        "catalog_od_count": len(all_rows),
        "selected_od_count": len(selected_rows),
        "provider_unique_od_budget": provider_unique_od_budget,
        "failed_od_count_this_run": len(failed_ids),
        "remaining_od_count": len(selected_rows) - len(completed),
        "checkpoint": str(checkpoint_path),
        "failures": str(failure_path),
    })
    _write_json(output_dir / "collection_report.json", report)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(
        description="중단·재개 가능한 Judge 후보 수집"
    )
    parser.add_argument(
        "--od-file",
        type=Path,
        default=Path("ai/data/training/od_800.csv"),
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("ai/data/training/generated/judge_800_collection"),
    )
    parser.add_argument("--server-url", default="http://127.0.0.1:8003")
    parser.add_argument(
        "--api-token",
        default=os.getenv("LABELING_API_TOKEN", ""),
        help="기본값은 LABELING_API_TOKEN 환경변수입니다.",
    )
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--timeout-seconds", type=float, default=180.0)
    parser.add_argument("--max-attempts", type=int, default=4)
    parser.add_argument("--minimum-candidates", type=int, default=2)
    parser.add_argument(
        "--minimum-known-slope-candidates",
        type=int,
        default=2,
    )
    parser.add_argument(
        "--minimum-known-shade-candidates",
        type=int,
        default=2,
    )
    parser.add_argument(
        "--quality-retry-delay-seconds",
        type=float,
        default=45.0,
    )
    parser.add_argument(
        "--provider-unique-od-budget",
        type=int,
        default=900,
    )
    parser.add_argument("--limit", type=int)
    parser.add_argument("--progress-every", type=int, default=25)
    args = parser.parse_args()
    last_printed = -1

    def print_progress(progress: dict[str, Any]) -> None:
        nonlocal last_printed
        completed = int(progress["completed_od_count"])
        if (
            completed == progress["selected_od_count"]
            or completed == 0
            or completed - last_printed >= args.progress_every
        ):
            print(json.dumps(progress, ensure_ascii=False), flush=True)
            last_printed = completed

    report = collect(
        od_path=args.od_file,
        output_dir=args.output_dir,
        server_url=args.server_url,
        api_token=args.api_token,
        workers=args.workers,
        timeout_seconds=args.timeout_seconds,
        max_attempts=args.max_attempts,
        minimum_candidates=args.minimum_candidates,
        minimum_known_slope_candidates=args.minimum_known_slope_candidates,
        minimum_known_shade_candidates=args.minimum_known_shade_candidates,
        quality_retry_delay_seconds=args.quality_retry_delay_seconds,
        provider_unique_od_budget=args.provider_unique_od_budget,
        limit=args.limit,
        on_progress=print_progress,
    )
    print(json.dumps(report, ensure_ascii=False), flush=True)
    if report["remaining_od_count"]:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
