"""외부 공급자 수치가 점수화 전에 지켜야 하는 도메인 불변식."""

from datetime import datetime

import pytest
from pydantic import ValidationError

from app.models import (
    LatLng,
    RouteCandidate,
    RouteSegment,
    ShadeSummary,
    TerrainSummary,
    WeatherCondition,
)


@pytest.mark.parametrize("invalid", [-1, float("nan"), float("inf")])
def test_route_segment_rejects_invalid_duration(invalid):
    with pytest.raises(ValidationError):
        RouteSegment(
            id="walk-1",
            mode="walk",
            description="도보",
            duration_min=invalid,
        )


def test_route_candidate_rejects_negative_counts_and_distances():
    segment = RouteSegment(
        id="walk-1",
        mode="walk",
        description="도보",
        duration_min=1,
    )
    with pytest.raises(ValidationError):
        RouteCandidate(
            id="route-1",
            summary="경로",
            origin="부산역",
            destination="서면역",
            segments=[segment],
            total_duration_min=10,
            total_walk_m=-1,
            transfer_count=-1,
        )


def test_latlng_and_weather_reject_nonfinite_or_negative_measurements():
    with pytest.raises(ValidationError):
        LatLng(lat=float("nan"), lng=129.04)
    with pytest.raises(ValidationError):
        WeatherCondition(
            label="실시간",
            temp_c=25,
            feels_like_c=25,
            precipitation_mm=-1,
            wind_ms=1,
            pm10=20,
            sky="clear",
            air="good",
        )


def test_unknown_shade_cannot_be_misrepresented_as_zero_percent():
    with pytest.raises(ValidationError, match="cannot expose estimated"):
        ShadeSummary(
            status="unavailable",
            evaluated_at=datetime.fromisoformat(
                "2026-07-24T13:00:00+09:00"
            ),
            shade_ratio=0,
            source="unavailable",
            data_quality="demo",
            calculation_note="정보 없음",
        )


def test_terrain_status_must_match_available_measurements():
    with pytest.raises(ValidationError, match="estimated terrain requires"):
        TerrainSummary(
            status="estimated_90m",
            avg_slope_percent=1,
            max_slope_percent=2,
            min_slope_percent=-1,
            resolution_m=90,
        )
    with pytest.raises(ValidationError, match="cannot expose measurements"):
        TerrainSummary(
            status="unavailable",
            avg_slope_percent=0,
        )
    unavailable = TerrainSummary(
        status="unavailable",
        source="Open-Meteo Copernicus DEM GLO-90",
        resolution_m=90,
    )
    assert unavailable.avg_slope_percent is None
    assert unavailable.source == "Open-Meteo Copernicus DEM GLO-90"
    assert unavailable.resolution_m == 90


def test_live_weather_requires_both_offset_aware_observation_times():
    with pytest.raises(ValidationError, match="requires provider"):
        WeatherCondition(
            label="실시간",
            temp_c=25,
            feels_like_c=25,
            precipitation_mm=0,
            wind_ms=1,
            pm10=20,
            sky="clear",
            air="good",
        )
