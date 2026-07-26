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
    # 대중교통 표시 선형을 나중에 정밀화하기 위한 공급자 내부 서술자.
    # 서버 내부 전용이며 공개 API 응답에 원문을 노출하지 않는다.
    transit_refinement: Optional[dict] = field(default=None)


class BaseRouteCollector(ABC):
    source_name: str = "base"

    @abstractmethod
    async def collect(self, origin: Coordinate, destination: Coordinate) -> list:
        """경로 후보 수집. 설정/호출/검증 실패는 CollectorError로 알린다."""
        pass
