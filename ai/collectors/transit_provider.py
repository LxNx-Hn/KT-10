"""대중교통 공급자 순서와 무중단 전환 정책."""
from __future__ import annotations

import asyncio

from collectors.base import (
    BaseRouteCollector,
    CollectorError,
    Coordinate,
    RouteCandidate,
)
from collectors.tmap_transit_collector import TmapTransitRouteCollector
from config import settings

SUPPORTED_TRANSIT_PROVIDERS = ("odsay", "tmap")


def provider_order(value: str | None = None) -> tuple[str, ...]:
    raw = settings.TRANSIT_PROVIDER_ORDER if value is None else value
    names = tuple(
        item.strip().casefold()
        for item in raw.split(",")
        if item.strip()
    )
    if not names:
        raise ValueError("TRANSIT_PROVIDER_ORDER가 비어 있습니다.")
    unknown = [name for name in names if name not in SUPPORTED_TRANSIT_PROVIDERS]
    if unknown:
        raise ValueError(
            "지원하지 않는 대중교통 공급자입니다: " + ", ".join(unknown)
        )
    if len(set(names)) != len(names):
        raise ValueError("TRANSIT_PROVIDER_ORDER에 중복 공급자가 있습니다.")
    return names


def configured_provider_names() -> tuple[str, ...]:
    configured: list[str] = []
    for name in provider_order():
        if name == "odsay":
            key = settings.ODSAY_API_KEY.strip()
        else:
            key = settings.TMAP_API_KEY.strip()
        if key and not key.startswith("YOUR_"):
            configured.append(name)
    return tuple(configured)


class TransitProviderCollector(BaseRouteCollector):
    """첫 정상 공급자를 사용하고 실패 원인을 구조적으로 보존한다."""

    source_name = "transit"

    def __init__(
        self,
        *,
        avoid_stairs: bool = False,
        uses_wheelchair: bool = False,
    ) -> None:
        self.avoid_stairs = avoid_stairs
        self.uses_wheelchair = uses_wheelchair
        self.attempted_sources: list[str] = []
        self.source_errors: dict[str, str] = {}
        self.selected_source: str | None = None

    def _collector(self, name: str) -> BaseRouteCollector:
        if name == "odsay":
            # ODsay는 전환 기간에만 쓰는 선택적 플러그인이다. 공급자 순서가
            # tmap이면 모듈 자체를 제거한 배포에서도 import하지 않는다.
            from collectors.odsay_collector import OdsayRouteCollector

            return OdsayRouteCollector(
                avoid_stairs=self.avoid_stairs,
                uses_wheelchair=self.uses_wheelchair,
            )
        if name == "tmap":
            return TmapTransitRouteCollector(
                avoid_stairs=self.avoid_stairs,
                uses_wheelchair=self.uses_wheelchair,
            )
        raise AssertionError(f"검증되지 않은 공급자: {name}")

    async def _attempt(
        self,
        name: str,
        origin: Coordinate,
        destination: Coordinate,
        max_candidates: int | None,
    ) -> tuple[str, list[RouteCandidate] | None, CollectorError | None]:
        collector = self._collector(name)
        self.attempted_sources.append(collector.source_name)
        try:
            candidates = await collector.collect(
                origin,
                destination,
                max_candidates=max_candidates,
            )
        except CollectorError as exc:
            return collector.source_name, None, exc
        if candidates:
            return collector.source_name, candidates, None
        return (
            collector.source_name,
            None,
            CollectorError(
                f"{collector.source_name}가 경로를 반환하지 않았습니다.",
                code="empty_geometry",
            ),
        )

    def _record_outcome(
        self,
        outcome: tuple[
            str,
            list[RouteCandidate] | None,
            CollectorError | None,
        ],
        failures: list[CollectorError],
    ) -> list[RouteCandidate] | None:
        source, candidates, error = outcome
        if candidates:
            self.selected_source = source
            return candidates
        if error is None:
            raise AssertionError("공급자 실패 결과에 오류가 없습니다.")
        self.source_errors[source] = (
            "NoRoutes"
            if error.code == "empty_geometry"
            else f"{type(error).__name__}: {error}"
        )
        failures.append(error)
        return None

    def _raise_unavailable(self, failures: list[CollectorError]) -> None:
        detail = "; ".join(
            f"{name}: {value}" for name, value in self.source_errors.items()
        )
        retryable = any(error.retryable for error in failures)
        code = failures[-1].code if failures else "not_configured"
        raise CollectorError(
            "사용 가능한 대중교통 경로 공급자가 없습니다."
            + (f" ({detail})" if detail else ""),
            code=code,
            retryable=retryable,
        )

    async def _collect_odsay_tmap_hedged(
        self,
        origin: Coordinate,
        destination: Coordinate,
        max_candidates: int | None,
        failures: list[CollectorError],
    ) -> list[RouteCandidate]:
        """ODsay가 느릴 때만 TMAP을 겹쳐 ALB 응답 제한 안에 끝낸다."""
        loop = asyncio.get_running_loop()
        deadline = loop.time() + settings.TRANSIT_PROVIDER_TOTAL_TIMEOUT_SECONDS
        odsay_task = asyncio.create_task(
            self._attempt("odsay", origin, destination, max_candidates)
        )
        tasks: dict[asyncio.Task, str] = {odsay_task: "odsay"}
        try:
            done, _ = await asyncio.wait(
                {odsay_task},
                timeout=settings.TRANSIT_PROVIDER_HEDGE_SECONDS,
            )
            if done:
                candidates = self._record_outcome(odsay_task.result(), failures)
                if candidates:
                    return candidates

            tmap_task = asyncio.create_task(
                self._attempt("tmap", origin, destination, max_candidates)
            )
            tasks[tmap_task] = "tmap_transit"
            pending = {
                task
                for task in tasks
                if not task.done()
            }
            while pending:
                remaining = deadline - loop.time()
                if remaining <= 0:
                    break
                done, pending = await asyncio.wait(
                    pending,
                    timeout=remaining,
                    return_when=asyncio.FIRST_COMPLETED,
                )
                if not done:
                    break
                # 같은 event-loop tick에 둘 다 끝나면 원래 순서인 ODsay를
                # 먼저 판정해 1순위 계약을 보존한다.
                ordered = sorted(done, key=lambda task: task is not odsay_task)
                for task in ordered:
                    candidates = self._record_outcome(task.result(), failures)
                    if candidates:
                        for other in pending:
                            other.cancel()
                        if pending:
                            await asyncio.gather(*pending, return_exceptions=True)
                        return candidates

            for task in pending:
                source = tasks[task]
                task.cancel()
                timeout_error = CollectorError(
                    f"{source} 전체 수집 제한시간을 초과했습니다.",
                    code="timeout",
                )
                self.source_errors[source] = (
                    f"CollectorError: {timeout_error}"
                )
                failures.append(timeout_error)
            if pending:
                await asyncio.gather(*pending, return_exceptions=True)
            self._raise_unavailable(failures)
        finally:
            unfinished = [task for task in tasks if not task.done()]
            for task in unfinished:
                task.cancel()
            if unfinished:
                await asyncio.gather(*unfinished, return_exceptions=True)

    async def collect(
        self,
        origin: Coordinate,
        destination: Coordinate,
        *,
        max_candidates: int | None = None,
    ) -> list[RouteCandidate]:
        self.attempted_sources.clear()
        self.source_errors.clear()
        self.selected_source = None
        failures: list[CollectorError] = []
        order = provider_order()
        if order == ("odsay", "tmap"):
            return await self._collect_odsay_tmap_hedged(
                origin,
                destination,
                max_candidates,
                failures,
            )
        for name in order:
            outcome = await self._attempt(
                name,
                origin,
                destination,
                max_candidates,
            )
            candidates = self._record_outcome(outcome, failures)
            if candidates:
                return candidates
        self._raise_unavailable(failures)
