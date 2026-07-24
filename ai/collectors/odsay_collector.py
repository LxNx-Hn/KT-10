"""
ODsay 대중교통 경로 수집기 (메인 소스).

ODsay Lab API로 대중교통 경로 후보를 수집한다.
버스·지하철 환승 정보, 정류장 좌표를 세그먼트 단위로 제공.
키가 없거나 응답이 불완전하면 가짜 경로를 만들지 않고 명시적으로 실패한다.

API 문서: https://lab.odsay.com/guide/service
"""
import asyncio
from hashlib import sha256
import json
import logging
from math import isfinite
from pathlib import Path
import time
from uuid import uuid4

import httpx

from collectors.base import (
    BaseRouteCollector,
    CollectorError,
    CollectorNotConfigured,
    Coordinate,
    RouteCandidate,
)
from config import settings

CACHE_SCHEMA_VERSION = 1
log = logging.getLogger("collectors.odsay")


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
        client: httpx.AsyncClient,
        map_object: str,
        origin: Coordinate,
        destination: Coordinate,
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
        data = await _cached_payload("lane", cache_identity)
        cache_hit = data is not None
        if not cache_hit:
            response = await client.get(
                self.LANE_URL,
                params=request_params,
                timeout=8.0,
            )
            response.raise_for_status()
            data = response.json()
        if not isinstance(data, dict):
            raise CollectorError(
                "ODsay loadLane 응답 본문이 JSON 객체가 아닙니다."
            )
        api_error = self._api_error(data)
        if api_error:
            raise CollectorError(f"ODsay loadLane 실패: {api_error}")
        if not cache_hit:
            await _store_payload("lane", cache_identity, data)
        paths = self._lane_paths(data, load_lane_map_object)
        if not paths or not any(paths):
            raise CollectorError("ODsay loadLane 응답에 유효한 경로 좌표가 없습니다.")
        return paths

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

    @staticmethod
    async def _walk_geometry(start: Coordinate, end: Coordinate) -> tuple[list[Coordinate], str]:
        # TMAP 키가 있으면 공식 보행 경로를 우선한다. OSMnx는 외부 그래프
        # 조회 지연이 크므로 명시적으로 활성화한 환경에서만 보조로 사용한다.
        from collectors.tmap_collector import TmapRouteCollector

        collectors = []
        if settings.TMAP_API_KEY and not settings.TMAP_API_KEY.startswith("YOUR_"):
            collectors.append(TmapRouteCollector())
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
            except (CollectorError, TimeoutError):
                continue
            if candidates and len(candidates[0].path) >= 2:
                return candidates[0].path, "exact"
        # 경로 시간이 아니라 화면 연결 geometry만 추정하며 상태를 반드시 estimated로 남긴다.
        return [start, end], "estimated"

    async def _build_candidate(
        self,
        client: httpx.AsyncClient,
        path: dict,
        origin: Coordinate,
        destination: Coordinate,
    ) -> RouteCandidate:
        """ODsay 후보 하나를 검증해 조립한다.

        후보 단위 오류는 호출 전체 오류와 분리한다. 상위 후보 하나의
        불완전한 ``mapObj``나 구간 값 때문에 뒤의 정상 후보까지 버리지 않는다.
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
        if settings.ODSAY_LOAD_LANE_ENABLED:
            map_object = info.get("mapObj")
            if not map_object:
                raise CollectorError("ODsay 후보에 mapObj가 없습니다.")
            lane_paths = await self._load_lane(
                client,
                map_object,
                origin,
                destination,
            )
        else:
            lane_paths = [
                self._estimated_transit_path(sub)
                for sub in sub_paths
                if sub.get("trafficType") != 3
            ]

        lane_index = 0
        segments = []
        coords: list[Coordinate] = []
        qualities: list[str] = []
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
                else:
                    segment_path, quality = await self._walk_geometry(*endpoints)
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
                quality = (
                    "exact"
                    if settings.ODSAY_LOAD_LANE_ENABLED
                    else "estimated"
                )
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
            })
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
        )

    async def _collect_live_or_cached(
        self,
        origin: Coordinate,
        destination: Coordinate,
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
            data = await _cached_payload("search", search_identity)
            cache_hit = data is not None
            if not cache_hit:
                async with httpx.AsyncClient(follow_redirects=True) as client:
                    resp = await client.get(self.BASE_URL, params={
                        "SX": origin.lng, "SY": origin.lat,
                        "EX": destination.lng, "EY": destination.lat,
                        "apiKey": settings.ODSAY_API_KEY,
                        "OPT": 0, "SearchType": 0, "SearchPathType": 0,
                    }, timeout=8.0)
                    resp.raise_for_status()
                data = resp.json()
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
                raise CollectorError("ODsay 응답의 result.path가 배열이 아닙니다.")
            if not cache_hit:
                await _store_payload("search", search_identity, data)

            candidates = []
            rejected: list[str] = []
            async with httpx.AsyncClient(follow_redirects=True) as lane_client:
                # 후보별 OSM 보행 구간은 서로 독립적이다. 세 후보를 한 묶음으로
                # 조립해 공급자 지연이 직렬로 누적되지 않게 하되, OSM 수집기
                # 내부 동시성 상한으로 공개 Overpass에 과도한 요청을 보내지 않는다.
                for batch_start in range(0, len(paths), 3):
                    batch: list[tuple[int, dict]] = []
                    for index, path in enumerate(
                        paths[batch_start:batch_start + 3],
                        start=batch_start,
                    ):
                        if not isinstance(path, dict):
                            rejected.append(f"{index + 1}번 후보: 객체 아님")
                            continue
                        batch.append((index, path))
                    results = await asyncio.gather(
                        *(
                            self._build_candidate(
                                lane_client,
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
                            candidates.append(result)
                            if len(candidates) >= 3:
                                break
                    if len(candidates) >= 3:
                        break
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
            raise CollectorError(f"ODsay 호출 또는 응답 처리 실패: {type(exc).__name__}") from exc

    async def collect(self, origin: Coordinate, destination: Coordinate) -> list:
        if not settings.ODSAY_API_KEY or settings.ODSAY_API_KEY.startswith("YOUR_"):
            raise CollectorNotConfigured("ODSAY_API_KEY가 설정되지 않았습니다.")
        try:
            return await asyncio.wait_for(
                self._collect_live_or_cached(origin, destination),
                timeout=settings.ODSAY_TIMEOUT_SECONDS,
            )
        except TimeoutError as exc:
            raise CollectorError(
                "ODsay 경로 수집이 서비스 시간 제한을 초과했습니다."
            ) from exc
