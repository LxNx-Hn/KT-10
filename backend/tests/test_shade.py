from datetime import datetime
from zoneinfo import ZoneInfo

from app.data.routes import demo_candidates
from app.shade import _swept_shadow, add_demo_shade, assign_characteristics, solar_position
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
    assert "검증 범위" in shade.calculation_note


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


def test_concave_building_shadow_is_not_inflated_to_convex_hull():
    footprint = Polygon([
        (0, 0), (4, 0), (4, 1), (1, 1), (1, 4), (0, 4), (0, 0),
    ])
    shadow = _swept_shadow(footprint, (10, 0))
    assert shadow.covers(Point(8, 3))
    assert not shadow.covers(Point(13, 3))


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
