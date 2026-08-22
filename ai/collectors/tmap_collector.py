"""
TMAP 보행자 길찾기 수집기 (보조 소스).

보행자 특화 경로, 계단/엘리베이터 속성 세그먼트 단위 제공.
facilityType 필드: 계단/엘리베이터/에스컬레이터 직접 파악 가능.
키가 없거나 응답이 불완전하면 가짜 직선 경로를 만들지 않는다.
"""
import asyncio
import json
import logging
import time
from hashlib import sha256
from math import cos, isfinite, radians, sqrt
from pathlib import Path
from threading import Lock
from uuid import uuid4
from weakref import WeakKeyDictionary

import httpx

from config import settings
from collectors.base import (
    BaseRouteCollector,
    CollectorError,
    CollectorNotConfigured,
    Coordinate,
    RouteCandidate,
)

CACHE_SCHEMA_VERSION = 3
# 성공한 사전수집 응답은 운영 요청에서 다시 검증하지 않는다. 공급자 계약이나
# 정규화 규칙이 바뀌면 이 값을 올려 명시적으로 무효화한다.
ROUTE_DATA_VERSION = 1
STAIR_EXCLUDED_SEARCH_OPTION = "30"
DEFAULT_SEARCH_OPTION = "0"
STAIR_FACILITY_TYPE = 17
STAIR_TURN_TYPE = 127
RAMP_TURN_TYPES = frozenset({128, 129})
RAMP_FACILITY_TYPES = frozenset({19, 20})
STAIR_ALTERNATIVE_RAMP_TURN_TYPE = 129
STAIR_ALTERNATIVE_RAMP_FACILITY_TYPE = 20
MAX_RAMP_EVIDENCE_POINTS = 100
RAMP_PATH_MATCH_MAX_M = 20.0
QUOTA_BACKOFF_SECONDS = 2.0
NETWORK_ATTEMPTS = 2
RETRY_DELAY_SECONDS = 0.5
RETRYABLE_HTTP_STATUSES = frozenset({408, 425, 429, 500, 502, 503, 504})
log = logging.getLogger("collectors.tmap")
_cache_write_locks: dict[str, Lock] = {}
_cache_write_locks_guard = Lock()
_request_locks: WeakKeyDictionary = WeakKeyDictionary()
_request_semaphores: WeakKeyDictionary = WeakKeyDictionary()
_request_state_guard = Lock()
_quota_backoff_until = 0.0
_quota_backoff_guard = Lock()


def _response_json(response: httpx.Response) -> object:
    """TMAP이 POI 문자열에 넣는 비이스케이프 제어문자를 안전하게 읽는다.

    실제 200 응답에서 상호명 사이 NUL 문자가 확인됐다. 문자열 내부 제어문자만
    허용하고, 이후 후보 스키마·좌표·수치 검증은 기존과 동일하게 수행한다.
    """
    try:
        return response.json()
    except ValueError:
        content = getattr(response, "content", None)
        if not isinstance(content, (bytes, bytearray)):
            raise
        encoding = getattr(response, "encoding", None) or "utf-8"
        return json.loads(bytes(content).decode(encoding), strict=False)


def _point_to_path_distance_m(point: Coordinate, path: list[Coordinate]) -> float:
    """부산 범위의 짧은 구간을 국소 평면으로 투영해 선형까지 거리를 구한다."""
    latitude_scale = 111_320.0
    longitude_scale = latitude_scale * cos(radians(point.lat))

    def xy(value: Coordinate) -> tuple[float, float]:
        return (
            (value.lng - point.lng) * longitude_scale,
            (value.lat - point.lat) * latitude_scale,
        )

    best = float("inf")
    for start, end in zip(path, path[1:]):
        ax, ay = xy(start)
        bx, by = xy(end)
        dx, dy = bx - ax, by - ay
        denominator = dx * dx + dy * dy
        ratio = (
            max(0.0, min(1.0, -(ax * dx + ay * dy) / denominator))
            if denominator > 0
            else 0.0
        )
        nearest_x = ax + ratio * dx
        nearest_y = ay + ratio * dy
        best = min(best, sqrt(nearest_x * nearest_x + nearest_y * nearest_y))
    return best


def _cache_identity(
    origin: Coordinate,
    destination: Coordinate,
    *,
    search_option: str,
) -> dict:
    return {
        "origin": [round(origin.lat, 7), round(origin.lng, 7)],
        "destination": [
            round(destination.lat, 7),
            round(destination.lng, 7),
        ],
        "searchOption": search_option,
        "routeDataVersion": ROUTE_DATA_VERSION,
    }


def _cache_path(identity: dict, cache_dir: str) -> Path | None:
    if not cache_dir:
        return None
    digest = sha256(
        json.dumps(
            identity,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("ascii")
    ).hexdigest()
    return Path(cache_dir) / f"route-{digest}.json"


def _read_cache(identity: dict, validator=None) -> dict | None:
    cache_dirs = (
        settings.TMAP_CACHE_DIR.strip(),
        settings.TMAP_PRECOMPUTED_CACHE_DIR.strip(),
    )
    for cache_dir in dict.fromkeys(cache_dirs):
        path = _cache_path(identity, cache_dir)
        if path is None or not path.is_file():
            continue
        try:
            wrapper = json.loads(path.read_text(encoding="utf-8"))
            cached_at = float(wrapper["cachedAtEpoch"])
            payload = wrapper["payload"]
        except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError):
            continue
        if (
            wrapper.get("schemaVersion") == CACHE_SCHEMA_VERSION
            and isinstance(payload, dict)
            and time.time() - cached_at <= settings.TMAP_CACHE_TTL_SECONDS
        ):
            if validator is not None:
                try:
                    validator(payload)
                except CollectorError:
                    continue
            return payload
    return None


def _cache_write_lock(path: Path) -> Lock:
    key = str(path.resolve())
    with _cache_write_locks_guard:
        return _cache_write_locks.setdefault(key, Lock())


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
            asyncio.Semaphore(settings.TMAP_MAX_CONCURRENT_REQUESTS),
        )


def _quota_backoff_active() -> bool:
    with _quota_backoff_guard:
        return time.monotonic() < _quota_backoff_until


def _start_quota_backoff() -> None:
    global _quota_backoff_until
    with _quota_backoff_guard:
        _quota_backoff_until = max(
            _quota_backoff_until,
            time.monotonic() + QUOTA_BACKOFF_SECONDS,
        )


def _clear_quota_backoff() -> None:
    global _quota_backoff_until
    with _quota_backoff_guard:
        _quota_backoff_until = 0.0


def _write_cache_to_dir(identity: dict, payload: dict, cache_dir: str) -> None:
    path = _cache_path(identity, cache_dir)
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


def _write_cache(identity: dict, payload: dict) -> None:
    _write_cache_to_dir(identity, payload, settings.TMAP_CACHE_DIR.strip())


def write_precomputed_cache(
    origin: Coordinate,
    destination: Coordinate,
    *,
    search_option: str,
    payload: dict,
    cache_dir: Path,
) -> None:
    """검증된 공급자 응답을 24시간 이내 단기 캐시로 내보낸다.

    TMAP 약관상 장기 배포 자산으로 사용할 수 없으므로 읽는 시점에도
    ``TMAP_CACHE_TTL_SECONDS``를 적용한다.
    """
    collector = TmapRouteCollector(
        avoid_stairs=search_option == STAIR_EXCLUDED_SEARCH_OPTION
    )
    if collector.search_option != search_option:
        raise ValueError("지원하지 않는 TMAP searchOption입니다.")
    collector._candidate_from_data(payload)
    identity = _cache_identity(
        origin,
        destination,
        search_option=search_option,
    )
    _write_cache_to_dir(identity, payload, str(cache_dir))


class TmapRouteCollector(BaseRouteCollector):
    source_name = "tmap"
    BASE_URL = "https://apis.openapi.sk.com/tmap/routes/pedestrian"

    def __init__(self, *, avoid_stairs: bool = False):
        self.avoid_stairs = avoid_stairs

    @property
    def search_option(self) -> str:
        return (
            STAIR_EXCLUDED_SEARCH_OPTION
            if self.avoid_stairs
            else DEFAULT_SEARCH_OPTION
        )

    @staticmethod
    def _integer_code(value) -> int | None:
        if isinstance(value, bool) or value is None:
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    def _accessibility_evidence(self, features: list[dict]) -> dict:
        """TMAP 공식 안내 코드에서 물리 경사로와 계단을 추출한다."""
        ramp_points: list[dict] = []
        seen_ramp_points: set[tuple[float, float, bool]] = set()
        stair_feature_count = 0
        for feature in features:
            properties = feature.get("properties")
            geometry = feature.get("geometry")
            if not isinstance(properties, dict) or not isinstance(geometry, dict):
                raise CollectorError("TMAP 접근성 feature 계약이 올바르지 않습니다.")
            facility_type = self._integer_code(properties.get("facilityType"))
            turn_type = self._integer_code(properties.get("turnType"))
            if facility_type == STAIR_FACILITY_TYPE or turn_type == STAIR_TURN_TYPE:
                stair_feature_count += 1
            if (
                turn_type not in RAMP_TURN_TYPES
                and facility_type not in RAMP_FACILITY_TYPES
            ):
                continue
            coordinates = geometry.get("coordinates")
            geometry_type = geometry.get("type")
            if geometry_type == "Point":
                raw_points = [coordinates]
            elif geometry_type == "LineString":
                raw_points = coordinates
            else:
                raise CollectorError(
                    "TMAP 경사로 근거 geometry는 Point 또는 LineString이어야 합니다."
                )
            if not isinstance(raw_points, list) or not raw_points:
                raise CollectorError("TMAP 경사로 근거에 유효한 좌표가 없습니다.")
            replaces_stairs = (
                turn_type == STAIR_ALTERNATIVE_RAMP_TURN_TYPE
                or facility_type == STAIR_ALTERNATIVE_RAMP_FACILITY_TYPE
            )
            for raw_point in raw_points:
                if not isinstance(raw_point, list) or len(raw_point) < 2:
                    raise CollectorError(
                        "TMAP 경사로 근거에 유효한 좌표가 없습니다."
                    )
                try:
                    lng, lat = float(raw_point[0]), float(raw_point[1])
                except (TypeError, ValueError) as exc:
                    raise CollectorError(
                        "TMAP 경사로 근거 좌표가 숫자가 아닙니다."
                    ) from exc
                if not (
                    isfinite(lat)
                    and isfinite(lng)
                    and 33 <= lat <= 39
                    and 124 <= lng <= 132
                ):
                    raise CollectorError(
                        "TMAP 경사로 근거가 대한민국 범위를 벗어났습니다."
                    )
                point_key = (lat, lng, replaces_stairs)
                if point_key in seen_ramp_points:
                    continue
                seen_ramp_points.add(point_key)
                ramp_points.append({
                    "lat": lat,
                    "lng": lng,
                    "turn_type": turn_type,
                    "facility_type": facility_type,
                    "replaces_stairs": replaces_stairs,
                })
                if len(ramp_points) > MAX_RAMP_EVIDENCE_POINTS:
                    raise CollectorError(
                        "TMAP 경사로 근거가 응답 상한을 초과했습니다.",
                        code="invalid_response",
                        retryable=False,
                    )
        if self.avoid_stairs and stair_feature_count:
            raise CollectorError(
                "TMAP 계단 제외 경로에 계단 안내점이 포함되었습니다.",
                code="invalid_response",
                retryable=False,
            )
        return {
            "provider": "TMAP pedestrian",
            "search_option": self.search_option,
            "stairs_excluded_by_provider": self.avoid_stairs,
            "stair_feature_count": stair_feature_count,
            "ramp_points": ramp_points,
        }

    @staticmethod
    def _positive_number(value, field: str) -> float:
        if value is None or isinstance(value, bool):
            raise CollectorError(f"TMAP 응답의 {field}가 비어 있습니다.")
        try:
            number = float(value)
        except (TypeError, ValueError) as exc:
            raise CollectorError(
                f"TMAP 응답의 {field}가 숫자가 아닙니다."
            ) from exc
        if not isfinite(number) or number <= 0:
            raise CollectorError(
                f"TMAP 응답의 {field}는 유한한 양수여야 합니다."
            )
        return number

    def _candidate_from_data(self, data: dict) -> RouteCandidate:
        features = data.get("features")
        if not isinstance(features, list):
            raise CollectorError("TMAP 응답의 features가 배열이 아닙니다.")
        coords = []
        for feat in features:
            if not isinstance(feat, dict):
                raise CollectorError(
                    "TMAP 응답의 feature가 객체가 아닙니다."
                )
            geom = feat.get("geometry", {})
            if not isinstance(geom, dict):
                raise CollectorError(
                    "TMAP 응답의 geometry가 객체가 아닙니다."
                )
            properties = feat.get("properties", {})
            if not isinstance(properties, dict):
                raise CollectorError(
                    "TMAP 응답의 properties가 객체가 아닙니다."
                )
            if geom.get("type") == "LineString":
                geometry_coords = geom.get("coordinates")
                if not isinstance(geometry_coords, list):
                    raise CollectorError(
                        "TMAP LineString의 coordinates가 배열이 아닙니다."
                    )
                for lng, lat in geometry_coords:
                    point = Coordinate(lat=float(lat), lng=float(lng))
                    if not (
                        isfinite(point.lat)
                        and isfinite(point.lng)
                        and 33 <= point.lat <= 39
                        and 124 <= point.lng <= 132
                    ):
                        raise CollectorError(
                            "TMAP 응답에 대한민국 범위를 벗어난 좌표가 있습니다."
                        )
                    if not coords or coords[-1] != point:
                        coords.append(point)

        if len(coords) < 2:
            raise CollectorError("TMAP 응답에 유효한 경로 좌표가 없습니다.")

        props = next(
            (
                feature["properties"]
                for feature in features
                if feature.get("properties", {}).get("totalTime") is not None
            ),
            {},
        )
        duration = self._positive_number(
            props.get("totalTime"),
            "totalTime",
        ) / 60
        distance = self._positive_number(
            props.get("totalDistance"),
            "totalDistance",
        )
        accessibility_evidence = self._accessibility_evidence(features)
        for ramp in accessibility_evidence["ramp_points"]:
            ramp_point = Coordinate(lat=ramp["lat"], lng=ramp["lng"])
            if _point_to_path_distance_m(ramp_point, coords) > RAMP_PATH_MATCH_MAX_M:
                raise CollectorError(
                    "TMAP 경사로 안내점이 반환된 보행 선형과 일치하지 않습니다.",
                    code="invalid_response",
                    retryable=False,
                )
        return RouteCandidate(
            source=self.source_name,
            path=coords,
            duration_min=duration,
            distance_m=distance,
            raw_response=data,
            accessibility_evidence=accessibility_evidence,
        )

    async def collect(self, origin: Coordinate, destination: Coordinate) -> list:
        if not settings.TMAP_API_KEY or settings.TMAP_API_KEY.startswith("YOUR_"):
            raise CollectorNotConfigured("TMAP_API_KEY가 설정되지 않았습니다.")

        identity = _cache_identity(
            origin,
            destination,
            search_option=self.search_option,
        )
        cached = await asyncio.to_thread(
            _read_cache,
            identity,
            self._candidate_from_data,
        )
        if cached is not None:
            try:
                return [self._candidate_from_data(cached)]
            except CollectorError:
                # 스키마 계약 불일치 캐시는 공급자 실응답 갱신 대상이다.
                pass

        async with _request_lock(identity):
            # 동일 OD 요청은 잠금 안에서 캐시를 재확인해 공급자 호출을
            # 한 번으로 제한한다.
            cached = await asyncio.to_thread(
                _read_cache,
                identity,
                self._candidate_from_data,
            )
            if cached is not None:
                try:
                    return [self._candidate_from_data(cached)]
                except CollectorError:
                    pass
            if _quota_backoff_active():
                raise CollectorError(
                    "TMAP 호출 한도 대기 중"
                )
            for attempt in range(NETWORK_ATTEMPTS):
                try:
                    async with _request_semaphore():
                        if _quota_backoff_active():
                            raise CollectorError(
                                "TMAP 호출 한도 대기 중"
                            )
                        async with httpx.AsyncClient() as client:
                            resp = await client.post(self.BASE_URL, json={
                                "startX": origin.lng, "startY": origin.lat,
                                "endX": destination.lng, "endY": destination.lat,
                                "startName": "출발지", "endName": "도착지",
                                "reqCoordType": "WGS84GEO",
                                "resCoordType": "WGS84GEO",
                                "sort": "index",
                                "searchOption": self.search_option,
                            }, params={"version": "1"}, headers={
                                "appKey": settings.TMAP_API_KEY,
                                "Accept": "application/json",
                                "Content-Type": "application/json",
                            }, timeout=10.0)
                    resp.raise_for_status()
                    data = _response_json(resp)
                    if not isinstance(data, dict):
                        raise CollectorError(
                            "TMAP 응답 본문이 JSON 객체가 아닙니다.",
                            code="invalid_response",
                            retryable=False,
                        )
                    candidate = self._candidate_from_data(data)
                    try:
                        await asyncio.to_thread(_write_cache, identity, data)
                    except OSError as exc:
                        log.warning("TMAP 캐시 저장 실패 (%s)", type(exc).__name__)
                    return [candidate]
                except httpx.HTTPStatusError as exc:
                    status = exc.response.status_code
                    if (
                        status in RETRYABLE_HTTP_STATUSES
                        and attempt + 1 < NETWORK_ATTEMPTS
                    ):
                        log.warning(
                            "TMAP 일시 응답 실패 HTTP %d, 1회 재시도",
                            status,
                        )
                        await asyncio.sleep(RETRY_DELAY_SECONDS)
                        continue
                    if status == 429:
                        _start_quota_backoff()
                        raise CollectorError(
                            "TMAP 호출 한도 초과",
                            code="quota_exceeded",
                        ) from exc
                    raise CollectorError(
                        f"TMAP 호출 실패: HTTP {status}"
                    ) from exc
                except CollectorError:
                    raise
                except (httpx.HTTPError, ValueError, TypeError) as exc:
                    if attempt + 1 < NETWORK_ATTEMPTS:
                        log.warning(
                            "TMAP 일시 응답 처리 실패 (%s), 1회 재시도",
                            type(exc).__name__,
                        )
                        await asyncio.sleep(RETRY_DELAY_SECONDS)
                        continue
                    raise CollectorError(
                        f"TMAP 호출 또는 응답 처리 실패: {type(exc).__name__}"
                    ) from exc
            raise AssertionError("TMAP 재시도 루프가 결과 없이 종료되었습니다.")

    async def collect_cached(
        self,
        origin: Coordinate,
        destination: Coordinate,
    ) -> list[RouteCandidate]:
        """검증된 기존 TMAP 응답만 읽고 네트워크는 절대 호출하지 않는다.

        사용자 휠체어 요청의 물리 경사로 정보는 사전 수집 결과가 있을 때만
        보조 근거로 결합한다. 캐시 미스·계약 불일치는 미확인으로 남긴다.
        """
        identity = _cache_identity(
            origin,
            destination,
            search_option=self.search_option,
        )
        cached = await asyncio.to_thread(
            _read_cache,
            identity,
            self._candidate_from_data,
        )
        if cached is None:
            return []
        try:
            return [self._candidate_from_data(cached)]
        except CollectorError:
            return []
