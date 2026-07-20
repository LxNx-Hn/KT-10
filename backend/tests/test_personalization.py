import pytest

from app.personalization import (
    PersonalizationStateError, blended_rank_score, parse_state, predict,
    reward_target, update_state,
)


def test_reward_uses_only_explicit_review_answers():
    weights = {"usable_weight": 1, "rating_weight": 1, "reuse_weight": 1}
    assert reward_target(was_usable=True, rating=5, would_reuse=True, **weights) == 1.0
    assert reward_target(was_usable=False, rating=1, would_reuse=False, **weights) == 0.0
    assert reward_target(was_usable=True, rating=3, would_reuse=None, **weights) == 0.75


def test_positive_reviews_raise_personal_prediction():
    features = {"elevator_ratio": 1, "stair_count": 0, "walk_distance_m": 200}
    state = parse_state(None)
    before = predict(state, features)
    for _ in range(5):
        state = update_state(state, features, 1.0, learning_rate_base=0.35, regularization=0.01)
    assert state["updates"] == 5
    assert predict(state, features) > before


def test_personal_model_influence_grows_with_real_updates():
    features = {"elevator_ratio": 1, "stair_count": 0}
    empty = parse_state(None)
    assert blended_rank_score(0.8, empty, features, max_personal_share=0.65, prior_reviews=5) == 0.8
    state = empty
    for _ in range(10):
        state = update_state(state, features, 0.0, learning_rate_base=0.35, regularization=0.01)
    assert blended_rank_score(0.8, state, features, max_personal_share=0.65, prior_reviews=5) < 0.8


def test_missing_feature_is_distinct_from_observed_zero():
    from app.personalization import vector

    assert vector({})["stair_count__known"] == 0
    assert vector({"stair_count": 0})["stair_count__known"] == 1


def test_corrupted_personalization_state_is_not_silently_reset():
    with pytest.raises(PersonalizationStateError, match="손상"):
        parse_state("not-json")
    with pytest.raises(PersonalizationStateError, match="버전"):
        parse_state('{"version":2,"bias":0,"weights":{},"updates":0}')
