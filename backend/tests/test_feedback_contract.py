"""프론트 camelCase 후기·프로필 payload 계약."""
import pytest
from pydantic import ValidationError

from app.api.feedback import FacilityReportInput, ImpressionInput, PreferenceInput, ReviewInput


def test_preference_accepts_frontend_camel_case():
    payload = PreferenceInput.model_validate({
        "usesWheelchair": True,
        "avoidStairsRequired": True,
        "maxWalkDistanceM": 900,
    })
    assert payload.uses_wheelchair is True
    assert payload.avoid_stairs_required is True
    assert payload.max_walk_distance_m == 900


def test_review_and_impression_accept_frontend_camel_case():
    impression = ImpressionInput.model_validate({
        "routeId": "route-1", "rank": 1, "feedbackToken": "x" * 20,
    })
    review = ReviewInput.model_validate({
        "routeId": "route-1",
        "impressionId": "impression-1",
        "wasUsable": True,
        "rating": 4,
        "stairsDifficulty": 2,
        "crowdingDifficulty": 4,
        "transferInformationDifficulty": 3,
        "accessibilityFacilityDifficulty": 1,
        "wouldReuse": True,
        "trainingConsent": True,
    })
    assert impression.feedback_token == "x" * 20
    assert review.was_usable is True
    assert review.stairs_difficulty == 2
    assert review.crowding_difficulty == 4
    assert review.transfer_information_difficulty == 3
    assert review.accessibility_facility_difficulty == 1
    assert review.training_consent is True


def test_review_observation_dimensions_are_optional_and_bounded():
    minimal = {
        "routeId": "route-1",
        "impressionId": "impression-1",
        "wasUsable": True,
        "rating": 4,
    }
    review = ReviewInput.model_validate(minimal)
    assert review.crowding_difficulty is None
    assert review.transfer_information_difficulty is None
    assert review.accessibility_facility_difficulty is None

    for field in (
        "crowdingDifficulty",
        "transferInformationDifficulty",
        "accessibilityFacilityDifficulty",
    ):
        with pytest.raises(ValidationError):
            ReviewInput.model_validate({**minimal, field: 0})
        with pytest.raises(ValidationError):
            ReviewInput.model_validate({**minimal, field: 6})


def test_facility_report_accepts_frontend_camel_case():
    payload = FacilityReportInput.model_validate({
        "facilityName": "부산역 승강기",
        "facilityType": "승강기",
        "issueType": "relocated",
        "reportedLat": 35.1151,
        "reportedLng": 129.0414,
    })
    assert payload.facility_name == "부산역 승강기"
    assert payload.reported_lat == 35.1151


def test_facility_report_rejects_partial_or_out_of_service_location():
    with pytest.raises(ValidationError):
        FacilityReportInput.model_validate({
            "facilityName": "부산역 승강기",
            "facilityType": "승강기",
            "issueType": "relocated",
            "reportedLat": 35.1151,
        })
    with pytest.raises(ValidationError):
        FacilityReportInput.model_validate({
            "facilityName": "서울역 승강기",
            "facilityType": "승강기",
            "issueType": "relocated",
            "reportedLat": 37.5547,
            "reportedLng": 126.9707,
        })
