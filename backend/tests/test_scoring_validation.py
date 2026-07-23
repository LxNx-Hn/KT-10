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
    "general": {"r1-overpass": 85.3, "r2-subway": 89.8, "r3-lowfloor": 85.1, "r4-regularbus": 86.4},
    "elderly": {"r1-overpass": 72.4, "r2-subway": 90.9, "r3-lowfloor": 86.5, "r4-regularbus": 83.4},
    "child": {"r1-overpass": 83.0, "r2-subway": 91.7, "r3-lowfloor": 88.3, "r4-regularbus": 85.7},
    "youth": {"r1-overpass": 87.0, "r2-subway": 90.4, "r3-lowfloor": 85.9, "r4-regularbus": 87.4},
    "disabled": {"r1-overpass": 66.7, "r2-subway": 90.9, "r3-lowfloor": 88.4, "r4-regularbus": 73.8},
    "pregnant": {"r1-overpass": 72.8, "r2-subway": 90.7, "r3-lowfloor": 85.7, "r4-regularbus": 85.5},
}


@pytest.mark.parametrize("profile", list(EXPECTED_FINAL))
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
    # 일부 보행/환승 구간의 계단 정보가 미확인이므로 비 미끄럼 위험도
    # 임의의 0/안전값으로 대체하지 않는다.
    "rain": {"r1-overpass": None, "r2-subway": None, "r3-lowfloor": None, "r4-regularbus": None},
    "dust": {"r1-overpass": 20, "r2-subway": 14, "r3-lowfloor": 16, "r4-regularbus": 14},
}


@pytest.mark.parametrize("scenario", list(EXPECTED_WEATHER_RISK))
def test_weather_risk_table_matches_frontend(scenario):
    s = score_all("general", scenario)
    for rid, expected in EXPECTED_WEATHER_RISK[scenario].items():
        if expected is None:
            assert s[rid].display.weather_risk is None
        else:
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
    off = score_all("general", "normal")
    on = score_all("general", "normal", carry_luggage=True)
    # 육교 도보 경로는 짐 많음 조건에서 보행 부담 비중이 커져 상대적으로 더 낮아진다.
    assert on["r1-overpass"].final_score < off["r1-overpass"].final_score


def test_stroller_prefers_elevator_route_over_stair_route():
    off = score_all("general", "normal")
    on = score_all("general", "normal", stroller=True)
    off_gap = off["r2-subway"].final_score - off["r1-overpass"].final_score
    on_gap = on["r2-subway"].final_score - on["r1-overpass"].final_score
    assert on_gap > off_gap


def test_shade_priority_uses_only_known_building_shade():
    from datetime import datetime
    from zoneinfo import ZoneInfo

    from app.shade import add_demo_shade

    routes = add_demo_shade(
        demo_candidates(),
        datetime(2026, 7, 23, 14, 0, tzinfo=ZoneInfo("Asia/Seoul")),
    )
    fastest = min(route.total_duration_min for route in routes)
    off = {
        route.id: score_route(
            route, NORMAL, "general", fastest, index + 1, _opts()
        )
        for index, route in enumerate(routes)
    }
    on = {
        route.id: score_route(
            route,
            NORMAL,
            "general",
            fastest,
            index + 1,
            _opts(shade_priority=True),
        )
        for index, route in enumerate(routes)
    }
    most_shaded = max(
        routes,
        key=lambda route: (
            route.shade.shade_ratio
            if route.shade and route.shade.shade_ratio is not None
            else -1
        ),
    )
    least_shaded = min(
        routes,
        key=lambda route: (
            route.shade.shade_ratio
            if route.shade and route.shade.shade_ratio is not None
            else 2
        ),
    )
    assert (
        on[most_shaded.id].final_score - off[most_shaded.id].final_score
        > on[least_shaded.id].final_score - off[least_shaded.id].final_score
    )


def test_unknown_shade_is_omitted_not_zero_filled():
    route = demo_candidates()[0]
    fastest = route.total_duration_min
    score = score_route(
        route, NORMAL, "general", fastest, 1, _opts(shade_priority=True)
    )
    assert score.components.shade_comfort is None


def test_weather_changes_score():
    normal = score_all("general", "normal")
    heat = score_all("general", "heatwave")
    assert heat["r1-overpass"].components.weather_safety < normal["r1-overpass"].components.weather_safety
    assert heat["r1-overpass"].final_score < normal["r1-overpass"].final_score


def test_rain_slope_risk_is_scored_when_stair_evidence_is_complete():
    import copy

    route = copy.deepcopy(ROUTES[2])
    for segment in route.segments:
        if (
            segment.mode in ("walk", "transfer")
            and segment.has_stairs is None
            and segment.stairs_count is None
        ):
            segment.has_stairs = False
    normal = score_route(
        route,
        WEATHER_SCENARIOS["normal"],
        "general",
        route.total_duration_min,
        1,
    )
    rain = score_route(
        route,
        WEATHER_SCENARIOS["rain"],
        "general",
        route.total_duration_min,
        1,
    )
    assert normal.display.weather_risk is not None
    assert rain.display.weather_risk is not None
    assert rain.display.weather_risk > normal.display.weather_risk


def test_verified_demo_shade_reduces_heat_exposure_only_when_known():
    from datetime import datetime
    from zoneinfo import ZoneInfo

    from app.shade import add_demo_shade

    route_without_shade = demo_candidates()[0]
    route_with_shade = add_demo_shade(
        demo_candidates()[:1],
        datetime(2026, 7, 23, 14, 0, tzinfo=ZoneInfo("Asia/Seoul")),
    )[0]
    fastest = route_with_shade.total_duration_min
    without = score_route(
        route_without_shade, WEATHER_SCENARIOS["heatwave"], "general", fastest, 1
    )
    with_shade = score_route(
        route_with_shade, WEATHER_SCENARIOS["heatwave"], "general", fastest, 1
    )
    assert route_with_shade.shade is not None
    if route_with_shade.shade.shade_ratio:
        assert with_shade.components.weather_safety > without.components.weather_safety
    else:
        assert with_shade.components.weather_safety == without.components.weather_safety


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
