"""
AI 파이프라인 전체 통합 테스트.
ODsay 없이도 동작하는 항목만 포함.

실행 (ai/ 에서): pytest tests/test_pipeline.py -v
"""
import pytest

from scoring.train import (
    auto_label, PROFILES, FEATURE_COLS, generate_synthetic_data, train_rankers
)
from scoring.predict import LOGIT_PENALTIES, predict_and_rank
from merger.route_merger import merge_route_candidates, MERGE_THRESHOLD_M
from features.extractor import _zero_features
from collectors.base import Coordinate, RouteCandidate


# ── 픽스처 ─────────────────────────────────────────────────
STAIR_HEAVY = {col: 0 for col in FEATURE_COLS}
STAIR_HEAVY.update({
    "stair_count": 8, "elevator_ratio": 0.0,
    "avg_slope_percent": 12.0, "max_slope_percent": 22.0,
    "transfer_count": 2, "walk_distance_m": 1800,
    "is_low_floor_bus": 0, "weather_risk": 0, "crowd_level": 0.3,
})

ACCESSIBLE = {col: 0 for col in FEATURE_COLS}
ACCESSIBLE.update({
    "stair_count": 0, "elevator_ratio": 1.0,
    "avg_slope_percent": 1.0, "max_slope_percent": 2.0,
    "transfer_count": 0, "walk_distance_m": 300,
    "is_low_floor_bus": 1, "weather_risk": 0, "crowd_level": 0.1,
    "shelter_nearby": 1, "crosswalk_signal_ratio": 0.9,
    "cctv_density_50m": 3.0, "aed_nearby": 1,
})


# ── 프로필 ──────────────────────────────────────────────────
def test_profiles_count():
    assert len(PROFILES) == 6

def test_profiles_names():
    assert set(PROFILES) == {"general", "elderly", "child", "teen", "disabled", "pregnant"}


# ── auto_label ──────────────────────────────────────────────
def test_accessible_beats_stair_for_all():
    for p in PROFILES:
        s_acc   = auto_label(ACCESSIBLE, p)
        s_stair = auto_label(STAIR_HEAVY, p)
        assert s_acc > s_stair, f"[{p}] 접근성({s_acc:.3f}) <= 계단({s_stair:.3f})"

def test_disabled_max_stair_penalty():
    scores = {p: auto_label(STAIR_HEAVY, p) for p in PROFILES}
    assert scores["disabled"] == min(scores.values()), \
        f"disabled 계단 패널티 최대 아님: {scores}"

def test_disabled_max_elevator_bonus():
    no_elev   = {**ACCESSIBLE, "elevator_ratio": 0.0}
    full_elev = {**ACCESSIBLE, "elevator_ratio": 1.0}
    diffs = {p: auto_label(full_elev, p) - auto_label(no_elev, p) for p in PROFILES}
    assert diffs["disabled"] == max(diffs.values()), \
        f"disabled 엘리베이터 가산 최대 아님: {diffs}"

def test_child_max_crosswalk_signal():
    no_sig   = {**ACCESSIBLE, "crosswalk_signal_ratio": 0.0}
    full_sig = {**ACCESSIBLE, "crosswalk_signal_ratio": 1.0}
    diffs = {p: auto_label(full_sig, p) - auto_label(no_sig, p) for p in PROFILES}
    assert diffs["child"] == max(diffs.values()), \
        f"child 신호등 가산 최대 아님: {diffs}"

def test_pregnant_max_weather_penalty():
    no_w   = {**ACCESSIBLE, "weather_risk": 0}
    high_w = {**ACCESSIBLE, "weather_risk": 25}
    diffs = {p: auto_label(no_w, p) - auto_label(high_w, p) for p in PROFILES}
    assert diffs["pregnant"] == max(diffs.values()), \
        f"pregnant 날씨 패널티 최대 아님: {diffs}"

def test_pregnant_max_crowd_penalty():
    no_c   = {**ACCESSIBLE, "crowd_level": 0.0}
    high_c = {**ACCESSIBLE, "crowd_level": 1.0}
    diffs = {p: auto_label(no_c, p) - auto_label(high_c, p) for p in PROFILES}
    assert diffs["pregnant"] == max(diffs.values()), \
        f"pregnant 혼잡 패널티 최대 아님: {diffs}"

def test_label_range():
    for p in PROFILES:
        for feat in [STAIR_HEAVY, ACCESSIBLE]:
            s = auto_label(feat, p)
            assert 0.0 <= s <= 1.0, f"[{p}] 범위 초과: {s}"


# ── LOGIT_PENALTIES ─────────────────────────────────────────
def test_penalties_all_profiles():
    for p in PROFILES:
        assert p in LOGIT_PENALTIES, f"{p} 패널티 없음"

def test_disabled_stair_penalty_largest():
    vals = {p: LOGIT_PENALTIES[p].get("stair_count", 0) for p in PROFILES}
    assert vals["disabled"] == max(vals.values()), \
        f"disabled stair 패널티 최대 아님: {vals}"

def test_pregnant_weather_penalty_largest():
    vals = {p: LOGIT_PENALTIES[p].get("weather_risk", 0) for p in PROFILES}
    assert vals["pregnant"] == max(vals.values()), \
        f"pregnant weather 패널티 최대 아님: {vals}"


# ── predict_and_rank ────────────────────────────────────────
@pytest.fixture(scope="module")
def rankers():
    return train_rankers()

def test_predict_top3(rankers):
    routes = [STAIR_HEAVY, ACCESSIBLE, {col: 0.5 for col in FEATURE_COLS}]
    result = predict_and_rank(rankers, routes, "elderly", top_k=3)
    assert len(result) == 3
    assert result[0]["rank"] == 1

def test_predict_prob_sum(rankers):
    routes = [STAIR_HEAVY, ACCESSIBLE, {col: 0.5 for col in FEATURE_COLS}]
    result = predict_and_rank(rankers, routes, "disabled", top_k=3)
    total  = sum(r["probability"] for r in result)
    assert abs(total - 1.0) < 0.01, f"확률 합 != 1: {total}"

def test_disabled_prefers_accessible(rankers):
    result = predict_and_rank(rankers, [STAIR_HEAVY, ACCESSIBLE], "disabled", top_k=2)
    assert result[0]["route_index"] == 1, "disabled가 접근성 경로를 1순위 선택 안 함"


# ── merger ──────────────────────────────────────────────────
def test_merge_threshold():
    assert MERGE_THRESHOLD_M == 50.0

def test_same_route_merged():
    coord = [Coordinate(35.16, 129.05), Coordinate(35.15, 129.06)]
    c1 = RouteCandidate(source="tmap",  path=coord, duration_min=10, distance_m=500)
    c2 = RouteCandidate(source="osmnx", path=coord, duration_min=11, distance_m=510)
    merged = merge_route_candidates([c1, c2])
    assert len(merged) == 1
    assert set(merged[0].sources) == {"tmap", "osmnx"}

def test_diff_route_not_merged():
    a = [Coordinate(35.16, 129.05), Coordinate(35.15, 129.06)]
    b = [Coordinate(35.20, 129.10), Coordinate(35.19, 129.11)]
    c1 = RouteCandidate(source="tmap",  path=a, duration_min=10, distance_m=500)
    c2 = RouteCandidate(source="osmnx", path=b, duration_min=20, distance_m=1500)
    merged = merge_route_candidates([c1, c2])
    assert len(merged) == 2


# ── extractor ───────────────────────────────────────────────
def test_zero_features_has_new_keys():
    zero = _zero_features()
    assert "accident_zone_count"           in zero
    assert "dongbaekjeon_store_count_300m" in zero
    assert "dongbaekjeon_store_count_200m" not in zero  # 구 키 없어야 함


# ── weather/crowd 헬퍼 ──────────────────────────────────────
def test_weather_risk():
    from api.router import _calc_weather_risk
    assert _calc_weather_risk("normal",   False) == 0.0
    assert _calc_weather_risk("heatwave", False) == 20.0
    assert _calc_weather_risk("coldwave", False) == 18.0
    assert _calc_weather_risk("heatwave", True)  == 30.0  # 1.5배 cap

def test_crowd_level_range():
    from api.router import _estimate_crowd_level
    for w in ("normal", "heatwave", "coldwave", "rain", "bad_air"):
        level = _estimate_crowd_level(w)
        assert 0.0 <= level <= 1.0, f"{w}: {level}"


# ── generate_synthetic_data ─────────────────────────────────
def test_synthetic_labels():
    """라벨은 auto_label()(0~1)을 XGBRanker용 정수 relevance 등급(0~4)으로 이산화한 값이다."""
    df = generate_synthetic_data(n_groups=5, n_routes=3)
    for p in PROFILES:
        assert f"label_{p}" in df.columns
        assert df[f"label_{p}"].between(0, 4).all()

def test_feature_cols_has_new_keys():
    assert "accident_zone_count"           in FEATURE_COLS
    assert "dongbaekjeon_store_count_300m" in FEATURE_COLS
    assert "dongbaekjeon_store_count_200m" not in FEATURE_COLS
