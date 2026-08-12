from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.main import _filter_wheelchair_candidates
from app.models import RouteCandidate, RouteSegment, ScoringOptions
from app.providers.ai_pipeline import _pipeline_payload
from app.wheelchair import effective_scoring_options, filter_known_stair_candidates


def _candidate(
    route_id: str,
    *,
    stairs: bool | None,
    count: int | None,
    provider_excluded: bool | None = None,
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


def test_wheelchair_keeps_only_provider_verified_stair_excluded_candidates():
    candidates = [
        _candidate("stairs", stairs=True, count=3),
        _candidate("unknown", stairs=None, count=None),
        _candidate("unverified-clear", stairs=False, count=0),
        _candidate(
            "verified-clear",
            stairs=False,
            count=0,
            provider_excluded=True,
        ),
    ]

    filtered = filter_known_stair_candidates(
        candidates,
        SimpleNamespace(uses_wheelchair=True),
    )

    assert [candidate.id for candidate in filtered] == ["verified-clear"]


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
    assert "계단 제외로 확인" in error.value.detail


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
