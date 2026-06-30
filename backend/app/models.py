"""
도메인 모델 (Pydantic v2). 프론트엔드 TypeScript 타입과 1:1 대응.
JSON 직렬화는 camelCase(alias)로 이루어져 프론트엔드와 그대로 호환된다.
- Optional[...] = None → 프론트엔드의 undefined(미확인)와 동일 의미.
- 응답에서 None 필드는 제외(response_model_exclude_none)하여 "미확인"을 표현한다.
"""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

ProfileId = Literal["general", "elderly", "child", "disabled"]
SegmentMode = Literal["walk", "bus", "subway", "transfer"]
AirQuality = Literal["good", "moderate", "bad", "very_bad"]
SkyCondition = Literal["clear", "cloudy", "rain", "snow"]
WeatherScenarioId = Literal["normal", "heatwave", "coldwave", "rain", "dust"]
LowFloorStatus = Literal["confirmed", "regular", "unknown", "none"]
AccidentRisk = Literal["low", "medium", "high"]


class CamelModel(BaseModel):
    """snake_case 속성 + camelCase JSON. 입력은 양쪽 모두 허용."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class LatLng(CamelModel):
    lat: float
    lng: float


class Place(CamelModel):
    id: str
    name: str
    lat: float
    lng: float
    category: Optional[str] = None
    address: Optional[str] = None


class RouteSegment(CamelModel):
    id: str
    mode: SegmentMode
    description: str
    duration_min: float
    distance_m: Optional[float] = None

    # 보행 구간
    outdoor: Optional[bool] = None
    has_stairs: Optional[bool] = None
    stairs_count: Optional[int] = None
    has_slope: Optional[bool] = None
    crosswalk_count: Optional[int] = None
    accident_risk: Optional[AccidentRisk] = None

    # 버스 구간
    bus_route_name: Optional[str] = None
    is_low_floor_bus: Optional[bool] = None  # None = 미확인
    wait_min: Optional[float] = None

    # 역/수직이동
    station_name: Optional[str] = None
    has_elevator: Optional[bool] = None  # None = 미확인
    needs_vertical_move: Optional[bool] = None


class RouteCandidate(CamelModel):
    id: str
    summary: str
    origin: str
    destination: str
    segments: list[RouteSegment]
    total_duration_min: float
    total_walk_m: float
    transfer_count: int
    path: Optional[list[LatLng]] = None


class WeatherCondition(CamelModel):
    label: str
    temp_c: float
    feels_like_c: float
    precipitation_mm: float
    is_heatwave: bool
    is_coldwave: bool
    wind_ms: float
    pm10: float
    sky: SkyCondition
    air: AirQuality


class BusArrival(CamelModel):
    route_name: str
    arrival_min: int
    is_low_floor: Optional[bool] = None  # None = 미확인
    remaining_stops: Optional[int] = None


class BusStopArrivals(CamelModel):
    stop_id: str
    stop_name: str
    arrivals: list[BusArrival]


class ScoreComponents(CamelModel):
    accessibility: float
    walk_comfort: float
    elevator: float
    low_floor_bus: float
    weather_safety: float
    safety: float
    data_reliability: float
    time_efficiency: float


class ScoreDisplay(CamelModel):
    walk_burden: float
    weather_risk: float


class RouteScore(CamelModel):
    route_id: str
    components: ScoreComponents
    display: ScoreDisplay
    final_score: float
    low_floor_status: LowFloorStatus
    reasons: list[str]
    cautions: list[str]
    voice_summary: str


class ScoredRoute(CamelModel):
    route: RouteCandidate
    score: RouteScore


class ScoringOptions(CamelModel):
    low_floor_priority: bool = False
    weather_avoid: bool = False
    avoid_stairs: bool = False


# ── 요청 모델 ──
class CandidatesRequest(CamelModel):
    origin: Place
    destination: Place


class RecommendRequest(CamelModel):
    origin: Place
    destination: Place
    profile: ProfileId = "general"
    weather_scenario: WeatherScenarioId = "normal"
    options: ScoringOptions = Field(default_factory=ScoringOptions)
    top_n: int = Field(default=3, ge=1, le=10)
