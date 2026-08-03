from datetime import datetime
from zoneinfo import ZoneInfo

import app.shade as shade_module
from app.data.routes import demo_candidates
from app.shade import (
    DEMO_BUILDING_DATA,
    _display_polygons,
    _swept_shadow,
    add_demo_shade,
    assign_characteristics,
    calculate_shade,
    prepare_shade_context,
    solar_position,
)
from shapely.geometry import Point, Polygon

KST = ZoneInfo("Asia/Seoul")


def test_solar_position_is_above_horizon_at_busan_summer_noon():
    azimuth, elevation = solar_position(
        datetime(2026, 7, 23, 12, 0, tzinfo=KST),
        35.16,
        129.06,
    )
    assert 0 <= azimuth < 360
    assert elevation > 60


def test_demo_shade_has_explicit_quality_and_valid_geometry():
    routes = add_demo_shade(
        demo_candidates(),
        datetime(2026, 7, 23, 14, 0, tzinfo=KST),
    )
    for route in routes:
        assert route.shade is not None
        assert route.shade.status == "estimated_demo"
        assert route.shade.data_quality == "demo"
        assert route.shade.shade_ratio is not None
        assert 0 <= route.shade.shade_ratio <= 1
        assert route.shade.shadow_polygons
        assert route.shade.path_segments


def test_night_is_not_misreported_as_zero_shade():
    route = add_demo_shade(
        demo_candidates()[:1],
        datetime(2026, 7, 23, 2, 0, tzinfo=KST),
    )[0]
    assert route.shade is not None
    assert route.shade.status == "not_daylight"
    assert route.shade.shade_ratio is None


def test_demo_buildings_outside_verified_area_are_unavailable_not_zero():
    route = demo_candidates()[0].model_copy(deep=True)
    assert route.path is not None
    for point in route.path:
        point.lat += 0.1

    shade = add_demo_shade(
        [route],
        datetime(2026, 7, 23, 14, 0, tzinfo=KST),
    )[0].shade

    assert shade is not None
    assert shade.status == "unavailable"
    assert shade.shade_ratio is None
    assert "건물 데이터 범위를 벗어나" in shade.calculation_note


def test_night_outside_demo_bounds_stays_not_daylight():
    route = demo_candidates()[0].model_copy(deep=True)
    assert route.path is not None
    for point in route.path:
        point.lat += 0.1

    shade = add_demo_shade(
        [route],
        datetime(2026, 7, 24, 1, 0, tzinfo=KST),
    )[0].shade

    assert shade is not None
    assert shade.status == "not_daylight"
    assert shade.shade_ratio is None


def test_zero_length_walking_geometry_is_unavailable_not_estimated():
    route = demo_candidates()[0].model_copy(deep=True)
    assert route.path is not None
    first = route.path[0]
    route.path = [first.model_copy(), first.model_copy()]

    shade = add_demo_shade(
        [route],
        datetime(2026, 7, 23, 14, 0, tzinfo=KST),
    )[0].shade

    assert shade is not None
    assert shade.status == "unavailable"
    assert shade.shade_ratio is None
    assert "보행 경로" in shade.calculation_note


def test_concave_building_shadow_is_not_inflated_to_convex_hull():
    footprint = Polygon([
        (0, 0), (4, 0), (4, 1), (1, 1), (1, 4), (0, 4), (0, 0),
    ])
    shadow = _swept_shadow(footprint, (10, 0))
    assert shadow.covers(Point(8, 3))
    assert not shadow.covers(Point(13, 3))


def test_display_shadow_simplification_preserves_topology_and_area():
    detailed = Polygon([
        (0, 0),
        (1, 0.1),
        (2, 0),
        (3, 0.1),
        (4, 0),
        (4, 4),
        (0, 4),
        (0, 0),
    ])

    display = _display_polygons(detailed)

    assert len(display) == 1
    simplified = Polygon(display[0])
    assert len(display[0]) < len(detailed.exterior.coords)
    assert simplified.is_valid
    assert abs(simplified.area - detailed.area) / detailed.area < 0.02


def test_prepared_context_builds_shared_shadows_once(monkeypatch):
    routes = demo_candidates()[:2]
    evaluated_at = datetime(2026, 7, 23, 14, 0, tzinfo=KST)
    swept_calls = 0
    original = shade_module._swept_shadow

    def counted(*args, **kwargs):
        nonlocal swept_calls
        swept_calls += 1
        return original(*args, **kwargs)

    monkeypatch.setattr(shade_module, "_swept_shadow", counted)
    context = prepare_shade_context(
        routes,
        evaluated_at,
        DEMO_BUILDING_DATA,
    )
    prepared_calls = swept_calls

    summaries = [
        calculate_shade(
            route,
            evaluated_at,
            DEMO_BUILDING_DATA,
            prepared_context=context,
        )
        for route in routes
    ]

    assert context is not None
    assert prepared_calls > 0
    assert swept_calls == prepared_calls
    assert all(summary.status == "estimated_demo" for summary in summaries)


def test_prepared_context_matches_independent_route_ratios():
    routes = demo_candidates()
    evaluated_at = datetime(2026, 7, 23, 14, 0, tzinfo=KST)
    context = prepare_shade_context(
        routes,
        evaluated_at,
        DEMO_BUILDING_DATA,
    )

    assert context is not None
    for route in routes:
        independent = calculate_shade(
            route,
            evaluated_at,
            DEMO_BUILDING_DATA,
        )
        shared = calculate_shade(
            route,
            evaluated_at,
            DEMO_BUILDING_DATA,
            prepared_context=context,
        )
        assert shared.shade_ratio == independent.shade_ratio


def test_characteristics_cover_factual_route_traits():
    routes = assign_characteristics(add_demo_shade(
        demo_candidates(),
        datetime(2026, 7, 23, 14, 0, tzinfo=KST),
    ))
    characteristics = {
        characteristic for route in routes for characteristic in route.characteristics
    }
    assert {
        "fastest",
        "shortest_walk",
        "lowest_slope",
        "most_shade",
        "fewest_transfers",
    }.issubset(characteristics)


def test_lowest_slope_uses_peak_not_diluted_whole_walk_average():
    routes = [route.model_copy(deep=True) for route in demo_candidates()[:2]]
    routes[0].terrain.avg_slope_percent = 1.5
    routes[0].terrain.max_slope_percent = 12
    routes[0].terrain.min_slope_percent = -3
    routes[1].terrain.avg_slope_percent = 3
    routes[1].terrain.max_slope_percent = 5
    routes[1].terrain.min_slope_percent = -4

    assign_characteristics(routes)

    assert "lowest_slope" not in routes[0].characteristics
    assert "lowest_slope" in routes[1].characteristics
