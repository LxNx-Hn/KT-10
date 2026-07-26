"""경로·30분 시각 버킷별 검증된 공공 그늘 결과 영구 캐시."""
from __future__ import annotations

import json
from datetime import datetime
from hashlib import sha256
from pathlib import Path
from threading import Lock
import time
from typing import Callable
from uuid import uuid4
from weakref import WeakValueDictionary

from .models import ShadeSummary
from .settings import settings

CACHE_SCHEMA_VERSION = 4
_write_locks: WeakValueDictionary[str, Lock] = WeakValueDictionary()
_write_locks_guard = Lock()
_compute_locks: WeakValueDictionary[str, Lock] = WeakValueDictionary()
_compute_locks_guard = Lock()


def _bucket(departure_at: datetime) -> str:
    normalized = departure_at.replace(
        minute=(departure_at.minute // 30) * 30,
        second=0,
        microsecond=0,
    )
    return normalized.isoformat()


def _identity(route_id: str, departure_at: datetime) -> dict[str, str | int]:
    return {
        "schemaVersion": CACHE_SCHEMA_VERSION,
        "routeId": route_id,
        "departureBucket": _bucket(departure_at),
        "source": "VWorld LT_C_BLDGINFO WFS",
    }


def _cache_path(identity: dict[str, str | int]) -> Path | None:
    cache_dir = settings.shade_cache_dir.strip()
    if not cache_dir:
        return None
    digest = sha256(
        json.dumps(
            identity,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    return Path(cache_dir) / f"shade-{digest}.json"


def _write_lock(path: Path) -> Lock:
    key = str(path.resolve())
    with _write_locks_guard:
        return _write_locks.setdefault(key, Lock())


def _compute_lock(identity: dict[str, str | int]) -> Lock:
    key = json.dumps(
        identity,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    with _compute_locks_guard:
        return _compute_locks.setdefault(key, Lock())


def read(
    route_id: str,
    departure_at: datetime,
) -> ShadeSummary | None:
    identity = _identity(route_id, departure_at)
    path = _cache_path(identity)
    if path is None or not path.is_file():
        return None
    try:
        wrapper = json.loads(path.read_text(encoding="utf-8"))
        cached_at = float(wrapper["cachedAtEpoch"])
        cached_identity = wrapper["identity"]
        summary = ShadeSummary.model_validate(wrapper["summary"])
    except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError):
        return None
    if (
        cached_identity != identity
        or time.time() - cached_at > settings.shade_cache_ttl_seconds
        or summary.status != "estimated_public"
        or summary.data_quality != "public"
        or summary.shade_ratio is None
    ):
        return None
    # 태양 계산 입력은 같은 30분 버킷에서 동일하지만, 사용자에게는
    # 이번 요청의 실제 평가시각을 반환한다.
    return summary.model_copy(
        deep=True,
        update={"evaluated_at": departure_at},
    )


def write(
    route_id: str,
    departure_at: datetime,
    summary: ShadeSummary,
) -> None:
    if (
        summary.status != "estimated_public"
        or summary.data_quality != "public"
        or summary.shade_ratio is None
    ):
        return
    identity = _identity(route_id, departure_at)
    path = _cache_path(identity)
    if path is None:
        return
    with _write_lock(path):
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
        try:
            temporary.write_text(
                json.dumps(
                    {
                        "cachedAtEpoch": time.time(),
                        "identity": identity,
                        "summary": summary.model_dump(
                            mode="json",
                            by_alias=False,
                        ),
                    },
                    ensure_ascii=False,
                    separators=(",", ":"),
                ),
                encoding="utf-8",
            )
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)


def get_or_compute(
    route_id: str,
    departure_at: datetime,
    compute: Callable[[], ShadeSummary],
) -> ShadeSummary:
    """같은 경로·시각의 동시 요청은 한 번만 계산하고 같은 결과를 재사용한다."""
    cached = read(route_id, departure_at)
    if cached is not None:
        return cached
    identity = _identity(route_id, departure_at)
    with _compute_lock(identity):
        cached = read(route_id, departure_at)
        if cached is not None:
            return cached
        summary = compute()
        write(route_id, departure_at, summary)
        return summary
