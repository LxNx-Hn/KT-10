"""OpenRouteService wheelchair 경로 수집기.

TMAP의 ``searchOption=30``은 계단 제외와 물리 경사로 안내점 확인에 쓴다.
이 수집기는 별도로 ORS wheelchair profile의 노면·평탄도·폭·턱·경사·접근
제약을 적용한다. 두 근거는 같은 경로일 때만 merger에서 결합한다.

ORS는 OpenStreetMap 태그를 사용하므로 미매핑·임시 장애물을 현장 확인한 것으로
표현하지 않는다. 응답에는 적용한 제약과 데이터 한계를 함께 보존한다.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from hashlib import sha256
from math import isfinite
from pathlib import Path
from threading import Lock
from uuid import uuid4
from weakref import WeakKeyDictionary

import httpx

from collectors.base import (
    BaseRouteCollector,
    CollectorError,
    CollectorNotConfigured,
    Coordinate,
    RouteCandidate,
)
from config import settings

CACHE_SCHEMA_VERSION = 2
RESTRICTION_SCHEMA_VERSION = 1
PROFILE = "wheelchair"
AVOID_FEATURES = ("steps", "ferries")
WHEELCHAIR_RESTRICTIONS = {
    # ORS 공식 wheelchair routing option 값. 사용자가 작은 턱은 허용한다고
    # 했으므로 낮은 턱 기준인 3cm를 선택한다.
    "surface_type": "cobblestone:flattened",
    "track_type": "grade1",
    "smoothness_type": "good",
    "maximum_sloped_kerb": 0.03,
    "maximum_incline": 6,
    "minimum_width": 0.9,
}
EXTRA_INFO = ("steepness", "suitability", "surface", "waytype", "osmid")
EXTRA_RESPONSE_KEYS = {
    "steepness": ("steepness",),
    "suitability": ("suitability",),
    "surface": ("surface",),
    # 공식 설명 표는 waytype을 쓰지만 같은 페이지의 실제 응답 예시는
    # waytypes를 사용한다. 배포 버전 차이를 허용하되 다른 키는 받지 않는다.
    "waytype": ("waytype", "waytypes"),
    # ORS 공식 계약상 요청명 osmid와 응답명 osmId가 다르다.
    "osmid": ("osmId", "osmid"),
}
CONSTRAINT_CATEGORIES = (
    "steps",
    "surface",
    "track",
    "smoothness",
    "sloped_kerb",
    "incline",
    "width",
    "wheelchair_access",
)
DATA_LIMITATIONS = (
    "OpenStreetMap 접근성 태그가 누락되었을 수 있습니다.",
    "공사·적치물·고장 등 임시 또는 미매핑 장애물은 확인하지 못합니다.",
    "차단봉·문·게이트의 실제 개방 상태와 통과 폭은 확인하지 못할 수 있습니다.",
)

log = logging.getLogger("collectors.ors")
_cache_write_locks: dict[str, Lock] = {}
_cache_write_locks_guard = Lock()
_request_locks: WeakKeyDictionary = WeakKeyDictionary()
_request_semaphores: WeakKeyDictionary = WeakKeyDictionary()
_request_state_guard = Lock()


def _request_payload(origin: Coordinate, destination: Coordinate) -> dict:
    return {
        "coordinates": [
            [origin.lng, origin.lat],
            [destination.lng, destination.lat],
        ],
        "instructions": True,
        "elevation": True,
        "extra_info": list(EXTRA_INFO),
        "options": {
            "avoid_features": list(AVOID_FEATURES),
            "profile_params": {
                "restrictions": dict(WHEELCHAIR_RESTRICTIONS),
            },
        },
    }


def _cache_identity(origin: Coordinate, destination: Coordinate) -> dict:
    return {
        "origin": [round(origin.lat, 7), round(origin.lng, 7)],
        "destination": [
            round(destination.lat, 7),
            round(destination.lng, 7),
        ],
        "profile": PROFILE,
        "restrictionSchemaVersion": RESTRICTION_SCHEMA_VERSION,
        "restrictions": dict(WHEELCHAIR_RESTRICTIONS),
        "avoidFeatures": list(AVOID_FEATURES),
        "extraInfo": list(EXTRA_INFO),
    }


def _cache_path(identity: dict) -> Path | None:
    cache_dir = settings.ORS_CACHE_DIR.strip()
    if not cache_dir:
        return None
    digest = sha256(
        json.dumps(identity, sort_keys=True, separators=(",", ":")).encode(
            "ascii"
        )
    ).hexdigest()
    return Path(cache_dir) / f"route-{digest}.json"


def _read_cache(identity: dict) -> dict | None:
    path = _cache_path(identity)
    if path is None or not path.is_file():
        return None
    try:
        wrapper = json.loads(path.read_text(encoding="utf-8"))
        cached_at = float(wrapper["cachedAtEpoch"])
        payload = wrapper["payload"]
    except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError):
        return None
    if (
        wrapper.get("schemaVersion") != CACHE_SCHEMA_VERSION
        or not isinstance(payload, dict)
        or time.time() - cached_at > settings.ORS_CACHE_TTL_SECONDS
    ):
        return None
    return payload


def _cache_write_lock(path: Path) -> Lock:
    key = str(path.resolve())
    with _cache_write_locks_guard:
        return _cache_write_locks.setdefault(key, Lock())


def _write_cache(identity: dict, payload: dict) -> None:
    path = _cache_path(identity)
    if path is None:
        return
    with _cache_write_lock(path):
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
        try:
            temporary.write_text(
                json.dumps(
                    {
                        "schemaVersion": CACHE_SCHEMA_VERSION,
                        "cachedAtEpoch": time.time(),
                        "payload": payload,
                    },
                    ensure_ascii=False,
                    separators=(",", ":"),
                ),
                encoding="utf-8",
            )
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)


def _request_lock(identity: dict) -> asyncio.Lock:
    loop = asyncio.get_running_loop()
    key = json.dumps(identity, sort_keys=True, separators=(",", ":"))
    with _request_state_guard:
        locks = _request_locks.setdefault(loop, {})
        return locks.setdefault(key, asyncio.Lock())


def _request_semaphore() -> asyncio.Semaphore:
    loop = asyncio.get_running_loop()
    with _request_state_guard:
        return _request_semaphores.setdefault(
            loop,
            asyncio.Semaphore(settings.ORS_MAX_CONCURRENT_REQUESTS),
        )


class OrsWheelchairRouteCollector(BaseRouteCollector):
    source_name = "ors"

    @property
    def endpoint(self) -> str:
        return (
            f"{str(settings.ORS_BASE_URL).rstrip('/')}"
            f"/v2/directions/{PROFILE}/geojson"
        )

    @staticmethod
    def _positive_number(value, field: str) -> float:
        if value is None or isinstance(value, bool):
            raise CollectorError(
                f"ORS 응답의 {field}가 비어 있습니다.",
                code="invalid_response",
            )
        try:
            number = float(value)
        except (TypeError, ValueError) as exc:
            raise CollectorError(
                f"ORS 응답의 {field}가 숫자가 아닙니다.",
                code="invalid_response",
            ) from exc
        if not isfinite(number) or number <= 0:
            raise CollectorError(
                f"ORS 응답의 {field}는 유한한 양수여야 합니다.",
                code="invalid_response",
            )
        return number

    @staticmethod
    def _coordinates(geometry: dict) -> list[Coordinate]:
        values = geometry.get("coordinates")
        if geometry.get("type") != "LineString" or not isinstance(values, list):
            raise CollectorError(
                "ORS 응답에 LineString 경로가 없습니다.",
                code="empty_geometry",
            )
        path: list[Coordinate] = []
        for value in values:
            if not isinstance(value, list) or len(value) < 2:
                raise CollectorError(
                    "ORS 경로 좌표 형식이 올바르지 않습니다.",
                    code="invalid_response",
                )
            try:
                lng, lat = float(value[0]), float(value[1])
            except (TypeError, ValueError) as exc:
                raise CollectorError(
                    "ORS 경로 좌표가 숫자가 아닙니다.",
                    code="invalid_response",
                ) from exc
            if not (
                isfinite(lat)
                and isfinite(lng)
                and 33 <= lat <= 39
                and 124 <= lng <= 132
            ):
                raise CollectorError(
                    "ORS 경로 좌표가 대한민국 범위를 벗어났습니다.",
                    code="invalid_response",
                )
            point = Coordinate(lat=lat, lng=lng)
            if not path or path[-1] != point:
                path.append(point)
        if len(path) < 2:
            raise CollectorError(
                "ORS 응답에 유효한 경로 좌표가 없습니다.",
                code="empty_geometry",
            )
        return path

    @staticmethod
    def _validated_extra_info(
        extras: dict,
        *,
        waypoint_count: int,
    ) -> dict[str, str]:
        """요청별 실제 응답 키와 전체 geometry 구간 coverage를 검증한다."""
        resolved: dict[str, str] = {}
        edge_count = waypoint_count - 1
        for request_key, response_keys in EXTRA_RESPONSE_KEYS.items():
            response_key = next(
                (key for key in response_keys if key in extras),
                None,
            )
            if response_key is None:
                raise CollectorError(
                    f"ORS extra_info가 누락되었습니다: {request_key}",
                    code="invalid_response",
                )
            item = extras.get(response_key)
            if not isinstance(item, dict):
                raise CollectorError(
                    f"ORS extra_info {response_key}가 객체가 아닙니다.",
                    code="invalid_response",
                )
            values = item.get("values")
            summary = item.get("summary")
            if not isinstance(values, list) or not values:
                raise CollectorError(
                    f"ORS extra_info {response_key} 구간이 비어 있습니다.",
                    code="invalid_response",
                )
            if not isinstance(summary, list):
                raise CollectorError(
                    f"ORS extra_info {response_key} summary가 배열이 아닙니다.",
                    code="invalid_response",
                )
            covered = [False] * edge_count
            for value in values:
                if (
                    not isinstance(value, list)
                    or len(value) != 3
                    or isinstance(value[0], bool)
                    or isinstance(value[1], bool)
                    or not isinstance(value[0], int)
                    or not isinstance(value[1], int)
                    or not 0 <= value[0] < value[1] < waypoint_count
                ):
                    raise CollectorError(
                        f"ORS extra_info {response_key} 구간 형식이 "
                        "올바르지 않습니다.",
                        code="invalid_response",
                    )
                for index in range(value[0], value[1]):
                    covered[index] = True
            if not all(covered):
                raise CollectorError(
                    f"ORS extra_info {response_key}가 경로 전체를 "
                    "포함하지 않습니다.",
                    code="invalid_response",
                )
            resolved[request_key] = response_key
        return resolved

    def _candidate_from_data(self, data: dict) -> RouteCandidate:
        if data.get("type") != "FeatureCollection":
            raise CollectorError(
                "ORS 응답이 FeatureCollection이 아닙니다.",
                code="invalid_response",
            )
        features = data.get("features")
        if not isinstance(features, list) or len(features) != 1:
            raise CollectorError(
                "ORS 응답에는 정확히 한 개의 경로가 있어야 합니다.",
                code="invalid_response",
            )
        feature = features[0]
        if not isinstance(feature, dict) or feature.get("type") != "Feature":
            raise CollectorError(
                "ORS 경로 feature 계약이 올바르지 않습니다.",
                code="invalid_response",
            )
        geometry = feature.get("geometry")
        properties = feature.get("properties")
        if not isinstance(geometry, dict) or not isinstance(properties, dict):
            raise CollectorError(
                "ORS geometry/properties 계약이 올바르지 않습니다.",
                code="invalid_response",
            )
        summary = properties.get("summary")
        extras = properties.get("extras")
        segments = properties.get("segments")
        if not isinstance(summary, dict) or not isinstance(extras, dict):
            raise CollectorError(
                "ORS summary/extra_info가 누락되었습니다.",
                code="invalid_response",
            )
        if not isinstance(segments, list) or not segments:
            raise CollectorError(
                "ORS 보행 안내 구간이 누락되었습니다.",
                code="invalid_response",
            )
        path = self._coordinates(geometry)
        response_extra_keys = self._validated_extra_info(
            extras,
            # extra_info 인덱스는 중복 정점을 정리한 내부 path가 아니라 ORS
            # 원본 geometry 좌표 배열을 기준으로 한다.
            waypoint_count=len(geometry["coordinates"]),
        )
        distance = self._positive_number(summary.get("distance"), "distance")
        duration = self._positive_number(summary.get("duration"), "duration")
        evidence = {
            "providers": ["openrouteservice wheelchair"],
            "wheelchair_profile": PROFILE,
            "wheelchair_constraints_applied": True,
            "wheelchair_restrictions": dict(WHEELCHAIR_RESTRICTIONS),
            "wheelchair_constraint_categories": list(CONSTRAINT_CATEGORIES),
            "avoided_features": list(AVOID_FEATURES),
            "verified_extra_info": list(EXTRA_INFO),
            "verified_extra_response_keys": response_extra_keys,
            "extra_info_full_route_coverage": True,
            # ORS wheelchair profile이 지도에 기록된 steps를 탐색에서 제외한
            # 결과다. OSM 누락까지 현장 확인한 값은 아니므로 계단 수를 0으로
            # 만들지 않는다.
            "stairs_excluded_by_provider": True,
            "wheelchair_data_limitations": list(DATA_LIMITATIONS),
        }
        return RouteCandidate(
            source=self.source_name,
            path=path,
            duration_min=duration / 60,
            distance_m=distance,
            raw_response=data,
            accessibility_evidence=evidence,
        )

    async def collect(
        self,
        origin: Coordinate,
        destination: Coordinate,
    ) -> list[RouteCandidate]:
        api_key = settings.ORS_API_KEY.strip()
        if not api_key or api_key.startswith("YOUR_"):
            raise CollectorNotConfigured("ORS_API_KEY가 설정되지 않았습니다.")
        identity = _cache_identity(origin, destination)
        cached = await asyncio.to_thread(_read_cache, identity)
        if cached is not None:
            try:
                return [self._candidate_from_data(cached)]
            except CollectorError:
                pass

        async with _request_lock(identity):
            cached = await asyncio.to_thread(_read_cache, identity)
            if cached is not None:
                try:
                    return [self._candidate_from_data(cached)]
                except CollectorError:
                    pass
            try:
                async with _request_semaphore():
                    async with httpx.AsyncClient(
                        follow_redirects=False,
                        timeout=settings.ORS_TIMEOUT_SECONDS,
                    ) as client:
                        response = await client.post(
                            self.endpoint,
                            headers={
                                "Authorization": api_key,
                                "Accept": "application/geo+json, application/json",
                                "Content-Type": "application/json",
                            },
                            json=_request_payload(origin, destination),
                        )
                response.raise_for_status()
                data = response.json()
                if not isinstance(data, dict):
                    raise CollectorError(
                        "ORS 응답 본문이 JSON 객체가 아닙니다.",
                        code="invalid_response",
                    )
                candidate = self._candidate_from_data(data)
                try:
                    await asyncio.to_thread(_write_cache, identity, data)
                except OSError as exc:
                    log.warning("ORS 캐시 저장 실패 (%s)", type(exc).__name__)
                return [candidate]
            except httpx.HTTPStatusError as exc:
                status = exc.response.status_code
                if status in {401, 403}:
                    raise CollectorError(
                        f"ORS 인증 실패: HTTP {status}",
                        code="auth_failed",
                        retryable=False,
                    ) from exc
                if status == 429:
                    raise CollectorError(
                        "ORS 호출 한도 초과",
                        code="quota_exceeded",
                        retryable=False,
                    ) from exc
                raise CollectorError(
                    f"ORS 호출 실패: HTTP {status}",
                    code="provider_error",
                ) from exc
            except CollectorError:
                raise
            except (httpx.HTTPError, ValueError, TypeError) as exc:
                raise CollectorError(
                    f"ORS 호출 또는 응답 처리 실패: {type(exc).__name__}"
                ) from exc
