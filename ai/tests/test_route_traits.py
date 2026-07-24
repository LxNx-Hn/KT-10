"""경로 특성 라벨이 관측된 사실만 사용하는지 검증한다."""
from labeling.route_traits import generate_route_traits
from scoring.snapshots import build_live_feature_snapshot


def _snapshot(route_id: str, **features):
    return build_live_feature_snapshot(
        group_id="g1",
        route_id=route_id,
        features=features,
        sources=["odsay"],
        geometry_quality="mixed",
        holdout_group_id="od-g1",
        captured_at="2026-07-24T12:00:00+09:00",
    )


def _ids(trait):
    return {label["label_id"] for label in trait["labels"]}


def test_traits_include_comparative_and_confirmed_factual_labels():
    snapshots = [
        _snapshot(
            "r1",
            total_duration_min=10,
            walk_distance_m=800,
            transfer_count=1,
            max_slope_percent=5,
            min_slope_percent=-4,
            elevation_source="open-meteo-glo90",
            shade_ratio=0.2,
            stair_count=0,
            is_low_floor_bus=None,
        ),
        _snapshot(
            "r2",
            total_duration_min=12,
            walk_distance_m=600,
            transfer_count=0,
            max_slope_percent=3,
            min_slope_percent=-3,
            elevation_source="open-meteo-glo90",
            shade_ratio=0.7,
            stair_count=None,
            is_low_floor_bus=True,
        ),
    ]
    traits = generate_route_traits(snapshots)

    assert {"fastest", "stair_free_confirmed"} <= _ids(traits["r1"])
    assert {
        "shortest",
        "fewest_transfers",
        "lowest_slope",
        "most_shade",
        "low_floor_confirmed",
    } <= _ids(traits["r2"])
    assert traits["r2"]["feature_snapshot_hash"] == snapshots[1]["feature_snapshot_hash"]
    assert traits["r2"]["provenance"]["labeler_kind"] == "deterministic_factual"
    shade_label = next(
        label for label in traits["r2"]["labels"]
        if label["label_id"] == "most_shade"
    )
    assert shade_label["evidence"] == [{
        "feature": "shade_ratio",
        "value": 0.7,
        "unit": "ratio",
        "source": "building_shade",
    }]


def test_unknown_comparative_fact_suppresses_positive_label_for_whole_set():
    snapshots = [
        _snapshot(
            "known",
            total_duration_min=10,
            walk_distance_m=500,
            transfer_count=0,
            max_slope_percent=2,
            min_slope_percent=-2,
            shade_ratio=0.8,
            stair_count=None,
            is_low_floor_bus=None,
        ),
        _snapshot(
            "unknown",
            total_duration_min=12,
            walk_distance_m=None,
            transfer_count=None,
            max_slope_percent=None,
            min_slope_percent=None,
            shade_ratio=None,
            stair_count=None,
            is_low_floor_bus=None,
        ),
    ]
    traits = generate_route_traits(snapshots)

    assert "fastest" in _ids(traits["known"])
    for label_id in ("shortest", "fewest_transfers", "lowest_slope", "most_shade"):
        assert label_id not in _ids(traits["known"])
        assert label_id not in _ids(traits["unknown"])
    assert traits["unknown"]["labels"] == []


def test_lowest_slope_uses_steepest_uphill_or_downhill_grade():
    snapshots = [
        _snapshot(
            "steep-downhill",
            total_duration_min=10,
            walk_distance_m=500,
            transfer_count=0,
            max_slope_percent=1,
            min_slope_percent=-20,
            shade_ratio=0.5,
            stair_count=None,
            is_low_floor_bus=None,
        ),
        _snapshot(
            "gentle",
            total_duration_min=11,
            walk_distance_m=550,
            transfer_count=0,
            max_slope_percent=4,
            min_slope_percent=-3,
            shade_ratio=0.5,
            stair_count=None,
            is_low_floor_bus=None,
        ),
    ]

    traits = generate_route_traits(snapshots)

    assert "lowest_slope" not in _ids(traits["steep-downhill"])
    assert "lowest_slope" in _ids(traits["gentle"])


def test_zero_shade_does_not_claim_a_shaded_route():
    snapshots = [
        _snapshot(
            "r1",
            total_duration_min=10,
            walk_distance_m=500,
            transfer_count=0,
            max_slope_percent=2,
            min_slope_percent=-2,
            shade_ratio=0.0,
            stair_count=None,
            is_low_floor_bus=None,
        ),
        _snapshot(
            "r2",
            total_duration_min=12,
            walk_distance_m=550,
            transfer_count=1,
            max_slope_percent=3,
            min_slope_percent=-3,
            shade_ratio=0.0,
            stair_count=None,
            is_low_floor_bus=None,
        ),
    ]

    traits = generate_route_traits(snapshots)

    assert "most_shade" not in _ids(traits["r1"])
    assert "most_shade" not in _ids(traits["r2"])
