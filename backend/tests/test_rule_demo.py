import json
from datetime import datetime
from zoneinfo import ZoneInfo

from app.data.routes import demo_candidates
from app.data.weather import WEATHER_SCENARIOS
from app.rule_demo import personalize_and_sign, route_features, select_representative_routes
from app.scoring import recommend_routes
from app.settings import settings
from app.shade import add_demo_shade, assign_characteristics


def _scored_routes():
    routes = assign_characteristics(add_demo_shade(
        demo_candidates(),
        datetime(2026, 7, 23, 14, 0, tzinfo=ZoneInfo("Asia/Seoul")),
    ))
    return recommend_routes(
        routes, WEATHER_SCENARIOS["normal"], "general", top_n=len(routes)
    )


def test_representatives_preserve_route_characteristic_winners():
    selected = select_representative_routes(_scored_routes(), 3)
    characteristics = {
        characteristic
        for item in selected
        for characteristic in item.route.characteristics
    }
    assert characteristics == {"fastest", "lowest_slope", "most_shade"}


def test_unknown_route_attributes_are_not_converted_to_zero():
    subway = next(
        item for item in _scored_routes() if item.route.id == "r2-subway"
    )
    features = route_features(subway, "general")
    assert features["stair_count"] is None
    overpass = next(
        item for item in _scored_routes() if item.route.id == "r1-overpass"
    )
    assert route_features(overpass, "general")["crosswalk_count"] is None


def test_rule_demo_signs_feedback_and_applies_bounded_personalization(monkeypatch):
    monkeypatch.setattr(settings, "session_secret", "test-session-secret")
    monkeypatch.setattr(settings, "personalization_max_share", 0.35)
    monkeypatch.setattr(settings, "personalization_prior_reviews", 5.0)
    monkeypatch.setattr(settings, "personalization_learning_rate", 0.25)
    monkeypatch.setattr(settings, "personalization_regularization", 0.02)
    monkeypatch.setattr(settings, "personalization_usable_weight", 0.45)
    monkeypatch.setattr(settings, "personalization_rating_weight", 0.35)
    monkeypatch.setattr(settings, "personalization_reuse_weight", 0.20)
    selected = select_representative_routes(_scored_routes(), 3)
    state = json.dumps({
        "version": 1,
        "bias": 0.0,
        "weights": {"shade_ratio": 2.0},
        "updates": 5,
    })
    result = personalize_and_sign(selected, "general", state)
    assert all(item.score.feedback_token for item in result)
    assert all(0 <= item.score.final_score <= 100 for item in result)
