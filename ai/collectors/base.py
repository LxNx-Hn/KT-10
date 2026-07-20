"""경로 수집기 공통 인터페이스와 명시적 실패 타입."""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Literal, Optional


class CollectorError(RuntimeError):
    """외부 경로 공급자 호출 또는 응답 검증 실패."""


class CollectorNotConfigured(CollectorError):
    """필수 API 키가 설정되지 않은 공급자."""


@dataclass
class Coordinate:
    lat: float
    lng: float


@dataclass
class RouteCandidate:
    source: str
    path: list
    # Geometry-only collectors cannot truthfully infer travel time without an
    # explicit walking-speed policy. Scored candidates must provide a value.
    duration_min: float | None
    distance_m: float
    raw_response: Optional[dict] = field(default=None)
    segments: list[dict[str, Any]] = field(default_factory=list)
    geometry_quality: Literal["exact", "mixed", "estimated"] = "exact"


class BaseRouteCollector(ABC):
    source_name: str = "base"

    @abstractmethod
    async def collect(self, origin: Coordinate, destination: Coordinate) -> list:
        """경로 후보 수집. 설정/호출/검증 실패는 CollectorError로 알린다."""
        pass
