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


class WheelchairRoutingRestrictions(CamelModel):
    """공급자에 실제 전달된 휠체어 통행 제한값."""

    surface_type: str = Field(min_length=1, max_length=100)
    track_type: str = Field(min_length=1, max_length=100)
    smoothness_type: str = Field(min_length=1, max_length=100)
    maximum_sloped_kerb: float = Field(ge=0, le=0.15)
    maximum_incline: float = Field(ge=0, le=30)
    minimum_width: float = Field(gt=0, le=5)


class WheelchairExtraResponseKeys(CamelModel):
    """ORS 응답에서 실제 검증한 extra_info 키 이름."""

    steepness: str = Field(min_length=1, max_length=30)
    suitability: str = Field(min_length=1, max_length=30)
    surface: str = Field(min_length=1, max_length=30)
    waytype: str = Field(min_length=1, max_length=30)
    osmid: str = Field(min_length=1, max_length=30)


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
    # 물리 경사로는 DEM 지형 경사와 별개다. 공급자 응답에 경사로 안내점이
    # 있을 때만 좌표와 근거를 노출한다.
    ramp_points: Optional[list[LatLng]] = Field(
        default=None,
        min_length=1,
        max_length=100,
    )
    ramp_replaces_stairs: Optional[bool] = None
    ramp_evidence_source: Optional[str] = Field(default=None, max_length=200)
    stairs_excluded_by_provider: Optional[bool] = None
    # ORS wheelchair profile의 노면·폭·턱·경사·계단 제한이 실제 탐색에
    # 적용된 경우에만 True다. OSM 누락/임시 장애물 한계도 반드시 함께 보낸다.
    wheelchair_constraints_applied: Optional[bool] = None
    wheelchair_constraint_source: Optional[str] = Field(
        default=None,
        max_length=200,
    )
    wheelchair_restrictions: Optional[WheelchairRoutingRestrictions] = None
    wheelchair_data_limitations: Optional[list[str]] = Field(
        default=None,
        min_length=1,
        max_length=20,
    )
    wheelchair_constraint_categories: Optional[list[str]] = Field(
        default=None,
        min_length=1,
        max_length=20,
    )
    wheelchair_extra_info_full_route_coverage: Optional[bool] = None
    wheelchair_extra_response_keys: Optional[
        WheelchairExtraResponseKeys
    ] = None
    crosswalk_count: Optional[int] = Field(default=None, ge=0)

    # 버스 구간
    bus_route_name: Optional[str] = None
    is_low_floor_bus: Optional[bool] = None  # None = 미확인
    wait_min: Optional[float] = Field(default=None, ge=0)

    # 대중교통 공급자가 경로검색 응답에 함께 제공한 탑승 metadata.
    # 실시간/시간표 도착 조회는 선택 경로 상세를 열 때만 이 식별자를 사용한다.
    transit_start_id: Optional[str] = Field(default=None, max_length=100)
    transit_end_id: Optional[str] = Field(default=None, max_length=100)
    transit_route_id: Optional[str] = Field(default=None, max_length=100)
    transit_direction: Optional[str] = Field(default=None, max_length=200)
    transit_direction_code: Optional[int] = Field(default=None, ge=1, le=2)
    transit_interval_min: Optional[int] = Field(default=None, ge=0)
    fast_boarding_position: Optional[str] = Field(default=None, max_length=100)
    start_exit_no: Optional[str] = Field(default=None, max_length=50)
    end_exit_no: Optional[str] = Field(default=None, max_length=50)
    smart_shelter_name: Optional[str] = Field(default=None, max_length=200)

    # 역/수직이동
    station_name: Optional[str] = None
    end_station_name: Optional[str] = None
    has_elevator: Optional[bool] = None  # None = 미확인
    needs_vertical_move: Optional[bool] = None
    # 역 단위 시설 재고이며 출구·보행 선형과 일치한다는 뜻이 아니다.
    station_external_ramp_count: Optional[int] = Field(default=None, ge=0)
    station_wheelchair_lift_count: Optional[int] = Field(default=None, ge=0)
    station_accessibility_evidence_source: Optional[str] = Field(
        default=None,
        max_length=200,
    )
    station_ramp_route_match: Optional[bool] = None
    # 공식 출구-승강장 엘리베이터 이동경로와 공급자 출구번호가 정확히
    # 일치한 경우만 True다. 미일치·미제공은 False가 아니라 None이다.
    start_station_elevator_exit_match: Optional[bool] = None
    end_station_elevator_exit_match: Optional[bool] = None
    station_elevator_route_evidence_source: Optional[str] = Field(
        default=None,
        max_length=200,
    )
    path: Optional[list[LatLng]] = Field(default=None, min_length=2)
    geometry_quality: Optional[Literal["exact", "mixed", "estimated"]] = None

    @model_validator(mode="after")
    def validate_accessibility_evidence(self):
        if self.has_slope is True and (
            not self.ramp_points or not self.ramp_evidence_source
        ):
            raise ValueError(
                "has_slope=True requires ramp_points and ramp_evidence_source"
            )
        if self.ramp_points and (
            self.has_slope is not True or not self.ramp_evidence_source
        ):
            raise ValueError(
                "ramp_points require has_slope=True and ramp_evidence_source"
            )
        if self.ramp_replaces_stairs is True and not self.ramp_points:
            raise ValueError("ramp_replaces_stairs=True requires ramp_points")
        if self.stairs_excluded_by_provider is True and (
            self.has_stairs is True
            or (
                self.stairs_count is not None
                and self.stairs_count > 0
            )
        ):
            raise ValueError(
                "stairs_excluded_by_provider=True conflicts with "
                "known stairs"
            )
        if self.wheelchair_constraints_applied is True and not (
            self.wheelchair_constraint_source
            and self.wheelchair_restrictions is not None
            and self.wheelchair_data_limitations
            and self.wheelchair_constraint_categories
            and self.stairs_excluded_by_provider is True
            and self.wheelchair_extra_info_full_route_coverage is True
            and self.wheelchair_extra_response_keys is not None
        ):
            raise ValueError(
                "wheelchair_constraints_applied=True requires source, "
                "restrictions, limitations, stair exclusion, and full "
                "extra-info coverage"
            )
        if any((
            self.wheelchair_constraint_source,
            self.wheelchair_restrictions,
            self.wheelchair_data_limitations,
            self.wheelchair_constraint_categories,
            self.wheelchair_extra_info_full_route_coverage is not None,
            self.wheelchair_extra_response_keys,
        )) and self.wheelchair_constraints_applied is not True:
            raise ValueError(
                "wheelchair constraint evidence requires "
                "wheelchair_constraints_applied=True"
            )
        station_inventory = (
            self.station_external_ramp_count is not None
            or self.station_wheelchair_lift_count is not None
        )
        if station_inventory and not self.station_accessibility_evidence_source:
            raise ValueError(
                "station accessibility inventory requires evidence source"
            )
        if self.station_ramp_route_match is not None:
            raise ValueError(
                "station ramp route match requires exit-level geometry"
            )
        elevator_matches = (
            self.start_station_elevator_exit_match,
            self.end_station_elevator_exit_match,
        )
        if False in elevator_matches:
            raise ValueError(
                "unverified station elevator exit match must be null"
            )
        if any(value is True for value in elevator_matches) and not (
            self.station_elevator_route_evidence_source
        ):
            raise ValueError(
                "station elevator exit match requires evidence source"
            )
        if self.station_elevator_route_evidence_source and not any(
            value is True for value in elevator_matches
        ):
            raise ValueError(
                "station elevator route source requires a verified exit match"
            )
        return self


class TerrainSlopeSegment(CamelModel):
    start: LatLng
    end: LatLng
    slope_percent: float
    distance_m: float = Field(gt=0)
    # start~end 사이를 원본 보행 polyline 정점으로 채운 표시용 경로. 경사는
    # 90m 표본 간 직선으로 계산하므로 이 값은 지도 렌더링에만 쓴다. 공급자가
    # 주지 않으면 빈 목록이며, 그때 지도는 start/end 직선으로 되돌아간다.
    path: list[LatLng] = Field(default_factory=list)


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
    slope_segments: list[TerrainSlopeSegment] = Field(default_factory=list)
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
        elif any(value is not None for value in measurements) or self.slope_segments:
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
    # 대중교통 지연 정밀화 서술자(원본 mapObj 포함). 서버 내부 전용이며
    # 어떤 API 응답에도 직렬화되지 않는다.
    transit_refinement: Optional[dict] = Field(default=None, exclude=True)
    # 후보별 정밀화 상태: not_loaded | loading | exact | failed
    transit_refinement_state: Literal[
        "not_loaded", "loading", "exact", "failed"
    ] = Field(default="exact", exclude=True)
    transit_refined_at: Optional[datetime] = Field(default=None, exclude=True)
    # 실패 재시도 정책 metadata. 서버 내부 전용이며 응답에 노출하지 않는다.
    transit_refinement_failure_code: Optional[str] = Field(
        default=None,
        exclude=True,
    )
    transit_refinement_failed_at: Optional[datetime] = Field(
        default=None,
        exclude=True,
    )
    transit_refinement_retry_after: Optional[datetime] = Field(
        default=None,
        exclude=True,
    )
    transit_refinement_failure_permanent: bool = Field(
        default=False,
        exclude=True,
    )
    transit_refinement_failure_count: int = Field(default=0, exclude=True)
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
        "rule_baseline", "bootstrap_baseline", "human_model"
    ] = "rule_baseline"


class ScoredRoute(CamelModel):
    route: RouteCandidate
    score: RouteScore
    route_set_token: Optional[str] = Field(default=None, min_length=20, max_length=64)


class ScoringOptions(CamelModel):
    carry_luggage: bool = False
    stroller: bool = False
    low_floor_priority: bool = False
    weather_avoid: bool = False
    avoid_stairs: bool = False
    # 계정 장기 설정과 별개인 이번 경로검색 세션의 휠체어 모드.
    # True이면 단순 가중치가 아니라 ORS 검증 후보만 허용한다.
    uses_wheelchair: bool = False
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
    # 생략 시 서버 운영 기본값(ROUTE_DEFAULT_TOP_N)을 사용한다.
    top_n: int | None = Field(default=None, ge=1, le=10)


class RouteExplanationRequest(CamelModel):
    route_set_token: str = Field(min_length=20, max_length=64)
    route_id: str = Field(min_length=1, max_length=200)


class RouteExplanationResponse(CamelModel):
    route_id: str
    explanation: str
    provider: Literal["nvidia_nim"]


class ShadeRefreshRequest(CamelModel):
    route_set_token: str = Field(min_length=20, max_length=64)
    profile: ProfileId = "general"
    options: ScoringOptions = Field(default_factory=ScoringOptions)
    top_n: int | None = Field(default=None, ge=1, le=10)


class RouteSetRescoreRequest(ShadeRefreshRequest):
    """기존 후보군을 재사용하는 프로필·조건·날씨 재채점 요청."""

    weather_scenario: Optional[WeatherScenarioId] = None


class TransitRefineRequest(CamelModel):
    """기존 추천 카드 선택 시 해당 후보의 대중교통 선형만 정밀화한다."""

    route_set_token: str = Field(min_length=20, max_length=64)
    route_id: str = Field(min_length=1, max_length=200)


class TransitRefinementResponse(CamelModel):
    """표시 geometry만 교체한다. score·rank·model snapshot은 포함하지 않는다."""

    route_id: str
    path: list[LatLng] = Field(min_length=2, max_length=50_000)
    segments: list[RouteSegment] = Field(min_length=1, max_length=200)
    geometry_quality: Literal["exact", "mixed", "estimated"]
    refined_at: Optional[datetime] = None


class TransitArrivalsRequest(CamelModel):
    """선택한 기존 후보의 버스 실시간·지하철 시간표 도착 조회."""

    route_set_token: str = Field(min_length=20, max_length=64)
    route_id: str = Field(min_length=1, max_length=200)


class TransitLegArrival(CamelModel):
    segment_id: str
    mode: Literal["bus", "subway"]
    status: Literal["live", "scheduled", "unavailable"]
    route_name: Optional[str] = None
    boarding_stop_name: Optional[str] = None
    direction: Optional[str] = None
    arrival_min: Optional[int] = Field(default=None, ge=0)
    arrival_message: Optional[str] = None
    departure_time: Optional[str] = Field(
        default=None,
        pattern=r"^([01]\d|2[0-3]):[0-5]\d(?::[0-5]\d)?$",
    )
    destination_arrival_time: Optional[str] = Field(
        default=None,
        pattern=r"^([01]\d|2[0-3]):[0-5]\d(?::[0-5]\d)?$",
    )
    observed_at: datetime
    source: str


class TransitArrivalsResponse(CamelModel):
    route_id: str
    arrivals: list[TransitLegArrival] = Field(max_length=200)
