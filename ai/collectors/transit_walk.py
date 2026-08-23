"""대중교통 공급자와 독립적인 보행 구간 geometry 해석기.

대중교통 경로 공급자는 승하차 지점까지만 결정한다. 실제 보행 구간은
일반 요청에서 TMAP pedestrian, 휠체어 요청에서 ORS wheelchair를 사용해
동일한 계약으로 검증한다. ODsay 전용 모듈을 제거해도 이 경로가 남도록
공급자 중립 모듈에 둔다.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from threading import Lock

from collectors.base import CollectorError, Coordinate
from config import settings
from merger.route_merger import (
    accessibility_paths_similar,
    merge_accessibility_evidence,
)

log = logging.getLogger("collectors.transit_walk")
_failure_signatures: set[tuple[str, str]] = set()
_failure_signatures_guard = Lock()


@dataclass(frozen=True)
class WalkGeometryResult:
    path: list[Coordinate]
    quality: str
    accessibility_evidence: dict
    duration_min: float | None = None
    distance_m: float | None = None


class TransitWalkGeometryResolver:
    """한 사용자 요청 안에서 동일 보행 구간 호출을 하나로 합친다."""

    def __init__(
        self,
        *,
        avoid_stairs: bool = False,
        uses_wheelchair: bool = False,
    ) -> None:
        self.avoid_stairs = avoid_stairs
        self.uses_wheelchair = uses_wheelchair
        self._tasks: dict[
            tuple[float, float, float, float, bool, bool],
            asyncio.Task[WalkGeometryResult],
        ] = {}

    def _identity(
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

    async def resolve(
        self,
        start: Coordinate,
        end: Coordinate,
    ) -> WalkGeometryResult:
        identity = self._identity(start, end)
        task = self._tasks.get(identity)
        if task is None:
            task = asyncio.create_task(self._resolve(start, end))
            self._tasks[identity] = task
        return await asyncio.shield(task)

    async def _resolve(
        self,
        start: Coordinate,
        end: Coordinate,
    ) -> WalkGeometryResult:
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

            # TMAP의 계단·경사로 지점은 ORS wheelchair 선형과 일치하는
            # 24시간 이내 캐시가 있을 때만 보조 근거로 결합한다.
            from collectors.tmap_collector import TmapRouteCollector

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
                duration_min=primary.duration_min,
                distance_m=primary.distance_m,
            )

        collectors = []
        if (
            settings.TMAP_API_KEY
            and not settings.TMAP_API_KEY.startswith("YOUR_")
        ):
            from collectors.tmap_collector import TmapRouteCollector

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
                    candidates = await asyncio.wait_for(
                        collector.collect(start, end),
                        timeout=settings.TRANSIT_WALK_ENRICHMENT_TIMEOUT_SECONDS,
                    )
            except (CollectorError, TimeoutError) as exc:
                signature = (collector.source_name, str(exc))
                with _failure_signatures_guard:
                    first = signature not in _failure_signatures
                    _failure_signatures.add(signature)
                if first:
                    log.warning(
                        "보행 geometry 보완 실패 source=%s detail=%s",
                        collector.source_name,
                        str(exc),
                    )
                continue
            if candidates and len(candidates[0].path) >= 2:
                candidate = candidates[0]
                return WalkGeometryResult(
                    candidate.path,
                    "exact",
                    dict(candidate.accessibility_evidence),
                    duration_min=candidate.duration_min,
                    distance_m=candidate.distance_m,
                )

        # 일반 경로는 대중교통 응답 자체의 보행 linestring을 상위 수집기가
        # 보존한다. 이 fallback은 그 선형조차 없을 때만 estimated 연결을
        # 만들며, 시간·거리 값을 추정하지 않는다.
        return WalkGeometryResult([start, end], "estimated", {})
