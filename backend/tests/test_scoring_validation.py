"""
점수 검증 (기획서 §8) — 프론트엔드 TS 엔진과 동일한 결과인지 파리티까지 확인.
표1(프로필×경로 최종점수)·표2(날씨×날씨위험)의 값을 프론트 검증 테스트와 동일하게 못박는다.
"""
import pytest

from app.data.routes import demo_candidates
from app.data.weather import WEATHER_SCENARIOS
from app.scoring import recommend_routes, score_route

ROUTES = demo_candidates()
NORMAL = WEATHER_SCENARIOS["normal"]


def score_all(profile: str, scenario: str, **opts):
    weather = WEATHER_SCENARIOS[scenario]
    fastest = min(r.total_duration_min for r in ROUTES)
    return {
        r.id: score_route(r, weather, profile, fastest, i + 1, _opts(**opts))
        for i, r in enumerate(ROUTES)
    }


def _opts(**kw):
    from app.models import ScoringOptions

    return ScoringOptions(**kw)


# ── 표1: 프로필 × 경로 최종점수 (평상 날씨) — 프론트와 동일해야 함 ──
EXPECTED_FINAL = {
    "general": {"r1-overpass": 81.5, "r2-subway": 92.0, "r3-lowfloor": 87.0, "r4-regularbus": 88.1},
    "elderly": {"r1-overpass": 70.2, "r2-subway": 92.1, "r3-lowfloor": 87.6, "r4-regularbus": 85.7},
    "child": {"r1-overpass": 81.4, "r2-subway": 93.0, "r3-lowfloor": 88.8, "r4-regularbus": 86.9},
    "disabled": {"r1-overpass": 69.6, "r2-subway": 91.8, "r3-lowfloor": 90.0, "r4-regularbus": 78.6},
}


@pytest.mark.parametrize("profile", ["general", "elderly", "child", "disabled"])
def test_final_score_table_matches_frontend(profile):
    s = score_all(profile, "normal")
    for rid, expected in EXPECTED_FINAL[profile].items():
        assert s[rid].final_score == pytest.approx(expected, abs=1e-6), (
            f"{profile}/{rid}: {s[rid].final_score} != {expected}"
        )


# ── 표2: 날씨 시나리오별 날씨위험(일반 프로필) ──
EXPECTED_WEATHER_RISK = {
    "normal": {"r1-overpass": 0, "r2-subway": 0, "r3-lowfloor": 0, "r4-regularbus": 0},
    "heatwave": {"r1-overpass": 25, "r2-subway": 16, "r3-lowfloor": 19, "r4-regularbus": 16},
    "coldwave": {"r1-overpass": 5, "r2-subway": 2, "r3-lowfloor": 13, "r4-regularbus": 8},
    "rain": {"r1-overpass": 30, "r2-subway": 12, "r3-lowfloor": 28, "r4-regularbus": 12},
    "dust": {"r1-overpass": 20, "r2-subway": 14, "r3-lowfloor": 16, "r4-regularbus": 14},
}


@pytest.mark.parametrize("scenario", list(EXPECTED_WEATHER_RISK))
def test_weather_risk_table_matches_frontend(scenario):
    s = score_all("general", scenario)
    for rid, expected in EXPECTED_WEATHER_RISK[scenario].items():
        assert s[rid].display.weather_risk == pytest.approx(expected, abs=1e-6)


# ── 검증 항목(기획서 §8) ──
def test_stairs_penalized_for_disabled():
    s = score_all("disabled", "normal")
    assert s["r2-subway"].final_score > s["r1-overpass"].final_score
    assert s["r2-subway"].components.elevator > s["r1-overpass"].components.elevator


def test_stair_route_excluded_from_disabled_top3():
    top3 = recommend_routes(ROUTES, NORMAL, "disabled")
    assert "r1-overpass" not in [sr.route.id for sr in top3]


@pytest.mark.parametrize("profile", ["elderly", "disabled"])
def test_elevator_gain(profile):
    s = score_all(profile, "normal")
    assert s["r2-subway"].final_score > s["r4-regularbus"].final_score


def test_low_floor_gain_for_disabled():
    s = score_all("disabled", "normal")
    assert s["r3-lowfloor"].final_score > s["r4-regularbus"].final_score
    assert s["r3-lowfloor"].components.low_floor_bus > s["r4-regularbus"].components.low_floor_bus


def test_low_floor_priority_raises_rank():
    def idx(lst):
        return next(i for i, sr in enumerate(lst) if sr.route.id == "r3-lowfloor")

    from app.models import ScoringOptions

    off = recommend_routes(ROUTES, NORMAL, "general", ScoringOptions(), top_n=4)
    on = recommend_routes(ROUTES, NORMAL, "general", ScoringOptions(low_floor_priority=True), top_n=4)
    assert idx(on) < idx(off)


def test_carry_luggage_penalizes_walking_heavy_route():
    from app.models import ScoringOptions

    off = score_all("general", "normal")
    on = score_all("general", "normal", carry_luggage=True)
    # 육교 도보 경로는 짐 많음 조건에서 보행 부담 비중이 커져 상대적으로 더 낮아진다.
    assert on["r1-overpass"].final_score < off["r1-overpass"].final_score


def test_weather_changes_score():
    normal = score_all("general", "normal")
    heat = score_all("general", "heatwave")
    assert heat["r1-overpass"].components.weather_safety < normal["r1-overpass"].components.weather_safety
    assert heat["r1-overpass"].final_score < normal["r1-overpass"].final_score


def test_child_penalizes_crosswalk_route_more():
    general = score_all("general", "normal")
    child = score_all("child", "normal")
    assert child["r4-regularbus"].final_score < general["r4-regularbus"].final_score


def test_low_floor_status():
    s = score_all("general", "normal")
    assert s["r3-lowfloor"].low_floor_status == "confirmed"
    assert s["r4-regularbus"].low_floor_status == "regular"
    assert s["r2-subway"].low_floor_status == "none"


def test_round1_half_up():
    from app.scoring.utils import round1

    # JS Math.round 와 동일하게 0.5는 올림
    assert round1(0.05) == 0.1
    assert round1(0.04) == 0.0
    assert round1(91.95) == 92.0
