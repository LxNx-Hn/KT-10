"""공급자별 정점 밀도와 이동수단을 보존하는 경로 병합 테스트."""
from collectors.base import Coordinate, RouteCandidate
from merger.route_merger import merge_route_candidates, sample_path_by_distance


def _candidate(
    source: str,
    path: list[Coordinate],
    *,
    quality: str = "exact",
    modes: tuple[str, ...] = (),
    evidence: dict | None = None,
) -> RouteCandidate:
    return RouteCandidate(
        source=source,
        path=path,
        duration_min=10.0,
        distance_m=1000.0,
        segments=[{"mode": mode} for mode in modes],
        geometry_quality=quality,
        accessibility_evidence=evidence or {},
    )


def _bus_candidate(bus_number: str | None) -> RouteCandidate:
    lane = {"busNo": bus_number} if bus_number is not None else {}
    return RouteCandidate(
        source="odsay",
        path=[
            Coordinate(lat=35.0, lng=129.0),
            Coordinate(lat=35.01, lng=129.01),
        ],
        duration_min=10.0,
        distance_m=1000.0,
        segments=[{
            "mode": "bus",
            "raw": {
                "lane": [lane],
                "startID": 100,
                "endID": 200,
            },
        }],
        geometry_quality="exact",
    )


def test_distance_sampling_includes_both_endpoints():
    path = [
        Coordinate(lat=35.0, lng=129.0),
        Coordinate(lat=35.001, lng=129.0),
        Coordinate(lat=35.010, lng=129.0),
    ]

    sampled = sample_path_by_distance(path, n=5)

    assert sampled[0] == path[0]
    assert sampled[-1] == path[-1]
    assert len(sampled) == 5


def test_dense_and_sparse_parallel_routes_are_not_falsely_merged():
    dense = [
        Coordinate(lat=35.0 + index * 0.0001, lng=129.0)
        for index in range(101)
    ]
    # 약 90m 동쪽의 평행 경로. 이전 구현은 2개 비교 거리의 합을
    # dense 표본 수 10으로 나눠 30m 이하라고 오판했다.
    sparse = [
        Coordinate(lat=35.0, lng=129.001),
        Coordinate(lat=35.010, lng=129.001),
    ]

    merged = merge_route_candidates([
        _candidate("source-a", dense, modes=("walk",)),
        _candidate("source-b", sparse, modes=("walk",)),
    ])

    assert len(merged) == 2


def test_localized_large_detour_is_not_hidden_by_small_mean_distance():
    direct = [
        Coordinate(lat=35.0 + index * 0.0002, lng=129.0)
        for index in range(51)
    ]
    detour = list(direct)
    # 일부 구간만 약 180m 동쪽으로 우회한다. 평균 이격이 작더라도 그늘·
    # 시설이 다른 대안일 수 있으므로 중복 경로로 제거하면 안 된다.
    for index in range(22, 29):
        detour[index] = Coordinate(
            lat=detour[index].lat,
            lng=detour[index].lng + 0.002,
        )

    merged = merge_route_candidates([
        _candidate("source-a", direct, modes=("walk",)),
        _candidate("source-b", detour, modes=("walk",)),
    ])

    assert len(merged) == 2


def test_same_geometry_with_different_transport_modes_is_not_merged():
    path = [
        Coordinate(lat=35.0, lng=129.0),
        Coordinate(lat=35.01, lng=129.01),
    ]

    merged = merge_route_candidates([
        _candidate("odsay", path, modes=("walk", "bus", "walk")),
        _candidate("tmap", path),
    ])

    assert len(merged) == 2


def test_better_geometry_updates_primary_source_consistently():
    path = [
        Coordinate(lat=35.0, lng=129.0),
        Coordinate(lat=35.01, lng=129.01),
    ]

    merged = merge_route_candidates([
        _candidate("tmap", path, quality="estimated"),
        _candidate("osmnx", path, quality="exact"),
    ])

    assert len(merged) == 1
    assert merged[0].sources == ["tmap", "osmnx"]
    assert merged[0].source == "osmnx"
    assert merged[0].geometry_quality == "exact"


def test_different_bus_lines_on_same_geometry_are_not_merged():
    merged = merge_route_candidates([
        _bus_candidate("100"),
        _bus_candidate("200"),
    ])

    assert len(merged) == 2


def test_unknown_transit_identity_is_not_treated_as_equal():
    merged = merge_route_candidates([
        _bus_candidate(None),
        _bus_candidate(None),
    ])

    assert len(merged) == 2


def test_similar_tmap_and_ors_walk_routes_combine_distinct_evidence():
    path = [
        Coordinate(lat=35.0, lng=129.0),
        Coordinate(lat=35.01, lng=129.01),
    ]

    merged = merge_route_candidates([
        _candidate(
            "tmap",
            path,
            evidence={
                "provider": "TMAP pedestrian",
                "stairs_excluded_by_provider": True,
                "ramp_points": [{
                    "lat": 35.005,
                    "lng": 129.005,
                    "turn_type": 129,
                    "replaces_stairs": True,
                }],
            },
        ),
        _candidate(
            "ors",
            path,
            evidence={
                "providers": ["openrouteservice wheelchair"],
                "wheelchair_constraints_applied": True,
                "wheelchair_restrictions": {"minimum_width": 0.9},
                "wheelchair_data_limitations": ["OSM 태그가 누락될 수 있음"],
                "wheelchair_constraint_categories": [
                    "steps", "surface", "width", "wheelchair_access"
                ],
                "stairs_excluded_by_provider": True,
            },
        ),
    ])

    assert len(merged) == 1
    assert merged[0].sources == ["tmap", "ors"]
    evidence = merged[0].accessibility_evidence
    assert evidence["providers"] == [
        "TMAP pedestrian",
        "openrouteservice wheelchair",
    ]
    assert evidence["ramp_points"][0]["turn_type"] == 129
    assert evidence["wheelchair_constraints_applied"] is True
    assert evidence["wheelchair_restrictions"] == {"minimum_width": 0.9}


def test_dissimilar_tmap_and_ors_routes_do_not_share_accessibility_evidence():
    tmap = [
        Coordinate(lat=35.0, lng=129.0),
        Coordinate(lat=35.01, lng=129.0),
    ]
    ors = [
        Coordinate(lat=35.0, lng=129.002),
        Coordinate(lat=35.01, lng=129.002),
    ]

    merged = merge_route_candidates([
        _candidate("tmap", tmap, evidence={"ramp_points": [{"lat": 35.0}]}),
        _candidate(
            "ors",
            ors,
            evidence={"wheelchair_constraints_applied": True},
        ),
    ])

    assert len(merged) == 2
    assert "wheelchair_constraints_applied" not in merged[0].accessibility_evidence
    assert "ramp_points" not in merged[1].accessibility_evidence
