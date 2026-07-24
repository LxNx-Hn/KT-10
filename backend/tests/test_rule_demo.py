import hashlib
import json
from datetime import datetime
from zoneinfo import ZoneInfo

from app.data.routes import demo_candidates
from app.data.weather import WEATHER_SCENARIOS
from app.feedback_tokens import verify_feedback_token
from app.models import ScoringOptions
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


def test_result_selection_preserves_score_order_and_trait_badges():
    selected = select_representative_routes(_scored_routes(), 3)
    assert [item.score.final_score for item in selected] == sorted(
        [item.score.final_score for item in selected],
        reverse=True,
    )
    assert any(item.route.characteristics for item in selected)


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


def test_trip_condition_interactions_keep_unknown_distinct_from_zero():
    subway = next(
        item for item in _scored_routes() if item.route.id == "r2-subway"
    )
    features = route_features(
        subway,
        "pregnant",
        ScoringOptions(
            carry_luggage=True,
            stroller=True,
            shade_priority=True,
            minimize_transfers=True,
        ),
    )
    assert features["luggage_walk_burden"] == subway.route.total_walk_m
    assert features["stroller_walk_burden"] == subway.route.total_walk_m
    assert features["shade_priority_unshaded_walk_m"] is not None
    assert features["minimize_transfers_burden"] == subway.route.transfer_count


def test_rule_demo_signs_feedback_and_applies_bounded_personalization(monkeypatch):
    monkeypatch.setattr(settings, "route_mode", "demo")
    monkeypatch.setattr(
        settings,
        "session_secret",
        "test-session-secret-with-at-least-32-chars",
    )
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
    payload = verify_feedback_token(result[0].score.feedback_token)
    features = payload["features"]
    assert features["snapshot_kind"] == "demo_route_candidate"
    assert features["training_eligible"] is False
    assert features["captured_at"] != features["shade_evaluated_at"]


def test_signed_rank_matches_frontend_score_and_duration_tie_break(
    monkeypatch,
):
    monkeypatch.setattr(settings, "route_mode", "demo")
    monkeypatch.setattr(
        settings,
        "session_secret",
        "test-session-secret-with-at-least-32-chars",
    )
    selected = select_representative_routes(_scored_routes(), 2)
    selected[0].score.final_score = 80.0
    selected[1].score.final_score = 80.0
    selected[0].route.total_duration_min = 40
    selected[1].route.total_duration_min = 20

    result = personalize_and_sign(selected, "general", None)

    assert [item.route.total_duration_min for item in result] == [20, 40]
    assert [
        verify_feedback_token(item.score.feedback_token)["displayed_rank"]
        for item in result
    ] == [1, 2]


def test_live_rule_feedback_reuses_verified_enriched_snapshot(monkeypatch):
    monkeypatch.setattr(settings, "route_mode", "live")
    monkeypatch.setattr(
        settings,
        "session_secret",
        "test-session-secret-with-at-least-32-chars",
    )
    selected = select_representative_routes(_scored_routes(), 3)
    captured_at = "2026-07-24T06:00:00+00:00"
    shade_evaluated_at = "2026-07-23T05:00:00+00:00"
    for item in selected:
        route = item.route
        model_features = {
            "total_duration_min": route.total_duration_min,
            "walk_distance_m": route.total_walk_m,
            "shade_ratio": route.shade.shade_ratio,
        }
        snapshot = {
            "snapshot_schema_version": "route-feature-snapshot-v2",
            "snapshot_kind": "live_route_candidate",
            "captured_at": captured_at,
            "shade_evaluated_at": shade_evaluated_at,
            "group_id": "enriched-live-query",
            "holdout_group_id": "od-live",
            "route_id": route.id,
            "sources": ["ODsay", "GLO-90", "synthetic-demo-buildings"],
            "geometry_quality": route.geometry_quality,
            "features": model_features,
        }
        snapshot["feature_snapshot_hash"] = hashlib.sha256(
            json.dumps(
                snapshot,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            ).encode("utf-8")
        ).hexdigest()
        route.model_features = model_features
        route.model_snapshot = snapshot

    result = personalize_and_sign(selected, "general", None)
    payload = verify_feedback_token(result[0].score.feedback_token)
    features = payload["features"]
    assert features["snapshot_kind"] == "live_route_candidate"
    assert features["training_eligible"] is True
    assert features["group_id"] == "enriched-live-query"
    assert features["captured_at"] == captured_at
    assert features["shade_evaluated_at"] == shade_evaluated_at
