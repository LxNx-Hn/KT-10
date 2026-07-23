"""
도메인 모델 (Pydantic v2). 프론트엔드 TypeScript 타입과 1:1 대응.
JSON 직렬화는 camelCase(alias)로 이루어져 프론트엔드와 그대로 호환된다.
- Optional[...] = None → 프론트엔드의 undefined(미확인)와 동일 의미.
- 응답에서 None 필드는 제외(response_model_exclude_none)하여 "미확인"을 표현한다.
"""
from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

ProfileId = Literal[
    "general", "elderly", "child", "youth", "disabled", "pregnant"
]
SegmentMode = Literal["walk", "bus", "subway", "transfer"]
AirQuality = Literal["good", "moderate", "bad", "very_bad"]
SkyCondition = Literal["clear", "cloudy", "rain", "snow"]
WeatherScenarioId = Literal["normal", "heatwave", "coldwave", "rain", "dust"]
LowFloorStatus = Literal["confirmed", "regular", "unknown", "none"]


class CamelModel(BaseModel):
    """snake_case 속성 + camelCase JSON. 입력은 양쪽 모두 허용."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class LatLng(CamelModel):
    lat: float
    lng: float


class Place(CamelModel):
    id: str
    name: str
    lat: float = Field(ge=34.8, le=35.5)
    lng: float = Field(ge=128.7, le=129.4)
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

    # 버스 구간
    bus_route_name: Optional[str] = None
    is_low_floor_bus: Optional[bool] = None  # None = 미확인
    wait_min: Optional[float] = None

    # 역/수직이동
    station_name: Optional[str] = None
    has_elevator: Optional[bool] = None  # None = 미확인
    needs_vertical_move: Optional[bool] = None
    path: Optional[list[LatLng]] = None
    geometry_quality: Optional[Literal["exact", "mixed", "estimated"]] = None


class TerrainSummary(CamelModel):
    avg_slope_percent: Optional[float] = None
    max_slope_percent: Optional[float] = None
    min_slope_percent: Optional[float] = None
    uphill_distance_m: Optional[float] = None
    downhill_distance_m: Optional[float] = None
    elevation_gain_m: Optional[float] = None
    elevation_loss_m: Optional[float] = None
    source: Optional[str] = None
    resolution_m: Optional[int] = None
    status: Literal["estimated_90m", "unavailable", "invalid"] = "unavailable"


class ShadePathSegment(CamelModel):
    start: LatLng
    end: LatLng
    shaded: bool


class ShadeSummary(CamelModel):
    status: Literal["estimated_demo", "estimated_public", "not_daylight", "unavailable"]
    evaluated_at: datetime
    shade_ratio: Optional[float] = Field(default=None, ge=0, le=1)
    shaded_walk_m: Optional[float] = Field(default=None, ge=0)
    total_walk_m: Optional[float] = Field(default=None, ge=0)
    solar_azimuth_deg: Optional[float] = Field(default=None, ge=0, lt=360)
    solar_elevation_deg: Optional[float] = None
    building_height_coverage: Optional[float] = Field(default=None, ge=0, le=1)
    building_count: Optional[int] = Field(default=None, ge=0)
    known_height_building_count: Optional[int] = Field(default=None, ge=0)
    estimate_kind: Optional[Literal["estimate", "lower_bound"]] = None
    overlay_resolution_m: Optional[float] = Field(default=None, gt=0)
    walking_geometry_quality: Optional[
        Literal["exact", "mixed", "estimated"]
    ] = None
    includes_tree_shade: bool = False
    includes_terrain_shadow: bool = False
    source: str
    data_quality: Literal["demo", "public", "measured"]
    shadow_polygons: list[list[LatLng]] = Field(default_factory=list)
    path_segments: list[ShadePathSegment] = Field(default_factory=list)
    calculation_note: str


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
    sources: list[str] = Field(default_factory=list)
    geometry_quality: Optional[Literal["exact", "mixed", "estimated"]] = None
    terrain: Optional[TerrainSummary] = None
    shade: Optional[ShadeSummary] = None
    characteristics: list[
        Literal[
            "fastest",
            "shortest_walk",
            "lowest_slope",
            "most_shade",
            "fewest_transfers",
            "stair_free",
            "low_floor_confirmed",
        ]
    ] = Field(default_factory=list)


class WeatherCondition(CamelModel):
    label: str
    temp_c: float
    feels_like_c: float
    precipitation_mm: float
    is_heatwave: Optional[bool] = None
    is_coldwave: Optional[bool] = None
    wind_ms: float
    pm10: float
    sky: SkyCondition
    air: AirQuality


class BusArrival(CamelModel):
    route_name: str
    vehicle_no: Optional[str] = None
    arrival_min: Optional[int] = None
    arrival_message: Optional[str] = None
    is_low_floor: Optional[bool] = None  # None = 미확인
    remaining_stops: Optional[int] = None


class BusStopArrivals(CamelModel):
    stop_id: str
    stop_name: str
    arrivals: list[BusArrival]


class ScoreComponents(CamelModel):
    accessibility: Optional[float] = None
    walk_comfort: Optional[float] = None
    slope_comfort: Optional[float] = None
    shade_comfort: Optional[float] = None
    transfer_simplicity: Optional[float] = None
    elevator: Optional[float] = None
    low_floor_bus: Optional[float] = None
    weather_safety: Optional[float] = None
    safety: Optional[float] = None
    data_reliability: Optional[float] = None
    time_efficiency: Optional[float] = None


class ScoreDisplay(CamelModel):
    walk_burden: Optional[float] = None
    weather_risk: Optional[float] = None


class RouteScore(CamelModel):
    route_id: str
    components: ScoreComponents
    display: ScoreDisplay
    final_score: float
    low_floor_status: LowFloorStatus
    reasons: list[str]
    cautions: list[str]
    voice_summary: str
    feedback_token: Optional[str] = None
    score_kind: Literal[
        "rule_baseline", "judge_baseline", "human_model"
    ] = "rule_baseline"


class ScoredRoute(CamelModel):
    route: RouteCandidate
    score: RouteScore


class ScoringOptions(CamelModel):
    carry_luggage: bool = False
    stroller: bool = False
    low_floor_priority: bool = False
    weather_avoid: bool = False
    avoid_stairs: bool = False
    shade_priority: bool = False
    minimize_transfers: bool = False
    departure_at: Optional[datetime] = None


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
