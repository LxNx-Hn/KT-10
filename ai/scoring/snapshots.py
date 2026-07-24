"""실제 경로 후보 피처 스냅샷의 고정·검증 계약."""
from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any

from .schema import GEOMETRY_QUALITIES, validate_feature_values

SNAPSHOT_SCHEMA_VERSION = "route-feature-snapshot-v2"
LIVE_SNAPSHOT_KIND = "live_route_candidate"


def feature_snapshot_hash(snapshot: dict[str, Any]) -> str:
    """스냅샷 전체를 정규화해 변경 감지용 SHA-256을 계산한다."""
    canonical = {
        key: value
        for key, value in snapshot.items()
        if key != "feature_snapshot_hash"
    }
    encoded = json.dumps(
        canonical,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def build_live_feature_snapshot(
    *,
    group_id: str,
    route_id: str,
    features: dict[str, Any],
    sources: list[str],
    geometry_quality: str | None,
    holdout_group_id: str,
    captured_at: str | None = None,
    shade_evaluated_at: str | None = None,
) -> dict[str, Any]:
    """라이브 후보 API 응답만 받아 해시가 포함된 불변 스냅샷을 만든다."""
    if not sources or any(not isinstance(source, str) or not source.strip() for source in sources):
        raise ValueError("실제 경로 후보 스냅샷에는 비어 있지 않은 sources가 필요합니다.")
    if not isinstance(holdout_group_id, str) or not holdout_group_id.strip():
        raise ValueError("스냅샷의 holdout_group_id가 비어 있습니다.")
    snapshot: dict[str, Any] = {
        "snapshot_schema_version": SNAPSHOT_SCHEMA_VERSION,
        "snapshot_kind": LIVE_SNAPSHOT_KIND,
        "captured_at": captured_at or datetime.now(UTC).isoformat(),
        "group_id": str(group_id),
        "holdout_group_id": holdout_group_id,
        "route_id": str(route_id),
        "sources": sorted(set(sources)),
        "geometry_quality": geometry_quality,
        "features": dict(features),
    }
    if shade_evaluated_at is not None:
        snapshot["shade_evaluated_at"] = shade_evaluated_at
    snapshot["feature_snapshot_hash"] = feature_snapshot_hash(snapshot)
    return snapshot


def validate_live_feature_snapshot(
    snapshot: dict[str, Any],
    feature_columns: list[str],
) -> None:
    """Judge baseline에 사용할 수 있는 실제 후보 스냅샷인지 검증한다."""
    if snapshot.get("snapshot_schema_version") != SNAPSHOT_SCHEMA_VERSION:
        raise ValueError(
            f"snapshot_schema_version은 {SNAPSHOT_SCHEMA_VERSION}이어야 합니다."
        )
    if snapshot.get("snapshot_kind") != LIVE_SNAPSHOT_KIND:
        raise ValueError(f"snapshot_kind는 {LIVE_SNAPSHOT_KIND}이어야 합니다.")
    for field in (
        "group_id",
        "holdout_group_id",
        "route_id",
        "captured_at",
        "feature_snapshot_hash",
    ):
        if not isinstance(snapshot.get(field), str) or not snapshot[field].strip():
            raise ValueError(f"스냅샷의 {field}가 비어 있습니다.")

    captured_at = datetime.fromisoformat(snapshot["captured_at"].replace("Z", "+00:00"))
    if captured_at.tzinfo is None:
        raise ValueError("captured_at에는 UTC 오프셋이 필요합니다.")
    if snapshot.get("shade_evaluated_at") is not None:
        shade_evaluated_at = datetime.fromisoformat(
            str(snapshot["shade_evaluated_at"]).replace("Z", "+00:00")
        )
        if shade_evaluated_at.tzinfo is None:
            raise ValueError("shade_evaluated_at에는 UTC 오프셋이 필요합니다.")

    sources = snapshot.get("sources")
    if not isinstance(sources, list) or not sources:
        raise ValueError("실제 경로 후보 스냅샷에는 sources가 필요합니다.")
    if any(not isinstance(source, str) or not source.strip() for source in sources):
        raise ValueError("sources에는 비어 있지 않은 문자열만 허용됩니다.")
    if len(sources) != len(set(sources)):
        raise ValueError("sources에는 중복 값을 넣을 수 없습니다.")
    if snapshot.get("geometry_quality") not in GEOMETRY_QUALITIES:
        raise ValueError(
            "geometry_quality는 exact, mixed, estimated 중 하나여야 합니다."
        )

    features = snapshot.get("features")
    if not isinstance(features, dict):
        raise ValueError("스냅샷의 features는 객체여야 합니다.")
    missing = set(feature_columns).difference(features)
    if missing:
        raise ValueError(
            "스냅샷 피처 컬럼 누락: " + ", ".join(sorted(missing))
        )
    validate_feature_values(features, feature_columns)

    expected_hash = feature_snapshot_hash(snapshot)
    if snapshot["feature_snapshot_hash"] != expected_hash:
        raise ValueError("feature_snapshot_hash가 현재 스냅샷 내용과 일치하지 않습니다.")
