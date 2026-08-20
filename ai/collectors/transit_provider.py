"""대중교통 공급자 순서와 무중단 전환 정책."""
from __future__ import annotations

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
        for name in provider_order():
            collector = self._collector(name)
            self.attempted_sources.append(collector.source_name)
            try:
                candidates = await collector.collect(
                    origin,
                    destination,
                    max_candidates=max_candidates,
                )
            except CollectorError as exc:
                self.source_errors[collector.source_name] = (
                    f"{type(exc).__name__}: {exc}"
                )
                failures.append(exc)
                continue
            if candidates:
                self.selected_source = collector.source_name
                return candidates
            self.source_errors[collector.source_name] = "NoRoutes"
            failures.append(
                CollectorError(
                    f"{collector.source_name}가 경로를 반환하지 않았습니다.",
                    code="empty_geometry",
                )
            )

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
