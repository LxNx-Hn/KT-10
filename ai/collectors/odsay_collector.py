"""
ODsay 대중교통 경로 수집기 (메인 소스).

ODsay Lab API로 대중교통 경로 후보를 수집한다.
버스·지하철 환승 정보, 정류장 좌표를 세그먼트 단위로 제공.
키가 없거나 응답이 불완전하면 가짜 경로를 만들지 않고 명시적으로 실패한다.

API 문서: https://lab.odsay.com/guide/service
"""
import httpx

from collectors.base import (
    BaseRouteCollector,
    CollectorError,
    CollectorNotConfigured,
    Coordinate,
    RouteCandidate,
)
from config import settings


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
        return value if has_base else f"0:0@{value}"

    @classmethod
    def _lane_paths(cls, data: dict, map_object: str) -> list[list[Coordinate]]:
        base_x, base_y = cls._map_base(map_object)
        paths: list[list[Coordinate]] = []
        for lane in data.get("result", {}).get("lane", []) or []:
            lane_coords: list[Coordinate] = []
            for section in lane.get("section", []) or []:
                for point in section.get("graphPos", []) or []:
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
            if len(lane_coords) >= 2:
                paths.append(lane_coords)
        return paths

    @classmethod
    def _lane_coordinates(cls, data: dict, map_object: str) -> list[Coordinate]:
        return [point for path in cls._lane_paths(data, map_object) for point in path]

    async def _load_lane(
        self,
        client: httpx.AsyncClient,
        map_object: str,
        origin: Coordinate,
        destination: Coordinate,
    ) -> list[list[Coordinate]]:
        margin = 0.02
        load_lane_map_object = self._load_lane_map_object(map_object)
        response = await client.get(
            self.LANE_URL,
            params={
                "mapObject": load_lane_map_object,
                "left": min(origin.lng, destination.lng) - margin,
                "top": max(origin.lat, destination.lat) + margin,
                "right": max(origin.lng, destination.lng) + margin,
                "bottom": min(origin.lat, destination.lat) - margin,
                "apiKey": settings.ODSAY_API_KEY,
            },
            timeout=15.0,
        )
        response.raise_for_status()
        data = response.json()
        api_error = self._api_error(data)
        if api_error:
            raise CollectorError(f"ODsay loadLane 실패: {api_error}")
        paths = self._lane_paths(data, load_lane_map_object)
        if not paths:
            raise CollectorError("ODsay loadLane 응답에 유효한 경로 좌표가 없습니다.")
        return paths

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
                candidates = await collector.collect(start, end)
            except CollectorError:
                continue
            if candidates and len(candidates[0].path) >= 2:
                return candidates[0].path, "exact"
        # 경로 시간이 아니라 화면 연결 geometry만 추정하며 상태를 반드시 estimated로 남긴다.
        return [start, end], "estimated"

    async def collect(self, origin: Coordinate, destination: Coordinate) -> list:
        if not settings.ODSAY_API_KEY or settings.ODSAY_API_KEY.startswith("YOUR_"):
            raise CollectorNotConfigured("ODSAY_API_KEY가 설정되지 않았습니다.")

        try:
            async with httpx.AsyncClient(follow_redirects=True) as client:
                resp = await client.get(self.BASE_URL, params={
                    "SX": origin.lng, "SY": origin.lat,
                    "EX": destination.lng, "EY": destination.lat,
                    "apiKey": settings.ODSAY_API_KEY,
                    "OPT": 0, "SearchType": 0, "SearchPathType": 0,
                }, timeout=15.0)
                resp.raise_for_status()
            data = resp.json()
            api_error = self._api_error(data)
            if api_error:
                raise CollectorError(f"ODsay 경로 검색 실패: {api_error}")

            candidates = []
            async with httpx.AsyncClient(follow_redirects=True) as lane_client:
                for path in (data.get("result", {}).get("path", []) or [])[:3]:
                    info = path.get("info") or {}
                    map_object = info.get("mapObj")
                    if not map_object:
                        continue
                    lane_paths = await self._load_lane(lane_client, map_object, origin, destination)
                    duration = float(info.get("totalTime") or 0)
                    distance = float(info.get("totalDistance") or 0)
                    if duration <= 0 or distance <= 0:
                        continue
                    sub_paths = path.get("subPath") or []
                    lane_index = 0
                    segments = []
                    coords: list[Coordinate] = []
                    qualities = []
                    for index, sub in enumerate(sub_paths):
                        try:
                            section_time = float(sub["sectionTime"])
                            section_distance = float(sub["distance"])
                        except (KeyError, TypeError, ValueError):
                            segments = []
                            coords = []
                            break
                        if section_time < 0 or section_distance < 0:
                            segments = []
                            coords = []
                            break
                        mode = {1: "subway", 2: "bus", 3: "walk"}.get(sub.get("trafficType"), "transfer")
                        if mode == "walk":
                            endpoints = self._walk_endpoints(sub_paths, index, origin, destination)
                            segment_path, quality = (
                                await self._walk_geometry(*endpoints) if endpoints else ([], "estimated")
                            )
                        else:
                            segment_path = lane_paths[lane_index] if lane_index < len(lane_paths) else []
                            lane_index += 1
                            quality = "exact" if segment_path else "estimated"
                        if segment_path:
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
                        continue
                    geometry_quality = "exact" if qualities and all(value == "exact" for value in qualities) else "mixed"
                    candidates.append(RouteCandidate(
                        source=self.source_name,
                        path=coords,
                        duration_min=duration,
                        distance_m=distance,
                        raw_response=path,
                        segments=segments,
                        geometry_quality=geometry_quality,
                    ))
            if not candidates:
                raise CollectorError("ODsay가 유효한 부산 대중교통 경로를 반환하지 않았습니다.")
            return candidates
        except CollectorError:
            raise
        except (httpx.HTTPError, ValueError, TypeError) as exc:
            raise CollectorError(f"ODsay 호출 또는 응답 처리 실패: {type(exc).__name__}") from exc
