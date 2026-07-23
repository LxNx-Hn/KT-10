from app.models import Place, ScoringOptions
from app.providers.ai_pipeline import _pipeline_payload, _to_route_candidate


ORIGIN = Place(id="origin", name="부산역", lat=35.1151, lng=129.0414)
DESTINATION = Place(id="destination", name="서면역", lat=35.1578, lng=129.0594)


def _candidate_payload() -> dict:
    return {
        "route_id": "route-live-1",
        "summary": "도보 + 도시철도",
        "duration_min": 24,
        "distance_m": 4100,
        "sources": ["odsay", "osmnx"],
        "geometry_quality": "mixed",
        "path": [
            {"lat": 35.1151, "lng": 129.0414},
            {"lat": 35.1300, "lng": 129.0500},
            {"lat": 35.1578, "lng": 129.0594},
        ],
        "segments": [
            {
                "id": "walk-1",
                "mode": "walk",
                "description": "부산역 출구까지 이동",
                "duration_min": 5,
                "distance_m": 320,
                "outdoor": True,
                "path": [
                    {"lat": 35.1151, "lng": 129.0414},
                    {"lat": 35.1160, "lng": 129.0420},
                ],
                "geometry_quality": "exact",
            },
            {
                "id": "subway-1",
                "mode": "subway",
                "description": "도시철도 1호선",
                "duration_min": 19,
                "distance_m": 3780,
                "station_name": "부산역",
                "path": [
                    {"lat": 35.1160, "lng": 129.0420},
                    {"lat": 35.1578, "lng": 129.0594},
                ],
                "geometry_quality": "exact",
            },
        ],
        "features": {
            "transfer_count": 0,
            "walk_distance_m": 320,
            "avg_slope_percent": 1.4,
            "max_slope_percent": 4.2,
            "min_slope_percent": -2.1,
            "elevation_gain_m": 7.5,
            "elevation_status": "estimated_90m",
            "elevation_source": "Open-Meteo Copernicus DEM GLO-90",
            "elevation_resolution_m": 90,
        },
    }


def test_labeling_candidate_maps_geometry_and_terrain_without_invention():
    route = _to_route_candidate(_candidate_payload(), ORIGIN, DESTINATION, 1)

    assert route.id == "route-live-1"
    assert route.path is not None and len(route.path) == 3
    assert route.geometry_quality == "mixed"
    assert route.total_walk_m == 320
    assert route.transfer_count == 0
    assert route.terrain is not None
    assert route.terrain.status == "estimated_90m"
    assert route.terrain.avg_slope_percent == 1.4
    assert route.segments[0].path is not None


def test_labeling_candidate_rejects_missing_geometry():
    payload = _candidate_payload()
    payload["path"] = []

    try:
        _to_route_candidate(payload, ORIGIN, DESTINATION, 1)
    except RuntimeError as exc:
        assert "geometry" in str(exc)
    else:
        raise AssertionError("geometry 없는 live 경로를 허용하면 안 됩니다.")


def test_pipeline_payload_keeps_profile_and_trip_conditions_separate():
    payload = _pipeline_payload(
        ORIGIN,
        DESTINATION,
        "pregnant",
        "normal",
        ScoringOptions(
            carry_luggage=True,
            stroller=True,
            avoid_stairs=True,
            shade_priority=True,
            low_floor_priority=True,
            minimize_transfers=True,
        ),
    )
    assert payload["profile"] == "pregnant"
    assert payload["carry_luggage"] is True
    assert payload["stroller"] is True
    assert payload["avoid_stairs"] is True
    assert payload["shade_priority"] is True
    assert payload["low_floor_priority"] is True
    assert payload["minimize_transfers"] is True
