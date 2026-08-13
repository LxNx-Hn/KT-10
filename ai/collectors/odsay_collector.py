"""
ODsay 대중교통 경로 수집기 (메인 소스).

ODsay Lab API로 대중교통 경로 후보를 수집한다.
버스·지하철 환승 정보, 정류장 좌표를 세그먼트 단위로 제공.
키가 없거나 응답이 불완전하면 가짜 경로를 만들지 않고 명시적으로 실패한다.

API 문서: https://lab.odsay.com/guide/service
"""
import asyncio
import csv
import json
import logging
import math
import re
import time
from dataclasses import dataclass
from hashlib import sha256
from math import isfinite
from pathlib import Path
from threading import Lock
from uuid import uuid4

import httpx
from config import settings

from collectors.base import (
    BaseRouteCollector,
    CollectorError,
    CollectorNotConfigured,
    Coordinate,
    RouteCandidate,
)
from collectors.odsay_instrumentation import (
    anonymized_hash,
    ensure_correlation_id,
    record_network_call,
    single_flight,
    with_concurrency_limit,
)
from collectors.odsay_instrumentation import (
    counters as odsay_counters,
)
from collectors.odsay_instrumentation import (
    log_call as log_odsay_call,
)
from merger.route_merger import (
    accessibility_paths_similar,
    merge_accessibility_evidence,
)

def _provider_error_code(data: dict) -> str:
    """ODsay 오류 응답 코드를 재시도 정책 분류로 옮긴다."""
    error = data.get("error")
    raw = str(error.get("code") if isinstance(error, dict) else "") or ""
    # ODsay 규격: 8=일일 사용량 초과, 9=서비스 키 오류, 500대=서버 오류
    if raw in {"8", "18"}:
        return "quota_exceeded"
    if raw in {"9", "10", "11"}:
        return "auth_failed"
    if raw.startswith("5"):
        return "upstream_5xx"
    return "invalid_response"


def _transport_error_code(exc: BaseException) -> str:
    if isinstance(exc, httpx.TimeoutException):
        return "timeout"
    if isinstance(exc, httpx.HTTPStatusError):
        status = exc.response.status_code
        if status in {401, 403}:
            return "auth_failed"
        if status == 429:
            return "quota_exceeded"
        if status >= 500:
            return "upstream_5xx"
        return "invalid_response"
    if isinstance(exc, httpx.TransportError):
        return "network_error"
    return "invalid_response"


CACHE_SCHEMA_VERSION = 2
# 후보 조립 병렬 상한. 아직 필요한 후보 수가 이보다 적으면 그 수만큼만 묶는다.
BUILD_BATCH_SIZE = 3
log = logging.getLogger("collectors.odsay")
_walk_geometry_failure_signatures: set[tuple[str, str]] = set()
_walk_geometry_failure_signatures_guard = Lock()

ACCESSIBLE_EXIT_COORDINATES_PATH = (
    Path(__file__).resolve().parents[2]
    / "data"
    / "raw"
    / "busan_subway_accessible_exit_coordinates_20260813.csv"
)


@dataclass(frozen=True)
class AccessibleSubwayExit:
    exit_no: str
    coordinate: Coordinate
    osm_node_id: int


@dataclass(frozen=True)
class WalkGeometryResult:
    path: list[Coordinate]
    quality: str
    accessibility_evidence: dict
    duration_min: float | None = None
    distance_m: float | None = None

    def __iter__(self):
        # 기존 호출부의 세 값 unpacking 계약을 유지한다.
        yield self.path
        yield self.quality
        yield self.accessibility_evidence


def _station_key(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = re.sub(r"[\s()\[\]·.-]", "", value).removesuffix("역")
    return normalized.casefold() or None


def _subway_line(sub_path: dict) -> int | None:
    lanes = sub_path.get("lane")
    for lane in lanes if isinstance(lanes, list) else []:
        if not isinstance(lane, dict):
            continue
        code = lane.get("subwayCode")
        if isinstance(code, int) and 71 <= code <= 74:
            return code - 70
        name = lane.get("name")
        matched = re.search(r"([1-4])\s*호선", str(name or ""))
        if matched:
            return int(matched.group(1))
    return None


def _load_accessible_subway_exits() -> dict[
    tuple[int, str], tuple[AccessibleSubwayExit, ...]
]:
    if not ACCESSIBLE_EXIT_COORDINATES_PATH.is_file():
        return {}
    grouped: dict[tuple[int, str], list[AccessibleSubwayExit]] = {}
    with ACCESSIBLE_EXIT_COORDINATES_PATH.open(
        encoding="utf-8",
        newline="",
    ) as handle:
        for row in csv.DictReader(handle):
            station = _station_key(row.get("station_name"))
            try:
                line = int(row["station_line"])
                exit_no = str(int(row["exit_no"]))
                coordinate = Coordinate(
                    lat=float(row["lat"]),
                    lng=float(row["lng"]),
                )
                node_id = int(row["osm_node_id"])
            except (KeyError, TypeError, ValueError) as exc:
                raise RuntimeError(
                    "접근 가능 도시철도 출구 좌표 파일이 올바르지 않습니다."
                ) from exc
            if station is None or not 1 <= line <= 4:
                raise RuntimeError(
                    "접근 가능 도시철도 출구의 역명·호선이 올바르지 않습니다."
                )
            grouped.setdefault((line, station), []).append(
                AccessibleSubwayExit(exit_no, coordinate, node_id)
            )
    return {
        key: tuple(sorted(values, key=lambda value: (int(value.exit_no), value.osm_node_id)))
        for key, values in grouped.items()
    }


ACCESSIBLE_SUBWAY_EXITS = _load_accessible_subway_exits()


def _cache_path(kind: str, identity: dict) -> Path | None:
    cache_dir = settings.ODSAY_CACHE_DIR.strip()
    if not cache_dir:
        return None
    digest = sha256(
        json.dumps(
            {"kind": kind, **identity},
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    return Path(cache_dir) / f"{kind}-{digest}.json"


def _read_cache(kind: str, identity: dict) -> dict | None:
    path = _cache_path(kind, identity)
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
        or time.time() - cached_at > settings.ODSAY_CACHE_TTL_SECONDS
    ):
        return None
    return payload


def _write_cache(kind: str, identity: dict, payload: dict) -> None:
    path = _cache_path(kind, identity)
    if path is None:
        return
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


async def _cached_payload(kind: str, identity: dict) -> dict | None:
    return await asyncio.to_thread(_read_cache, kind, identity)


async def _store_payload(kind: str, identity: dict, payload: dict) -> None:
    try:
        await asyncio.to_thread(_write_cache, kind, identity, payload)
    except OSError as exc:
        log.warning("ODsay 캐시 저장 실패 (%s)", type(exc).__name__)


class OdsayRouteCollector(BaseRouteCollector):
    source_name = "odsay"
    BASE_URL = "https://api.odsay.com/v1/api/searchPubTransPathT"
    LANE_URL = "https://api.odsay.com/v1/api/loadLane"

    def __init__(
        self,
        *,
        avoid_stairs: bool = False,
        uses_wheelchair: bool = False,
        accessible_subway_exits: dict[
            tuple[int, str], tuple[AccessibleSubwayExit, ...]
        ] | None = None,
    ):
        self.avoid_stairs = avoid_stairs
        self.uses_wheelchair = uses_wheelchair
        self.accessible_subway_exits = (
            ACCESSIBLE_SUBWAY_EXITS
            if accessible_subway_exits is None
            else accessible_subway_exits
        )
        # 한 사용자 요청에서 후보들이 같은 실제 도보 구간을 공유하면 ORS
        # wheelchair 계산과 cached-only 보조 결합을 동일 Task로 합친다.
        self._walk_geometry_tasks: dict[
            tuple[float, float, float, float, bool, bool],
            asyncio.Task[WalkGeometryResult],
        ] = {}

    def _walk_geometry_identity(
        self,
        start: Coordinate,
        end: Coordinate,
    ) -> tuple[float, float, float, float, bool, bool]:
        return (
            round(start.lat, 7),
            round(start.lng, 7),
            round(end.lat, 7),
            round(end.lng, 7),
            self.uses_wheelchair,
            self.avoid_stairs,
        )

    async def _shared_walk_geometry(
        self,
        start: Coordinate,
        end: Coordinate,
    ) -> WalkGeometryResult:
        identity = self._walk_geometry_identity(start, end)
        task = self._walk_geometry_tasks.get(identity)
        if task is None:
            task = asyncio.create_task(self._walk_geometry(start, end))
            self._walk_geometry_tasks[identity] = task
        return await asyncio.shield(task)

    def _accessible_exit(
        self,
        sub_path: dict,
        side: str,
        anchor: Coordinate,
    ) -> AccessibleSubwayExit | None:
        line = _subway_line(sub_path)
        station = _station_key(sub_path.get(f"{side}Name"))
        candidates = (
            self.accessible_subway_exits.get((line, station), ())
            if line is not None and station is not None
            else ()
        )
        if not candidates:
            return None
        longitude_scale = math.cos(math.radians(anchor.lat))
        return min(
            candidates,
            key=lambda candidate: (
                (candidate.coordinate.lat - anchor.lat) ** 2
                + (
                    (candidate.coordinate.lng - anchor.lng)
                    * longitude_scale
                ) ** 2,
                int(candidate.exit_no),
                candidate.osm_node_id,
            ),
        )

    def _apply_accessible_subway_exits(
        self,
        sub_paths: list[dict],
        origin: Coordinate,
        destination: Coordinate,
    ) -> list[dict]:
        """첫·마지막 도시철도 지상 접점을 공식 접근 가능 출구로 바꾼다.

        공식 동선에 포함된 출구만 사용하고, 좌표가 없는 역은 ODsay 값을
        그대로 둬 후단의 닫힌 검증에서 제외되게 한다. 캐시 원문을 변경하지
        않도록 후보의 subPath를 복사한다.
        """
        copied = [dict(sub_path) for sub_path in sub_paths]
        if not self.uses_wheelchair:
            return copied
        transit_indices = [
            index
            for index, sub_path in enumerate(copied)
            if sub_path.get("trafficType") != 3
        ]
        if not transit_indices:
            return copied
        first = copied[transit_indices[0]]
        if first.get("trafficType") == 1:
            selected = self._accessible_exit(first, "start", origin)
            if selected is not None:
                first.update({
                    "startExitNo": selected.exit_no,
                    "startExitX": selected.coordinate.lng,
                    "startExitY": selected.coordinate.lat,
                    "startExitCoordinateSource": "OpenStreetMap ODbL 1.0",
                    "startExitOsmNodeId": selected.osm_node_id,
                })
        last = copied[transit_indices[-1]]
        if last.get("trafficType") == 1:
            selected = self._accessible_exit(last, "end", destination)
            if selected is not None:
                last.update({
                    "endExitNo": selected.exit_no,
                    "endExitX": selected.coordinate.lng,
                    "endExitY": selected.coordinate.lat,
                    "endExitCoordinateSource": "OpenStreetMap ODbL 1.0",
                    "endExitOsmNodeId": selected.osm_node_id,
                })
        return copied

    @staticmethod
    def _api_error(data: dict) -> str | None:
        error = data.get("error")
        if isinstance(error, dict):
            return str(error.get("msg") or error.get("message") or error.get("code") or "ODsay API 오류")
        if error:
            return str(error)
        return None

    @staticmethod
    def _map_base(map_object: str) -> tuple[float, float]:
        try:
            x, y = map_object.split("@", 1)[0].split(":", 1)
            return float(x), float(y)
        except (AttributeError, TypeError, ValueError) as exc:
            raise CollectorError("ODsay mapObject의 기준 좌표 형식이 올바르지 않습니다.") from exc

    @staticmethod
    def _load_lane_map_object(map_object: str) -> str:
        """검색 응답의 축약 mapObj를 loadLane 요청 형식으로 정규화한다."""
        if not isinstance(map_object, str) or not map_object.strip():
            raise CollectorError("ODsay mapObject가 비어 있습니다.")
        value = map_object.strip()
        # searchPubTransPathT는 부산 버스 단일 구간처럼 기준점 없이
        # ``ID:Class:StartIdx:EndIdx`` 노선 토큰 하나 이상을 반환할 수 있다.
        # 기준점은 ``BaseX:BaseY`` 두 필드이고 노선 토큰은 네 필드이므로,
        # 첫 토큰의 필드 수로 이미 기준점이 포함되었는지 판별한다.
        first_token = value.split("@", 1)[0]
        has_base = len(first_token.split(":")) == 2
        route_tokens = value.split("@")[1:] if has_base else value.split("@")
        if not route_tokens or any(
            len(token.split(":")) != 4 for token in route_tokens
        ):
            raise CollectorError(
                "ODsay mapObject의 노선 토큰 형식이 올바르지 않습니다."
            )
        return value if has_base else f"0:0@{value}"

    @classmethod
    def _lane_paths(cls, data: dict, map_object: str) -> list[list[Coordinate]]:
        base_x, base_y = cls._map_base(map_object)
        paths: list[list[Coordinate]] = []
        result = data.get("result")
        lanes = result.get("lane") if isinstance(result, dict) else None
        if not isinstance(lanes, list):
            return []
        for lane in lanes:
            lane_coords: list[Coordinate] = []
            sections = lane.get("section") if isinstance(lane, dict) else None
            for section in sections if isinstance(sections, list) else []:
                points = (
                    section.get("graphPos")
                    if isinstance(section, dict)
                    else None
                )
                for point in points if isinstance(points, list) else []:
                    try:
                        lng, lat = float(point["x"]), float(point["y"])
                    except (KeyError, TypeError, ValueError):
                        continue
                    # ODsay 문서상 graphPos는 mapObject의 BaseX/BaseY를 뺀 값일 수 있다.
                    if not 124.0 <= lng <= 132.0:
                        lng += base_x
                    if not 33.0 <= lat <= 39.0:
                        lat += base_y
                    if 124.0 <= lng <= 132.0 and 33.0 <= lat <= 39.0:
                        point_obj = Coordinate(lat=lat, lng=lng)
                        if not lane_coords or lane_coords[-1] != point_obj:
                            lane_coords.append(point_obj)
            # 빈 lane도 위치를 보존해야 뒤의 유효 lane이 앞 교통구간으로
            # 잘못 이동하지 않는다. 후보 조립 단계에서 해당 후보를 제외한다.
            paths.append(lane_coords if len(lane_coords) >= 2 else [])
        return paths

    @classmethod
    def _lane_coordinates(cls, data: dict, map_object: str) -> list[Coordinate]:
        return [point for path in cls._lane_paths(data, map_object) for point in path]

    @classmethod
    def _estimated_transit_path(cls, sub_path: dict) -> list[Coordinate]:
        """정류장 관측 좌표만 연결한 표시용 추정 선형을 만든다.

        도로 선형으로 위장하지 않으며 호출자는 geometry_quality를 반드시
        estimated로 기록해야 한다. 보행 경사·그늘 분석에는 사용하지 않는다.
        """
        raw_stations = sub_path.get("passStopList")
        stations = (
            raw_stations.get("stations")
            if isinstance(raw_stations, dict)
            else None
        )
        coordinates: list[Coordinate] = []
        start = cls._point(sub_path.get("startX"), sub_path.get("startY"))
        end = cls._point(sub_path.get("endX"), sub_path.get("endY"))
        station_coordinates = (
            [
                cls._point(station.get("x"), station.get("y"))
                for station in stations
                if isinstance(station, dict)
            ]
            if isinstance(stations, list)
            else []
        )
        for coordinate in (
            start,
            *station_coordinates,
            end,
        ):
            if coordinate is not None and (
                not coordinates or coordinates[-1] != coordinate
            ):
                coordinates.append(coordinate)
        return coordinates if len(coordinates) >= 2 else []

    async def _load_lane(
        self,
        map_object: str,
        origin: Coordinate,
        destination: Coordinate,
        *,
        call_site: str,
    ) -> list[list[Coordinate]]:
        margin = 0.02
        load_lane_map_object = self._load_lane_map_object(map_object)
        request_params = {
            "mapObject": load_lane_map_object,
            "left": min(origin.lng, destination.lng) - margin,
            "top": max(origin.lat, destination.lat) + margin,
            "right": max(origin.lng, destination.lng) + margin,
            "bottom": min(origin.lat, destination.lat) - margin,
            "apiKey": settings.ODSAY_API_KEY,
        }
        cache_identity = {
            "mapObject": load_lane_map_object,
            "left": round(float(request_params["left"]), 5),
            "top": round(float(request_params["top"]), 5),
            "right": round(float(request_params["right"]), 5),
            "bottom": round(float(request_params["bottom"]), 5),
        }
        identity_hash = anonymized_hash(
            json.dumps(cache_identity, sort_keys=True)
        )
        started_at = time.monotonic()
        data = await _cached_payload("lane", cache_identity)
        cache_hit = data is not None
        network = False
        follower = False
        semaphore_wait = 0.0
        http_status: int | None = None
        outcome = "cache"
        try:
            if not cache_hit:
                async def _fetch() -> dict:
                    nonlocal network, semaphore_wait, http_status
                    # single-flight leader 안에서 다시 캐시를 확인해
                    # 직전 leader가 저장한 결과를 재사용한다.
                    cached = await _cached_payload("lane", cache_identity)
                    if cached is not None:
                        return cached

                    async def _request() -> dict:
                        nonlocal http_status, network
                        # semaphore를 얻은 뒤, 실제 transport 직전에만
                        # network 호출로 집계한다. 대기 중 취소·timeout은
                        # 실제 호출이 아니다.
                        async with httpx.AsyncClient(
                            follow_redirects=True
                        ) as client:
                            record_network_call("loadLane")
                            network = True
                            odsay_counters.record_network_attempt("loadLane")
                            try:
                                response = await client.get(
                                    self.LANE_URL,
                                    params=request_params,
                                    timeout=8.0,
                                )
                            except BaseException:
                                odsay_counters.record_network_result(
                                    "loadLane", completed=False
                                )
                                raise
                        odsay_counters.record_network_result(
                            "loadLane", completed=True
                        )
                        http_status = getattr(
                            response, "status_code", None
                        )
                        response.raise_for_status()
                        payload = response.json()
                        return payload

                    fetched, waited = await with_concurrency_limit(_request)
                    semaphore_wait = waited
                    return fetched

                data, follower = await single_flight(
                    f"lane:{identity_hash}",
                    _fetch,
                )
                outcome = "network" if network else "single-flight"
            if not isinstance(data, dict):
                raise CollectorError(
                    "ODsay loadLane 응답 본문이 JSON 객체가 아닙니다.",
                    code="invalid_response",
                )
            api_error = self._api_error(data)
            if api_error:
                # 공급자 오류 응답은 캐시하지 않고 그대로 실패로 반환한다.
                raise CollectorError(
                    f"ODsay loadLane 실패: {api_error}",
                    code=_provider_error_code(data),
                )
            paths = self._lane_paths(data, load_lane_map_object)
            if not paths or not any(paths):
                raise CollectorError(
                    "ODsay loadLane 응답에 유효한 경로 좌표가 없습니다.",
                    code="empty_geometry",
                )
            if network:
                await _store_payload("lane", cache_identity, data)
            return paths
        except BaseException:
            outcome = "error"
            raise
        finally:
            odsay_counters.record(
                "loadLane",
                network=network,
                cache_hit=cache_hit,
                follower=follower,
                semaphore_wait=semaphore_wait,
            )
            log_odsay_call(
                "loadLane",
                identity_hash=identity_hash,
                cache_hit=cache_hit,
                network=network,
                follower=follower,
                duration_ms=(time.monotonic() - started_at) * 1000,
                outcome=outcome,
                call_site=call_site,
                http_status=http_status,
                semaphore_wait=semaphore_wait,
            )

    async def refine_transit(
        self,
        map_object: str,
        origin: Coordinate,
        destination: Coordinate,
    ) -> list[list[Coordinate]]:
        """선택된 후보 하나의 대중교통 정밀 선형만 조회한다.

        검색이나 전체 후보 수집을 다시 실행하지 않는다.
        """
        if not settings.ODSAY_API_KEY or settings.ODSAY_API_KEY.startswith(
            "YOUR_"
        ):
            raise CollectorNotConfigured("ODSAY_API_KEY가 설정되지 않았습니다.")
        ensure_correlation_id()
        try:
            return await asyncio.wait_for(
                self._load_lane(
                    map_object,
                    origin,
                    destination,
                    call_site="refine_transit",
                ),
                timeout=settings.ODSAY_TIMEOUT_SECONDS,
            )
        except TimeoutError as exc:
            raise CollectorError(
                "ODsay 대중교통 정밀 선형 조회가 시간 제한을 초과했습니다.",
                code="timeout",
            ) from exc

    @staticmethod
    def _number(
        value,
        field: str,
        *,
        positive: bool,
    ) -> float:
        if value is None or isinstance(value, bool):
            raise CollectorError(f"ODsay 응답의 {field}가 비어 있습니다.")
        try:
            number = float(value)
        except (TypeError, ValueError) as exc:
            raise CollectorError(
                f"ODsay 응답의 {field}가 숫자가 아닙니다."
            ) from exc
        if (
            not isfinite(number)
            or (positive and number <= 0)
            or (not positive and number < 0)
        ):
            condition = "0보다 커야" if positive else "0 이상이어야"
            raise CollectorError(
                f"ODsay 응답의 {field}는 {condition} 합니다."
            )
        return number

    @staticmethod
    def _point(x, y) -> Coordinate | None:
        try:
            lng, lat = float(x), float(y)
        except (TypeError, ValueError):
            return None
        return Coordinate(lat=lat, lng=lng) if 124 <= lng <= 132 and 33 <= lat <= 39 else None

    @classmethod
    def _transit_edge(cls, sub_path: dict, side: str) -> Coordinate | None:
        if side == "start":
            return cls._point(
                sub_path.get("startExitX", sub_path.get("startX")),
                sub_path.get("startExitY", sub_path.get("startY")),
            )
        return cls._point(
            sub_path.get("endExitX", sub_path.get("endX")),
            sub_path.get("endExitY", sub_path.get("endY")),
        )

    @classmethod
    def _walk_endpoints(
        cls,
        sub_paths: list[dict],
        index: int,
        origin: Coordinate,
        destination: Coordinate,
    ) -> tuple[Coordinate, Coordinate] | None:
        previous = next((item for item in reversed(sub_paths[:index]) if item.get("trafficType") != 3), None)
        following = next((item for item in sub_paths[index + 1:] if item.get("trafficType") != 3), None)
        start = cls._transit_edge(previous, "end") if previous else origin
        end = cls._transit_edge(following, "start") if following else destination
        return (start, end) if start and end else None

    async def _walk_geometry(
        self,
        start: Coordinate,
        end: Coordinate,
    ) -> WalkGeometryResult:
        # 휠체어는 ORS wheelchair profile이 확인한 선형을 기준으로 삼는다.
        # TMAP은 같은 선형일 때만 물리 경사로 안내점 근거를 보탠다.
        if self.uses_wheelchair:
            from collectors.ors_collector import OrsWheelchairRouteCollector

            ors_candidates = await OrsWheelchairRouteCollector().collect(
                start,
                end,
            )
            if not ors_candidates or len(ors_candidates[0].path) < 2:
                raise CollectorError(
                    "ORS wheelchair 보행 경로가 비어 있습니다.",
                    code="empty_geometry",
                )
            primary = ors_candidates[0]
            evidence = dict(primary.accessibility_evidence)
            from collectors.tmap_collector import TmapRouteCollector

            # TMAP은 요청 시 네트워크를 호출하지 않는다. 사전 수집된 캐시가
            # 있고 ORS 선형과 일치할 때만 물리 경사로 안내점을 보탠다.
            tmap_candidates = await TmapRouteCollector(
                avoid_stairs=True
            ).collect_cached(start, end)
            if (
                tmap_candidates
                and accessibility_paths_similar(
                    primary.path,
                    tmap_candidates[0].path,
                )
            ):
                evidence = merge_accessibility_evidence(
                    evidence,
                    tmap_candidates[0].accessibility_evidence,
                )
            return WalkGeometryResult(
                primary.path,
                "exact",
                evidence,
                duration_min=getattr(primary, "duration_min", None),
                distance_m=getattr(primary, "distance_m", None),
            )

        # 일반 보행은 TMAP 공식 보행 경로를 우선하고, OSMnx는 명시적으로
        # 활성화한 환경의 보조 공급자다.
        from collectors.tmap_collector import TmapRouteCollector

        collectors = []
        if settings.TMAP_API_KEY and not settings.TMAP_API_KEY.startswith("YOUR_"):
            collectors.append(
                TmapRouteCollector(avoid_stairs=self.avoid_stairs)
            )
        if settings.OSMNX_WALK_GEOMETRY_ENABLED:
            from collectors.osmnx_collector import OsmnxRouteCollector

            collectors.append(OsmnxRouteCollector())
        for collector in collectors:
            try:
                if collector.source_name == "osmnx":
                    candidates = (
                        await collector.collect(start, end)
                        if settings.OSMNX_WALK_GEOMETRY_BLOCKING
                        else await collector.collect_cached_or_schedule(
                            start,
                            end,
                        )
                    )
                else:
                    candidates = await collector.collect(start, end)
            except (CollectorError, TimeoutError) as exc:
                signature = (collector.source_name, str(exc))
                with _walk_geometry_failure_signatures_guard:
                    first_occurrence = (
                        signature not in _walk_geometry_failure_signatures
                    )
                    _walk_geometry_failure_signatures.add(signature)
                if first_occurrence:
                    log.warning(
                        "보행 경로 geometry 보완 실패 source=%s detail=%s",
                        collector.source_name,
                        str(exc),
                    )
                continue
            if candidates and len(candidates[0].path) >= 2:
                return WalkGeometryResult(
                    candidates[0].path,
                    "exact",
                    dict(getattr(candidates[0], "accessibility_evidence", {})),
                    duration_min=getattr(candidates[0], "duration_min", None),
                    distance_m=getattr(candidates[0], "distance_m", None),
                )
        # 경로 시간이 아니라 화면 연결 geometry만 추정하며 상태를 반드시 estimated로 남긴다.
        return WalkGeometryResult([start, end], "estimated", {})

    async def _build_candidate(
        self,
        path: dict,
        origin: Coordinate,
        destination: Coordinate,
    ) -> RouteCandidate:
        """ODsay 후보 하나를 검증해 조립한다.

        후보 단위 오류는 호출 전체 오류와 분리한다. 상위 후보 하나의
        불완전한 ``mapObj``나 구간 값 때문에 뒤의 정상 후보까지 버리지 않는다.

        대중교통 구간은 최초에 정류장 관측 좌표 기반 estimated 선형으로
        조립한다. 정밀 도로·철도 선형(loadLane)은 최종 순위 확정 후
        선택된 후보만 ``refine_transit``으로 조회한다.
        """
        info = path.get("info")
        if not isinstance(info, dict):
            raise CollectorError("ODsay 후보의 info가 객체가 아닙니다.")
        duration = self._number(
            info.get("totalTime"),
            "totalTime",
            positive=True,
        )
        distance = self._number(
            info.get("totalDistance"),
            "totalDistance",
            positive=True,
        )
        sub_paths = path.get("subPath")
        if (
            not isinstance(sub_paths, list)
            or not sub_paths
            or any(not isinstance(sub, dict) for sub in sub_paths)
        ):
            raise CollectorError("ODsay 후보에 subPath가 없습니다.")
        sub_paths = self._apply_accessible_subway_exits(
            sub_paths,
            origin,
            destination,
        )
        refinement: dict | None = None
        if settings.ODSAY_LOAD_LANE_ENABLED:
            map_object = info.get("mapObj")
            if not map_object:
                raise CollectorError("ODsay 후보에 mapObj가 없습니다.")
            # 형식이 잘못된 mapObj는 정밀화 시점이 아니라 수집 시점에 거른다.
            self._load_lane_map_object(map_object)
            refinement = {
                "provider": self.source_name,
                "map_object": str(map_object),
                "origin": {"lat": origin.lat, "lng": origin.lng},
                "destination": {
                    "lat": destination.lat,
                    "lng": destination.lng,
                },
            }
        lane_paths = [
            self._estimated_transit_path(sub)
            for sub in sub_paths
            if sub.get("trafficType") != 3
        ]

        # 한 후보의 첫·마지막 도보 구간은 서로 독립적이다. 휠체어 요청은
        # 각 구간마다 ORS wheelchair 검증이 필요하므로 순차 대기하면 외부
        # 응답시간이 그대로 합산된다. 기존 ORS semaphore 범위 안에서 같은
        # 후보의 실제 보행 구간만 병렬 검증한다.
        walk_geometry_requests: list[
            tuple[int, tuple[Coordinate, Coordinate]]
        ] = []
        for index, sub in enumerate(sub_paths):
            if sub.get("trafficType") != 3:
                continue
            section_distance = self._number(
                sub.get("distance"),
                "distance",
                positive=False,
            )
            if section_distance == 0:
                continue
            endpoints = self._walk_endpoints(
                sub_paths,
                index,
                origin,
                destination,
            )
            if endpoints is None:
                raise CollectorError(
                    "ODsay 보행 구간의 시작·끝 좌표를 확인할 수 없습니다."
                )
            walk_geometry_requests.append((index, endpoints))
        walk_geometry_results = await asyncio.gather(*(
            self._shared_walk_geometry(*endpoints)
            for _, endpoints in walk_geometry_requests
        ))
        walk_geometries = {
            index: result
            for (index, _), result in zip(
                walk_geometry_requests,
                walk_geometry_results,
            )
        }

        lane_index = 0
        segments = []
        coords: list[Coordinate] = []
        qualities: list[str] = []
        walk_metrics_adjusted = False
        for index, sub in enumerate(sub_paths):
            section_time = self._number(
                sub.get("sectionTime"),
                "sectionTime",
                positive=False,
            )
            section_distance = self._number(
                sub.get("distance"),
                "distance",
                positive=False,
            )
            traffic_type = sub.get("trafficType")
            if (
                type(traffic_type) is not int
                or traffic_type not in {1, 2, 3}
            ):
                raise CollectorError(
                    f"지원하지 않는 ODsay trafficType입니다: {traffic_type!r}"
                )
            mode = {1: "subway", 2: "bus", 3: "walk"}[traffic_type]
            if mode == "walk":
                endpoints = self._walk_endpoints(
                    sub_paths,
                    index,
                    origin,
                    destination,
                )
                if endpoints is None:
                    raise CollectorError(
                        "ODsay 보행 구간의 시작·끝 좌표를 확인할 수 없습니다."
                    )
                if section_distance == 0:
                    if endpoints[0] != endpoints[1]:
                        raise CollectorError(
                            "ODsay 0m 보행 구간의 시작·끝 좌표가 일치하지 않습니다."
                        )
                    segment_path = [endpoints[0], endpoints[1]]
                    quality = "exact"
                    accessibility_evidence = {}
                else:
                    result = walk_geometries[index]
                    (
                        segment_path,
                        quality,
                        accessibility_evidence,
                    ) = result
                    if isinstance(result, WalkGeometryResult):
                        if result.duration_min is not None:
                            section_time = result.duration_min
                            walk_metrics_adjusted = True
                        if result.distance_m is not None:
                            section_distance = result.distance_m
                            walk_metrics_adjusted = True
            else:
                segment_path = (
                    lane_paths[lane_index]
                    if lane_index < len(lane_paths)
                    else []
                )
                lane_index += 1
                if len(segment_path) < 2:
                    raise CollectorError(
                        f"ODsay {mode} 구간의 정류장 geometry가 없습니다."
                    )
                # 정류장 좌표를 이은 선형은 실제 도로·철도 선형이 아니므로
                # 정밀화 전까지 반드시 estimated로 기록한다.
                quality = "estimated"
                accessibility_evidence = {}
            if coords and coords[-1] == segment_path[0]:
                coords.extend(segment_path[1:])
            else:
                coords.extend(segment_path)
            qualities.append(quality)
            segments.append({
                "mode": mode,
                "duration_min": section_time,
                "distance_m": section_distance,
                "path": segment_path,
                "geometry_quality": quality,
                "raw": sub,
                "accessibility_evidence": accessibility_evidence,
            })
        if walk_metrics_adjusted:
            duration = sum(float(segment["duration_min"]) for segment in segments)
            distance = sum(float(segment["distance_m"]) for segment in segments)
        if len(coords) < 2:
            raise CollectorError("ODsay 후보의 조립된 geometry가 비어 있습니다.")
        geometry_quality = (
            qualities[0]
            if qualities and len(set(qualities)) == 1
            else "mixed"
        )
        return RouteCandidate(
            source=self.source_name,
            path=coords,
            duration_min=duration,
            distance_m=distance,
            raw_response=path,
            segments=segments,
            geometry_quality=geometry_quality,
            transit_refinement=refinement,
        )

    async def _collect_live_or_cached(
        self,
        origin: Coordinate,
        destination: Coordinate,
        *,
        max_candidates: int,
    ) -> list:
        try:
            search_identity = {
                "origin": [
                    round(float(origin.lat), 5),
                    round(float(origin.lng), 5),
                ],
                "destination": [
                    round(float(destination.lat), 5),
                    round(float(destination.lng), 5),
                ],
            }
            identity_hash = anonymized_hash(
                json.dumps(search_identity, sort_keys=True)
            )
            started_at = time.monotonic()
            data = await _cached_payload("search", search_identity)
            cache_hit = data is not None
            network = False
            follower = False
            semaphore_wait = 0.0
            http_status: int | None = None
            outcome = "cache"
            try:
                if not cache_hit:
                    async def _fetch_search() -> dict:
                        nonlocal network, semaphore_wait, http_status
                        cached = await _cached_payload(
                            "search", search_identity
                        )
                        if cached is not None:
                            return cached

                        async def _request() -> dict:
                            nonlocal http_status, network
                            # semaphore 확보 후 실제 transport 직전에만 집계.
                            async with httpx.AsyncClient(
                                follow_redirects=True
                            ) as client:
                                record_network_call("searchPubTransPathT")
                                network = True
                                odsay_counters.record_network_attempt(
                                    "searchPubTransPathT"
                                )
                                try:
                                    resp = await client.get(
                                        self.BASE_URL,
                                        params={
                                            "SX": origin.lng,
                                            "SY": origin.lat,
                                            "EX": destination.lng,
                                            "EY": destination.lat,
                                            "apiKey": settings.ODSAY_API_KEY,
                                            "OPT": 0,
                                            "SearchType": 0,
                                            "SearchPathType": 0,
                                        },
                                        timeout=8.0,
                                    )
                                except BaseException:
                                    odsay_counters.record_network_result(
                                        "searchPubTransPathT",
                                        completed=False,
                                    )
                                    raise
                            odsay_counters.record_network_result(
                                "searchPubTransPathT",
                                completed=True,
                            )
                            http_status = getattr(
                                resp, "status_code", None
                            )
                            resp.raise_for_status()
                            payload = resp.json()
                            return payload

                        fetched, waited = await with_concurrency_limit(
                            _request
                        )
                        semaphore_wait = waited
                        return fetched

                    data, follower = await single_flight(
                        f"search:{identity_hash}",
                        _fetch_search,
                    )
                    outcome = "network" if network else "single-flight"
                if not isinstance(data, dict):
                    raise CollectorError("ODsay 응답 본문이 JSON 객체가 아닙니다.")
                api_error = self._api_error(data)
                if api_error:
                    raise CollectorError(f"ODsay 경로 검색 실패: {api_error}")

                result = data.get("result")
                if not isinstance(result, dict):
                    raise CollectorError("ODsay 응답의 result가 객체가 아닙니다.")
                paths = result.get("path")
                if paths is None:
                    paths = []
                elif not isinstance(paths, list):
                    raise CollectorError(
                        "ODsay 응답의 result.path가 배열이 아닙니다."
                    )
                if network:
                    await _store_payload("search", search_identity, data)
            except BaseException:
                outcome = "error"
                raise
            finally:
                odsay_counters.record(
                    "searchPubTransPathT",
                    network=network,
                    cache_hit=cache_hit,
                    follower=follower,
                    semaphore_wait=semaphore_wait,
                )
                log_odsay_call(
                    "searchPubTransPathT",
                    identity_hash=identity_hash,
                    cache_hit=cache_hit,
                    network=network,
                    follower=follower,
                    duration_ms=(time.monotonic() - started_at) * 1000,
                    outcome=outcome,
                    call_site="collect",
                    http_status=http_status,
                    semaphore_wait=semaphore_wait,
                )

            candidates = []
            rejected: list[str] = []
            # 후보별 보행 구간은 서로 독립적이므로 묶어서 조립해 공급자
            # 지연이 직렬로 누적되지 않게 한다. 다만 batch 크기는 아직
            # 필요한 후보 수에 맞춰 줄인다. 고정 크기로 묶으면 이미 충분한
            # 후보를 확보한 뒤에도 남은 후보의 TMAP 보행 geometry·검증·
            # 파싱을 실행하고 결과를 버리게 된다.
            # 대중교통 loadLane은 이 단계에서 호출하지 않는다.
            cursor = 0
            while cursor < len(paths) and len(candidates) < max_candidates:
                remaining = max_candidates - len(candidates)
                batch_size = min(BUILD_BATCH_SIZE, remaining)
                batch: list[tuple[int, dict]] = []
                while cursor < len(paths) and len(batch) < batch_size:
                    index = cursor
                    path = paths[cursor]
                    cursor += 1
                    if not isinstance(path, dict):
                        rejected.append(f"{index + 1}번 후보: 객체 아님")
                        continue
                    batch.append((index, path))
                if not batch:
                    break
                results = await asyncio.gather(
                    *(
                        self._build_candidate(
                            path,
                            origin,
                            destination,
                        )
                        for _, path in batch
                    ),
                    return_exceptions=True,
                )
                for (index, _), result in zip(batch, results):
                    if isinstance(result, CollectorError):
                        rejected.append(f"{index + 1}번 후보: {result}")
                    elif isinstance(result, BaseException):
                        raise result
                    else:
                        refinement = getattr(
                            result,
                            "transit_refinement",
                            None,
                        )
                        if isinstance(refinement, dict):
                            refinement[
                                "provider_candidate_index"
                            ] = index + 1
                        candidates.append(result)
            if not candidates:
                suffix = f" ({'; '.join(rejected[:3])})" if rejected else ""
                raise CollectorError(
                    "ODsay가 유효한 부산 대중교통 경로를 반환하지 않았습니다."
                    + suffix
                )
            return candidates
        except CollectorError:
            raise
        except (httpx.HTTPError, ValueError, TypeError) as exc:
            raise CollectorError(
                f"ODsay 호출 또는 응답 처리 실패: {type(exc).__name__}",
                code=_transport_error_code(exc),
            ) from exc

    async def collect(
        self,
        origin: Coordinate,
        destination: Coordinate,
        *,
        max_candidates: int | None = None,
    ) -> list:
        if not settings.ODSAY_API_KEY or settings.ODSAY_API_KEY.startswith("YOUR_"):
            raise CollectorNotConfigured("ODSAY_API_KEY가 설정되지 않았습니다.")
        candidate_limit = max_candidates or settings.ODSAY_MAX_CANDIDATES
        if candidate_limit > settings.ODSAY_MAX_CANDIDATES:
            # 요청보다 적게 수집하고 정상 처리한 것처럼 보이지 않도록
            # 상한 초과는 조용한 절단 대신 명시적 오류로 반환한다.
            raise CollectorError(
                f"요청한 후보 수 {candidate_limit}개가 서버 상한 "
                f"{settings.ODSAY_MAX_CANDIDATES}개를 초과합니다."
            )
        ensure_correlation_id()
        try:
            return await asyncio.wait_for(
                self._collect_live_or_cached(
                    origin,
                    destination,
                    max_candidates=candidate_limit,
                ),
                timeout=settings.ODSAY_TIMEOUT_SECONDS,
            )
        except TimeoutError as exc:
            raise CollectorError(
                "ODsay 경로 수집이 서비스 시간 제한을 초과했습니다.",
                code="timeout",
            ) from exc
