"""OD별 정적 경로·공간·90m 경사 피처의 TTL 캐시."""
from __future__ import annotations

import asyncio
import json
import time
from hashlib import sha256
from pathlib import Path
from threading import Lock
from uuid import uuid4
from weakref import WeakKeyDictionary

from config import settings

# v9: 휠체어 사용자 요청에서 독립 TMAP 후보 network 수집을 제거하고,
# ODsay + ORS wheelchair만 실제 후보 공급자로 사용한다.
CACHE_SCHEMA_VERSION = 9
_write_locks: dict[str, Lock] = {}
_write_locks_guard = Lock()
_request_locks: WeakKeyDictionary = WeakKeyDictionary()
_request_locks_guard = Lock()


def _credential_fingerprint(value: str) -> str | None:
    normalized = value.strip()
    if not normalized or normalized.startswith("YOUR_"):
        return None
    return sha256(normalized.encode("utf-8")).hexdigest()


def cache_identity(
    origin_lat: float,
    origin_lng: float,
    dest_lat: float,
    dest_lng: float,
    *,
    avoid_stairs: bool = False,
    uses_wheelchair: bool = False,
) -> dict:
    return {
        "schemaVersion": CACHE_SCHEMA_VERSION,
        "origin": [round(origin_lat, 5), round(origin_lng, 5)],
        "destination": [round(dest_lat, 5), round(dest_lng, 5)],
        "geometryProfile": {
            "stairsExcluded": avoid_stairs,
            "wheelchairConstraints": uses_wheelchair,
            "orsRestrictionSchemaVersion": 1 if uses_wheelchair else None,
            "orsConfigured": bool(
                settings.ORS_API_KEY
                and not settings.ORS_API_KEY.startswith("YOUR_")
            ),
            "orsCredentialFingerprint": _credential_fingerprint(
                settings.ORS_API_KEY
            ),
            "odsayCredentialFingerprint": _credential_fingerprint(
                settings.ODSAY_API_KEY
            ),
            "odsayLoadLane": settings.ODSAY_LOAD_LANE_ENABLED,
            "tmapConfigured": not uses_wheelchair and bool(
                settings.TMAP_API_KEY
                and not settings.TMAP_API_KEY.startswith("YOUR_")
            ),
            "tmapRampEvidenceMode": (
                "cached_only" if uses_wheelchair else None
            ),
            "osmnxFallback": settings.OSMNX_WALK_GEOMETRY_ENABLED,
            "regionalDemPath": settings.ELEVATION_REGIONAL_DEM_PATH,
        },
    }


def _cache_path(identity: dict) -> Path | None:
    cache_dir = settings.ROUTE_FEATURE_CACHE_DIR.strip()
    if not cache_dir:
        return None
    digest = sha256(
        json.dumps(
            identity,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("ascii")
    ).hexdigest()
    return Path(cache_dir) / f"route-features-{digest}.json"


def _write_lock(path: Path) -> Lock:
    key = str(path.resolve())
    with _write_locks_guard:
        return _write_locks.setdefault(key, Lock())


def request_lock(identity: dict) -> asyncio.Lock:
    loop = asyncio.get_running_loop()
    key = json.dumps(identity, sort_keys=True, separators=(",", ":"))
    with _request_locks_guard:
        locks = _request_locks.setdefault(loop, {})
        return locks.setdefault(key, asyncio.Lock())


def read(
    identity: dict,
    *,
    minimum_candidate_limit: int,
) -> tuple[list[dict], dict] | None:
    path = _cache_path(identity)
    if path is None or not path.is_file():
        return None
    try:
        wrapper = json.loads(path.read_text(encoding="utf-8"))
        cached_at = float(wrapper["cachedAtEpoch"])
        candidate_limit = int(wrapper["candidateLimit"])
        route_features = wrapper["routeFeatures"]
        metadata = wrapper["metadata"]
    except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError):
        return None
    if (
        wrapper.get("schemaVersion") != CACHE_SCHEMA_VERSION
        or time.time() - cached_at > settings.ROUTE_FEATURE_CACHE_TTL_SECONDS
        or candidate_limit < minimum_candidate_limit
        or not isinstance(route_features, list)
        or not route_features
        or any(not isinstance(feature, dict) for feature in route_features)
        or not isinstance(metadata, dict)
    ):
        return None
    return route_features, metadata


def write(
    identity: dict,
    *,
    candidate_limit: int,
    route_features: list[dict],
    metadata: dict,
) -> None:
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
                        "schemaVersion": CACHE_SCHEMA_VERSION,
                        "cachedAtEpoch": time.time(),
                        "candidateLimit": candidate_limit,
                        "routeFeatures": route_features,
                        "metadata": metadata,
                    },
                    ensure_ascii=False,
                    separators=(",", ":"),
                ),
                encoding="utf-8",
            )
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)
