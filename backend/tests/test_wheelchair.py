from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.main import _filter_wheelchair_candidates
from app.models import (
    RouteCandidate,
    RouteSegment,
    ScoreComponents,
    ScoringOptions,
    WeatherCondition,
)
from app.providers.ai_pipeline import _pipeline_payload
from app.scoring.explain import build_cautions, build_reasons
from app.wheelchair import effective_scoring_options, filter_known_stair_candidates


def _candidate(
    route_id: str,
    *,
    stairs: bool | None,
    count: int | None,
    provider_excluded: bool | None = None,
    wheelchair_constrained: bool = False,
) -> RouteCandidate:
    return RouteCandidate(
        id=route_id,
        summary=route_id,
        origin="출발",
        destination="도착",
        total_duration_min=10,
        total_walk_m=100,
        transfer_count=0,
        segments=[
            RouteSegment(
                id=f"{route_id}-walk",
                mode="walk",
                description="도보",
                duration_min=10,
                distance_m=100,
                has_stairs=stairs,
                stairs_count=count,
                stairs_excluded_by_provider=provider_excluded,
                wheelchair_constraints_applied=(
                    True if wheelchair_constrained else None
                ),
                wheelchair_constraint_source=(
                    "openrouteservice wheelchair profile"
                    if wheelchair_constrained
                    else None
                ),
                wheelchair_restrictions=(
                    {
                        "surface_type": "cobblestone:flattened",
                        "track_type": "grade1",
                        "smoothness_type": "good",
                        "maximum_sloped_kerb": 0.06,
                        "maximum_incline": 6,
                        "minimum_width": 0.9,
                    }
                    if wheelchair_constrained
                    else None
                ),
                wheelchair_data_limitations=(
                    ["OSM 태그 누락 가능"]
                    if wheelchair_constrained
                    else None
                ),
                wheelchair_constraint_categories=(
                    ["steps", "surface", "width", "wheelchair_access"]
                    if wheelchair_constrained
                    else None
                ),
                wheelchair_extra_info_full_route_coverage=(
                    True if wheelchair_constrained else None
                ),
                wheelchair_extra_response_keys=(
                    {
                        "steepness": "steepness",
                        "suitability": "suitability",
                        "surface": "surface",
                        "waytype": "waytypes",
                        "osmid": "osmId",
                    }
                    if wheelchair_constrained
                    else None
                ),
            )
        ],
    )


def test_wheelchair_preference_enforces_avoid_stairs_without_mutating_request():
    requested = ScoringOptions(avoid_stairs=False)
    preference = SimpleNamespace(uses_wheelchair=True)

    effective = effective_scoring_options(requested, preference)

    assert requested.avoid_stairs is False
    assert effective.avoid_stairs is True


def test_non_wheelchair_preference_keeps_requested_stair_option():
    requested = ScoringOptions(avoid_stairs=False)

    effective = effective_scoring_options(
        requested,
        SimpleNamespace(uses_wheelchair=False),
    )

    assert effective is requested
    assert effective.avoid_stairs is False


def test_request_wheelchair_mode_is_independent_of_saved_preference():
    requested = ScoringOptions(
        avoid_stairs=False,
        uses_wheelchair=True,
    )

    effective = effective_scoring_options(
        requested,
        SimpleNamespace(uses_wheelchair=False),
    )

    assert effective.uses_wheelchair is True
    assert effective.avoid_stairs is True


def test_wheelchair_keeps_only_provider_verified_stair_excluded_candidates():
    candidates = [
        _candidate("stairs", stairs=True, count=3),
        _candidate("unknown", stairs=None, count=None),
        _candidate("unverified-clear", stairs=False, count=0),
        _candidate(
            "stairs-only",
            stairs=False,
            count=0,
            provider_excluded=True,
        ),
        _candidate(
            "verified-clear",
            stairs=None,
            count=None,
            provider_excluded=True,
            wheelchair_constrained=True,
        ),
    ]

    filtered = filter_known_stair_candidates(
        candidates,
        SimpleNamespace(uses_wheelchair=True),
    )

    assert [candidate.id for candidate in filtered] == ["verified-clear"]


def test_request_wheelchair_mode_filters_without_account_preference():
    filtered = filter_known_stair_candidates(
        [
            _candidate("unverified", stairs=None, count=None),
            _candidate(
                "verified",
                stairs=None,
                count=None,
                provider_excluded=True,
                wheelchair_constrained=True,
            ),
        ],
        None,
        request_uses_wheelchair=True,
    )

    assert [candidate.id for candidate in filtered] == ["verified"]


def test_wheelchair_transit_requires_low_floor_bus_and_both_station_exits():
    ordinary_bus = _candidate(
        "ordinary-bus",
        stairs=None,
        count=None,
        provider_excluded=True,
        wheelchair_constrained=True,
    )
    ordinary_bus.segments.append(RouteSegment(
        id="ordinary-bus-leg",
        mode="bus",
        description="일반버스",
        duration_min=5,
        is_low_floor_bus=None,
    ))
    low_floor_bus = ordinary_bus.model_copy(deep=True)
    low_floor_bus.id = "low-floor-bus"
    low_floor_bus.segments[-1].is_low_floor_bus = True

    unknown_subway = _candidate(
        "unknown-subway",
        stairs=None,
        count=None,
        provider_excluded=True,
        wheelchair_constrained=True,
    )
    unknown_subway.segments.append(RouteSegment(
        id="unknown-subway-leg",
        mode="subway",
        description="도시철도",
        duration_min=5,
    ))
    verified_subway = _candidate(
        "verified-subway",
        stairs=None,
        count=None,
        provider_excluded=True,
        wheelchair_constrained=True,
    )
    verified_subway.segments.append(RouteSegment(
        id="verified-subway-leg",
        mode="subway",
        description="도시철도",
        duration_min=5,
        start_station_elevator_exit_match=True,
        end_station_elevator_exit_match=True,
        station_elevator_route_evidence_source="부산교통공사 공식 이동경로",
    ))

    filtered = filter_known_stair_candidates(
        [ordinary_bus, low_floor_bus, unknown_subway, verified_subway],
        None,
        request_uses_wheelchair=True,
    )

    assert [candidate.id for candidate in filtered] == [
        "low-floor-bus",
        "verified-subway",
    ]


def test_recommendation_boundary_rejects_unverified_wheelchair_route():
    user = SimpleNamespace(
        preference=SimpleNamespace(uses_wheelchair=True),
    )

    with pytest.raises(HTTPException) as error:
        _filter_wheelchair_candidates(
            [_candidate("unverified", stairs=False, count=0)],
            user,
        )

    assert error.value.status_code == 422
    assert "휠체어 통행 제약" in error.value.detail


def test_pipeline_sends_wheelchair_stair_constraint():
    origin = SimpleNamespace(lat=35.1, lng=129.0, name="출발")
    destination = SimpleNamespace(lat=35.2, lng=129.1, name="도착")

    payload = _pipeline_payload(
        origin,
        destination,
        "disabled",
        "normal",
        ScoringOptions(),
        SimpleNamespace(
            uses_wheelchair=True,
            uses_walking_aid=False,
            avoid_stairs_required=False,
            max_walk_distance_m=None,
        ),
    )

    assert payload["uses_wheelchair"] is True
    assert payload["avoid_stairs"] is True


def test_pipeline_sends_request_scoped_wheelchair_mode():
    payload = _pipeline_payload(
        SimpleNamespace(lat=35.1, lng=129.0, name="출발"),
        SimpleNamespace(lat=35.2, lng=129.1, name="도착"),
        "disabled",
        "normal",
        ScoringOptions(uses_wheelchair=True),
        None,
    )

    assert payload["uses_wheelchair"] is True
    assert payload["avoid_stairs"] is True


def test_wheelchair_explanation_states_constraints_and_real_world_limit():
    route = _candidate(
        "wheelchair-ready",
        stairs=None,
        count=None,
        provider_excluded=True,
        wheelchair_constrained=True,
    )
    components = ScoreComponents()
    weather = WeatherCondition(
        label="테스트",
        temp_c=20,
        feels_like_c=20,
        precipitation_mm=0,
        wind_ms=1,
        pm10=20,
        sky="clear",
        air="good",
    )

    reasons = build_reasons(route, components, "none")
    cautions = build_cautions(route, components, "none", weather)

    assert any("지도에 기록된 계단·노면·폭·턱·경사 제한" in item for item in reasons)
    assert any("임시 장애물" in item for item in cautions)
