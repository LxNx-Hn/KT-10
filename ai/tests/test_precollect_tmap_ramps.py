import asyncio

from collectors.base import Coordinate, RouteCandidate
from data_tools import precollect_tmap_ramps as module


def _wheelchair_evidence() -> dict:
    return {
        "wheelchair_constraints_applied": True,
        "stairs_excluded_by_provider": True,
    }


def test_precollection_deduplicates_segments_and_reports_official_ramps(
    monkeypatch,
    tmp_path,
):
    origin = Coordinate(35.10, 129.00)
    middle = Coordinate(35.11, 129.01)
    destination = Coordinate(35.12, 129.02)
    transit = RouteCandidate(
        source="odsay",
        path=[origin, middle, destination],
        duration_min=20,
        distance_m=2000,
        segments=[{
            "mode": "walk",
            "distance_m": 500,
            "path": [origin, middle],
            "accessibility_evidence": _wheelchair_evidence(),
        }],
    )
    direct = RouteCandidate(
        source="ors",
        path=[origin, destination],
        duration_min=30,
        distance_m=2500,
        accessibility_evidence=_wheelchair_evidence(),
    )
    tmap_calls = []

    class FakeOdsay:
        def __init__(self, **_kwargs):
            pass

        async def collect(self, *_args, **_kwargs):
            return [transit]

    class FakeOrs:
        async def collect(self, *_args):
            return [direct]

    class FakeTmap:
        def __init__(self, **_kwargs):
            pass

        async def collect_cached(self, *_args):
            return []

        async def collect(self, start, end):
            tmap_calls.append((start, end))
            payload = {
                "features": [{
                    "geometry": {
                        "type": "LineString",
                        "coordinates": [
                            [start.lng, start.lat],
                            [end.lng, end.lat],
                        ],
                    },
                    "properties": {
                        "totalTime": 600,
                        "totalDistance": 500,
                    },
                }],
            }
            return [RouteCandidate(
                source="tmap",
                path=[start, end],
                duration_min=10,
                distance_m=500,
                accessibility_evidence={
                    "ramp_points": [{
                        "lat": start.lat,
                        "lng": start.lng,
                        "replaces_stairs": end == middle,
                    }],
                },
                raw_response=payload,
            )]

    monkeypatch.setattr(module, "OdsayRouteCollector", FakeOdsay)
    monkeypatch.setattr(module, "OrsWheelchairRouteCollector", FakeOrs)
    monkeypatch.setattr(module, "TmapRouteCollector", FakeTmap)
    exported = []
    monkeypatch.setattr(
        module,
        "write_precomputed_cache",
        lambda *args, **kwargs: exported.append((args, kwargs)),
    )
    rows = [{
        "origin_lat": str(origin.lat),
        "origin_lng": str(origin.lng),
        "origin_name": "출발",
        "dest_lat": str(destination.lat),
        "dest_lng": str(destination.lng),
        "dest_name": "도착",
    }]

    report = asyncio.run(module.precollect_rows(
        rows,
        artifact_dir=tmp_path,
    ))

    assert report["status"] == "complete"
    assert report["uniqueVerifiedWalkSegmentCount"] == 2
    assert report["validatedTmapSegmentCount"] == 2
    assert report["networkMissCount"] == 2
    assert report["knownRampSegmentCount"] == 2
    assert report["knownStairAlternativeRampSegmentCount"] == 1
    assert len(tmap_calls) == 2
    assert len(exported) == 2


def test_precollection_does_not_call_tmap_for_unverified_walk(monkeypatch):
    origin = Coordinate(35.10, 129.00)
    destination = Coordinate(35.12, 129.02)
    unverified = RouteCandidate(
        source="ors",
        path=[origin, destination],
        duration_min=30,
        distance_m=2500,
        accessibility_evidence={},
    )

    class FakeOdsay:
        def __init__(self, **_kwargs):
            pass

        async def collect(self, *_args, **_kwargs):
            return []

    class FakeOrs:
        async def collect(self, *_args):
            return [unverified]

    class ForbiddenTmap:
        def __init__(self, **_kwargs):
            raise AssertionError("검증되지 않은 구간은 TMAP을 호출하면 안 됩니다.")

    monkeypatch.setattr(module, "OdsayRouteCollector", FakeOdsay)
    monkeypatch.setattr(module, "OrsWheelchairRouteCollector", FakeOrs)
    monkeypatch.setattr(module, "TmapRouteCollector", ForbiddenTmap)
    rows = [{
        "origin_lat": str(origin.lat),
        "origin_lng": str(origin.lng),
        "origin_name": "출발",
        "dest_lat": str(destination.lat),
        "dest_lng": str(destination.lng),
        "dest_name": "도착",
    }]

    report = asyncio.run(module.precollect_rows(rows))

    assert report["status"] == "partial"
    assert report["uniqueVerifiedWalkSegmentCount"] == 0
    assert report["validatedTmapSegmentCount"] == 0
    assert report["failures"][0]["errorType"] == "NoVerifiedSegments"
