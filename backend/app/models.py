"""
도메인 모델 (Pydantic v2). 프론트엔드 TypeScript 타입과 1:1 대응.
JSON 직렬화는 camelCase(alias)로 이루어져 프론트엔드와 그대로 호환된다.
- Optional[...] = None → 프론트엔드의 undefined(미확인)와 동일 의미.
- 응답에서 None 필드는 제외(response_model_exclude_none)하여 "미확인"을 표현한다.
"""
from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator
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

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        allow_inf_nan=False,
    )


class LatLng(CamelModel):
    lat: float = Field(ge=-90, le=90)
    lng: float = Field(ge=-180, le=180)


class Place(CamelModel):
    id: str = Field(min_length=1, max_length=200)
    name: str = Field(min_length=1, max_length=200)
    lat: float = Field(ge=34.8, le=35.5)
    lng: float = Field(ge=128.7, le=129.4)
    category: Optional[str] = Field(default=None, max_length=200)
    address: Optional[str] = Field(default=None, max_length=500)


class RouteSegment(CamelModel):
    id: str = Field(min_length=1, max_length=200)
    mode: SegmentMode
    description: str = Field(min_length=1, max_length=500)
    duration_min: float = Field(ge=0)
    distance_m: Optional[float] = Field(default=None, ge=0)

    # 보행 구간
    outdoor: Optional[bool] = None
    has_stairs: Optional[bool] = None
    stairs_count: Optional[int] = Field(default=None, ge=0)
    has_slope: Optional[bool] = None
    crosswalk_count: Optional[int] = Field(default=None, ge=0)

    # 버스 구간
    bus_route_name: Optional[str] = None
    is_low_floor_bus: Optional[bool] = None  # None = 미확인
    wait_min: Optional[float] = Field(default=None, ge=0)

    # 역/수직이동
    station_name: Optional[str] = None
    has_elevator: Optional[bool] = None  # None = 미확인
    needs_vertical_move: Optional[bool] = None
    path: Optional[list[LatLng]] = Field(default=None, min_length=2)
    geometry_quality: Optional[Literal["exact", "mixed", "estimated"]] = None


class TerrainSummary(CamelModel):
    avg_slope_percent: Optional[float] = None
    max_slope_percent: Optional[float] = None
    min_slope_percent: Optional[float] = None
    uphill_distance_m: Optional[float] = Field(default=None, ge=0)
    downhill_distance_m: Optional[float] = Field(default=None, ge=0)
    elevation_gain_m: Optional[float] = Field(default=None, ge=0)
    elevation_loss_m: Optional[float] = Field(default=None, ge=0)
    source: Optional[str] = Field(default=None, max_length=200)
    resolution_m: Optional[int] = Field(default=None, gt=0)
    status: Literal["estimated_90m", "unavailable", "invalid"] = "unavailable"

    @model_validator(mode="after")
    def validate_status_metrics(self):
        measurements = (
            self.avg_slope_percent,
            self.max_slope_percent,
            self.min_slope_percent,
            self.uphill_distance_m,
            self.downhill_distance_m,
            self.elevation_gain_m,
            self.elevation_loss_m,
        )
        if self.status == "estimated_90m":
            if (
                self.avg_slope_percent is None
                or self.max_slope_percent is None
                or self.min_slope_percent is None
                or self.resolution_m is None
                or not self.source
            ):
                raise ValueError(
                    "estimated terrain requires slope, resolution, and source."
                )
        elif any(value is not None for value in measurements):
            raise ValueError(
                "unavailable or invalid terrain cannot expose measurements."
            )
        return self


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
    solar_elevation_deg: Optional[float] = Field(default=None, ge=-90, le=90)
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

    @model_validator(mode="after")
    def validate_status_metrics(self):
        estimated = self.status in ("estimated_demo", "estimated_public")
        if estimated and self.shade_ratio is None:
            raise ValueError("estimated shade requires shadeRatio.")
        if not estimated and any(
            value is not None
            for value in (
                self.shade_ratio,
                self.shaded_walk_m,
                self.estimate_kind,
            )
        ):
            raise ValueError(
                "unavailable or non-daylight shade cannot expose estimated metrics."
            )
        if (
            self.shaded_walk_m is not None
            and self.total_walk_m is not None
            and self.shaded_walk_m > self.total_walk_m
        ):
            raise ValueError("shadedWalkM cannot exceed totalWalkM.")
        if (
            self.known_height_building_count is not None
            and self.building_count is not None
            and self.known_height_building_count > self.building_count
        ):
            raise ValueError(
                "knownHeightBuildingCount cannot exceed buildingCount."
            )
        return self


class TraitEvidence(CamelModel):
    feature: str
    value: str | float | int | bool | None = None
    unit: Optional[str] = None
    source: str


class RouteTraitLabel(CamelModel):
    label_id: str
    display_label: str
    evidence_status: Literal["observed", "derived", "unavailable"]
    evidence: list[TraitEvidence] = Field(default_factory=list)


class RouteCandidate(CamelModel):
    id: str = Field(min_length=1, max_length=200)
    summary: str = Field(min_length=1, max_length=500)
    origin: str = Field(min_length=1, max_length=200)
    destination: str = Field(min_length=1, max_length=200)
    segments: list[RouteSegment] = Field(min_length=1, max_length=200)
    total_duration_min: float = Field(gt=0)
    total_walk_m: float = Field(ge=0)
    transfer_count: int = Field(ge=0)
    path: Optional[list[LatLng]] = Field(default=None, min_length=2, max_length=50_000)
    sources: list[str] = Field(default_factory=list)
    geometry_quality: Optional[Literal["exact", "mixed", "estimated"]] = None
    terrain: Optional[TerrainSummary] = None
    shade: Optional[ShadeSummary] = None
    trait_labels: list[RouteTraitLabel] = Field(default_factory=list)
    # AI 수집 단계의 검증된 수치 피처. 백엔드가 건물 그늘을 결합한 뒤
    # 내부 rank endpoint에 다시 보낼 때만 쓰며 클라이언트 응답에는 노출하지 않는다.
    model_features: dict[str, float | int | bool | None] = Field(
        default_factory=dict,
        exclude=True,
    )
    model_snapshot: dict = Field(default_factory=dict, exclude=True)
    model_group_id: Optional[str] = Field(default=None, exclude=True)
    model_holdout_group_id: Optional[str] = Field(default=None, exclude=True)
    model_snapshot_hash: Optional[str] = Field(default=None, exclude=True)
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
    label: str = Field(min_length=1, max_length=100)
    temp_c: float
    feels_like_c: float
    precipitation_mm: float = Field(ge=0)
    is_heatwave: Optional[bool] = None
    is_coldwave: Optional[bool] = None
    wind_ms: float = Field(ge=0)
    pm10: float = Field(ge=0)
    sky: SkyCondition
    air: AirQuality
    observed_at: Optional[datetime] = None
    air_quality_observed_at: Optional[datetime] = None

    @model_validator(mode="after")
    def validate_observation_times(self):
        if (self.observed_at is None) != (
            self.air_quality_observed_at is None
        ):
            raise ValueError(
                "weather and air-quality observation times must be paired."
            )
        if self.label == "실시간" and self.observed_at is None:
            raise ValueError(
                "live weather requires provider observation times."
            )
        if self.observed_at is not None and (
            self.observed_at.tzinfo is None
            or self.air_quality_observed_at is None
            or self.air_quality_observed_at.tzinfo is None
        ):
            raise ValueError("weather observation times require UTC offsets.")
        return self


class BusArrival(CamelModel):
    route_name: str
    vehicle_no: Optional[str] = None
    arrival_min: Optional[int] = Field(default=None, ge=0)
    arrival_message: Optional[str] = None
    is_low_floor: Optional[bool] = None  # None = 미확인
    remaining_stops: Optional[int] = Field(default=None, ge=0)


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
    final_score: float = Field(ge=0, le=100)
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
