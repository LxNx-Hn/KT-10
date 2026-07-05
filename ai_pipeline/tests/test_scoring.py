"""XGBoost 학습 및 추론 테스트."""
import pytest
from scoring.train import train_rankers, FEATURE_COLS
from scoring.predict import predict_and_rank


@pytest.fixture(scope="module")
def rankers():
    return train_rankers()


def test_all_profiles_trained(rankers):
    """4개 프로필 모두 모델이 학습되어야 한다."""
    assert set(rankers.keys()) == {"general", "elderly", "child", "disabled"}


def test_predict_top_k(rankers):
    """top_k=3 설정 시 결과가 3개여야 한다."""
    dummy = [{col: 0.5 for col in FEATURE_COLS} for _ in range(3)]
    result = predict_and_rank(rankers, dummy, "elderly", top_k=3)
    assert len(result) == 3


def test_predict_rank_order(rankers):
    """결과는 rank 오름차순이어야 한다."""
    dummy = [{col: 0.5 for col in FEATURE_COLS} for _ in range(3)]
    result = predict_and_rank(rankers, dummy, "general", top_k=3)
    ranks = [r["rank"] for r in result]
    assert ranks == sorted(ranks)


def test_predict_probability_sum(rankers):
    """probability 합이 1.0이어야 한다 (부동소수점 허용 오차 내)."""
    dummy = [{col: 0.5 for col in FEATURE_COLS} for _ in range(3)]
    result = predict_and_rank(rankers, dummy, "general", top_k=3)
    total = sum(r["probability"] for r in result)
    assert abs(total - 1.0) < 0.01


def test_disabled_prefers_elevator(rankers):
    """
    장애인 프로필은 엘리베이터 있고 계단 없는 경로를 1순위로 선호해야 한다.
    """
    base = {col: 0.5 for col in FEATURE_COLS}
    routes = [
        {**base, "stair_count": 8, "elevator_ratio": 0.0},   # 최악
        {**base, "stair_count": 0, "elevator_ratio": 1.0},   # 최적
        {**base, "stair_count": 3, "elevator_ratio": 0.5},   # 중간
    ]
    result = predict_and_rank(rankers, routes, "disabled", top_k=3)
    best_route_idx = result[0]["route_index"]
    assert best_route_idx == 1, f"장애인 1순위가 예상(1)과 다름: {best_route_idx}"
