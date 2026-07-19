"""경로 수집기 공통 인터페이스."""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Coordinate:
    lat: float
    lng: float


@dataclass
class RouteCandidate:
    source: str
    path: list
    duration_min: float
    distance_m: float
    raw_response: Optional[dict] = field(default=None)


class BaseRouteCollector(ABC):
    source_name: str = "base"

    @abstractmethod
    async def collect(self, origin: Coordinate, destination: Coordinate) -> list:
        """경로 후보 수집. 실패 시 빈 리스트 반환 (예외 전파 금지)."""
        pass
