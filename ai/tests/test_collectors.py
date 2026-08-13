"""
경로 수집기 테스트. 키 누락·공급자 실패가 가짜 경로로 위장되지 않는지 검증한다.

ai/.env 에 실제 키가 설정돼 있어도 결과가 흔들리지 않도록,
settings의 키 값은 monkeypatch로 강제 고정한다 (환경 비의존).
"""
import asyncio
import json
import time
from types import SimpleNamespace

import httpx
import pytest

from collectors.base import CollectorError, CollectorNotConfigured, Coordinate
from collectors.odsay_collector import (
    AccessibleSubwayExit,
    OdsayRouteCollector,
    WalkGeometryResult,
)
from collectors.ors_collector import (
    AVOID_FEATURES,
    EXTRA_INFO,
    WHEELCHAIR_RESTRICTIONS,
    OrsWheelchairRouteCollector,
)
from collectors.osmnx_collector import OsmnxRouteCollector
from collectors.tmap_collector import TmapRouteCollector
from config import settings

ORIGIN = Coordinate(lat=35.1626, lng=129.0530)
DEST = Coordinate(lat=35.1578, lng=129.0594)


def test_wheelchair_odsay_uses_nearest_official_accessible_subway_exits():
    origin = Coordinate(lat=35.2479, lng=129.0912)
    destination = Coordinate(lat=35.0977, lng=129.0349)
    exits = {
        (1, "구서"): (
            AccessibleSubwayExit("3", Coordinate(35.24795, 129.09120), 101),
            AccessibleSubwayExit("4", Coordinate(35.24795, 129.09142), 102),
        ),
        (1, "남포"): (
            AccessibleSubwayExit("4", Coordinate(35.09768, 129.03487), 201),
            AccessibleSubwayExit("5", Coordinate(35.09815, 129.03521), 202),
        ),
    }
    original = [
        {"trafficType": 3},
        {
            "trafficType": 1,
            "startName": "구서",
            "endName": "남포",
            "startExitNo": "2",
            "endExitNo": "3",
            "lane": [{"name": "부산 1호선", "subwayCode": 71}],
        },
        {"trafficType": 3},
    ]

    adjusted = OdsayRouteCollector(
        uses_wheelchair=True,
        accessible_subway_exits=exits,
    )._apply_accessible_subway_exits(original, origin, destination)

    assert original[1]["startExitNo"] == "2"
    assert original[1]["endExitNo"] == "3"
    assert adjusted[1]["startExitNo"] == "3"
    assert adjusted[1]["startExitOsmNodeId"] == 101
    assert adjusted[1]["endExitNo"] == "4"
    assert adjusted[1]["endExitOsmNodeId"] == 201
    assert adjusted[1]["startExitCoordinateSource"] == (
        "OpenStreetMap ODbL 1.0"
    )


def test_general_odsay_does_not_replace_provider_subway_exits():
    original = [{
        "trafficType": 1,
        "startName": "구서",
        "endName": "남포",
        "startExitNo": "2",
        "endExitNo": "3",
        "lane": [{"subwayCode": 71}],
    }]
    exits = {
        (1, "구서"): (
            AccessibleSubwayExit("3", Coordinate(35.24795, 129.09120), 101),
        ),
    }

    adjusted = OdsayRouteCollector(
        uses_wheelchair=False,
        accessible_subway_exits=exits,
    )._apply_accessible_subway_exits(original, ORIGIN, DEST)

    assert adjusted == original
    assert adjusted is not original


def test_odsay_candidate_recalculates_walk_metrics_after_exact_reroute(
    monkeypatch,
):
    path = {
        "info": {"totalTime": 37, "totalDistance": 18_430},
        "subPath": [
            {"trafficType": 3, "sectionTime": 1, "distance": 19},
            {
                "trafficType": 1,
                "sectionTime": 35,
                "distance": 18_400,
                "startX": 129.0912,
                "startY": 35.2479,
                "endX": 129.0349,
                "endY": 35.0977,
                "lane": [{"subwayCode": 71}],
            },
            {"trafficType": 3, "sectionTime": 1, "distance": 11},
        ],
    }
    results = iter((
        WalkGeometryResult(
            [ORIGIN, Coordinate(35.2479, 129.0912)],
            "exact",
            {},
            duration_min=2.0,
            distance_m=100.0,
        ),
        WalkGeometryResult(
            [Coordinate(35.0977, 129.0349), DEST],
            "exact",
            {},
            duration_min=3.0,
            distance_m=200.0,
        ),
    ))

    async def exact_walk(_self, _start, _end):
        return next(results)

    monkeypatch.setattr(settings, "ODSAY_LOAD_LANE_ENABLED", False)
    monkeypatch.setattr(OdsayRouteCollector, "_walk_geometry", exact_walk)
    candidate = asyncio.run(
        OdsayRouteCollector(
            uses_wheelchair=True,
            accessible_subway_exits={},
        )._build_candidate(path, ORIGIN, DEST)
    )

    assert candidate.duration_min == 40.0
    assert candidate.distance_m == 18_700.0
    assert candidate.segments[0]["duration_min"] == 2.0
    assert candidate.segments[0]["distance_m"] == 100.0
    assert candidate.segments[2]["duration_min"] == 3.0
    assert candidate.segments[2]["distance_m"] == 200.0


def test_odsay_fails_explicitly_without_api_key(monkeypatch):
    monkeypatch.setattr(settings, "ODSAY_API_KEY", "")
    with pytest.raises(CollectorNotConfigured):
        asyncio.run(OdsayRouteCollector().collect(ORIGIN, DEST))


def test_odsay_persistent_cache_round_trip(monkeypatch, tmp_path):
    import collectors.odsay_collector as module

    monkeypatch.setattr(settings, "ODSAY_CACHE_DIR", str(tmp_path))
    monkeypatch.setattr(settings, "ODSAY_CACHE_TTL_SECONDS", 1800)
    identity = {
        "origin": [ORIGIN.lat, ORIGIN.lng],
        "destination": [DEST.lat, DEST.lng],
    }
    payload = {"result": {"path": [{"info": {"totalTime": 10}}]}}

    module._write_cache("search", identity, payload)

    assert module._read_cache("search", identity) == payload
    cache_text = next(tmp_path.glob("*.json")).read_text(encoding="utf-8")
    assert "ODSAY_API_KEY" not in cache_text


def test_odsay_has_hard_service_timeout(monkeypatch):
    async def slow_collect(_self, _origin, _destination, **_kwargs):
        await asyncio.sleep(0.05)
        return []

    monkeypatch.setattr(settings, "ODSAY_API_KEY", "test-key")
    monkeypatch.setattr(settings, "ODSAY_TIMEOUT_SECONDS", 0.01)
    monkeypatch.setattr(
        OdsayRouteCollector,
        "_collect_live_or_cached",
        slow_collect,
    )

    with pytest.raises(CollectorError, match="시간 제한"):
        asyncio.run(OdsayRouteCollector().collect(ORIGIN, DEST))


def test_tmap_fails_explicitly_without_api_key(monkeypatch):
    monkeypatch.setattr(settings, "TMAP_API_KEY", "")
    with pytest.raises(CollectorNotConfigured):
        asyncio.run(TmapRouteCollector().collect(ORIGIN, DEST))


def _ors_payload():
    response_keys = {
        "steepness": "steepness",
        "suitability": "suitability",
        "surface": "surface",
        "waytype": "waytypes",
        "osmid": "osmId",
    }
    return {
        "type": "FeatureCollection",
        "features": [{
            "type": "Feature",
            "geometry": {
                "type": "LineString",
                "coordinates": [
                    [ORIGIN.lng, ORIGIN.lat, 12.0],
                    [DEST.lng, DEST.lat, 11.0],
                ],
            },
            "properties": {
                "summary": {"distance": 1000, "duration": 600},
                "segments": [{"distance": 1000, "duration": 600}],
                "extras": {
                    response_key: {
                        "values": [[0, 1, index + 1]],
                        "summary": [],
                    }
                    for index, response_key in enumerate(
                        response_keys.values()
                    )
                },
            },
        }],
    }


def test_ors_fails_explicitly_without_api_key(monkeypatch):
    monkeypatch.setattr(settings, "ORS_API_KEY", "")

    with pytest.raises(CollectorNotConfigured):
        asyncio.run(OrsWheelchairRouteCollector().collect(ORIGIN, DEST))


def test_ors_wheelchair_request_applies_all_official_restrictions(monkeypatch):
    import collectors.ors_collector as module

    captured = {}

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return _ors_payload()

    class Client:
        def __init__(self, *args, **kwargs):
            captured["client"] = kwargs

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def post(self, url, **kwargs):
            captured["url"] = url
            captured.update(kwargs)
            return Response()

    monkeypatch.setattr(settings, "ORS_API_KEY", "test-secret")
    monkeypatch.setattr(settings, "ORS_CACHE_DIR", "")
    monkeypatch.setattr(module.httpx, "AsyncClient", Client)

    candidate = asyncio.run(
        OrsWheelchairRouteCollector().collect(ORIGIN, DEST)
    )[0]

    assert captured["url"].endswith("/v2/directions/wheelchair/geojson")
    assert captured["headers"]["Authorization"] == "test-secret"
    assert captured["json"]["options"] == {
        "avoid_features": list(AVOID_FEATURES),
        "profile_params": {
            "restrictions": WHEELCHAIR_RESTRICTIONS,
        },
    }
    assert captured["json"]["extra_info"] == list(EXTRA_INFO)
    assert candidate.duration_min == 10
    assert candidate.distance_m == 1000
    assert candidate.accessibility_evidence[
        "wheelchair_constraints_applied"
    ] is True
    assert candidate.accessibility_evidence[
        "wheelchair_restrictions"
    ] == WHEELCHAIR_RESTRICTIONS
    assert candidate.accessibility_evidence[
        "stairs_excluded_by_provider"
    ] is True
    assert "stair_feature_count" not in candidate.accessibility_evidence
    assert candidate.accessibility_evidence["wheelchair_data_limitations"]
    assert "wheelchair_access" in candidate.accessibility_evidence[
        "wheelchair_constraint_categories"
    ]
    assert "ramp_points" not in candidate.accessibility_evidence
    assert candidate.accessibility_evidence[
        "verified_extra_response_keys"
    ] == {
        "steepness": "steepness",
        "suitability": "suitability",
        "surface": "surface",
        "waytype": "waytypes",
        "osmid": "osmId",
    }
    assert candidate.accessibility_evidence[
        "extra_info_full_route_coverage"
    ] is True


def test_ors_rejects_missing_requested_extra_info():
    payload = _ors_payload()
    del payload["features"][0]["properties"]["extras"]["surface"]

    with pytest.raises(CollectorError, match="extra_info"):
        OrsWheelchairRouteCollector()._candidate_from_data(payload)


def test_ors_rejects_empty_or_partial_extra_info_coverage():
    empty = _ors_payload()
    empty["features"][0]["properties"]["extras"]["surface"]["values"] = []
    with pytest.raises(CollectorError, match="구간이 비어"):
        OrsWheelchairRouteCollector()._candidate_from_data(empty)

    partial = _ors_payload()
    partial["features"][0]["geometry"]["coordinates"].insert(
        1,
        [129.0560, 35.1600, 11.5],
    )
    with pytest.raises(CollectorError, match="경로 전체"):
        OrsWheelchairRouteCollector()._candidate_from_data(partial)


def test_ors_rejects_explicitly_unsuitable_wheelchair_segment():
    payload = _ors_payload()
    payload["features"][0]["properties"]["extras"]["suitability"][
        "values"
    ] = [[0, 1, 1]]

    with pytest.raises(CollectorError, match="부적합한 구간") as captured:
        OrsWheelchairRouteCollector()._candidate_from_data(payload)

    assert captured.value.code == "wheelchair_unsuitable"
    assert captured.value.retryable is False


@pytest.mark.parametrize(
    ("status", "code"),
    [(401, "auth_failed"), (403, "auth_failed"), (429, "quota_exceeded")],
)
def test_ors_classifies_auth_and_quota_failures(monkeypatch, status, code):
    import collectors.ors_collector as module

    class Client:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def post(self, url, **_kwargs):
            return httpx.Response(status, request=httpx.Request("POST", url))

    monkeypatch.setattr(settings, "ORS_API_KEY", "test-secret")
    monkeypatch.setattr(settings, "ORS_CACHE_DIR", "")
    monkeypatch.setattr(module.httpx, "AsyncClient", Client)

    with pytest.raises(CollectorError) as captured:
        asyncio.run(OrsWheelchairRouteCollector().collect(ORIGIN, DEST))

    assert captured.value.code == code
    assert captured.value.retryable is False


def test_ors_persistent_cache_does_not_store_api_key(monkeypatch, tmp_path):
    import collectors.ors_collector as module

    requests = 0

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return _ors_payload()

    class Client:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def post(self, *_args, **_kwargs):
            nonlocal requests
            requests += 1
            return Response()

    monkeypatch.setattr(settings, "ORS_API_KEY", "test-secret")
    monkeypatch.setattr(settings, "ORS_CACHE_DIR", str(tmp_path))
    monkeypatch.setattr(module.httpx, "AsyncClient", Client)

    asyncio.run(OrsWheelchairRouteCollector().collect(ORIGIN, DEST))
    asyncio.run(OrsWheelchairRouteCollector().collect(ORIGIN, DEST))

    cache_path = next(tmp_path.glob("*.json"))
    wrapper = json.loads(cache_path.read_text(encoding="utf-8"))
    wrapper["cachedAtEpoch"] = 0
    cache_path.write_text(json.dumps(wrapper), encoding="utf-8")
    asyncio.run(OrsWheelchairRouteCollector().collect(ORIGIN, DEST))

    assert requests == 1
    cache_text = cache_path.read_text(encoding="utf-8")
    assert "test-secret" not in cache_text


def test_tmap_persistent_cache_avoids_repeated_provider_call(
    monkeypatch,
    tmp_path,
):
    import collectors.tmap_collector as module

    payload = {
        "features": [{
            "geometry": {
                "type": "LineString",
                "coordinates": [
                    [ORIGIN.lng, ORIGIN.lat],
                    [DEST.lng, DEST.lat],
                ],
            },
            "properties": {
                "totalTime": 600,
                "totalDistance": 1000,
            },
        }],
    }
    requests = 0

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return payload

    class Client:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def post(self, *_args, **_kwargs):
            nonlocal requests
            requests += 1
            await asyncio.sleep(0.01)
            return Response()

    monkeypatch.setattr(settings, "TMAP_API_KEY", "test-secret")
    monkeypatch.setattr(settings, "TMAP_CACHE_DIR", str(tmp_path))
    monkeypatch.setattr(settings, "TMAP_CACHE_TTL_SECONDS", 1800)
    monkeypatch.setattr(module.httpx, "AsyncClient", Client)

    async def collect_concurrently():
        return await asyncio.gather(
            TmapRouteCollector().collect(ORIGIN, DEST),
            TmapRouteCollector().collect(ORIGIN, DEST),
        )

    first, second = asyncio.run(collect_concurrently())
    third = asyncio.run(TmapRouteCollector().collect(ORIGIN, DEST))
    monkeypatch.setattr(settings, "TMAP_API_KEY", "")
    cached_only = asyncio.run(
        TmapRouteCollector().collect_cached(ORIGIN, DEST)
    )

    assert requests == 1
    assert first[0].path == second[0].path
    assert second[0].path == third[0].path
    assert cached_only[0].path == third[0].path
    cache_text = next(tmp_path.glob("*.json")).read_text(encoding="utf-8")
    assert "test-secret" not in cache_text


def test_tmap_precomputed_cache_survives_age_and_never_calls_provider(
    monkeypatch,
    tmp_path,
):
    import collectors.tmap_collector as module

    writable = tmp_path / "writable"
    precomputed = tmp_path / "precomputed"
    payload = {
        "features": [{
            "geometry": {
                "type": "LineString",
                "coordinates": [
                    [ORIGIN.lng, ORIGIN.lat],
                    [DEST.lng, DEST.lat],
                ],
            },
            "properties": {
                "totalTime": 600,
                "totalDistance": 1000,
            },
        }],
    }
    module.write_precomputed_cache(
        ORIGIN,
        DEST,
        search_option=module.STAIR_EXCLUDED_SEARCH_OPTION,
        payload=payload,
        cache_dir=precomputed,
    )
    wrapper_path = next(precomputed.glob("*.json"))
    wrapper = json.loads(wrapper_path.read_text(encoding="utf-8"))
    wrapper["cachedAtEpoch"] = 0
    wrapper_path.write_text(json.dumps(wrapper), encoding="utf-8")

    class ForbiddenClient:
        def __init__(self, *_args, **_kwargs):
            raise AssertionError("사전가공 캐시 적중 시 TMAP을 호출하면 안 됩니다.")

    monkeypatch.setattr(settings, "TMAP_API_KEY", "test-secret")
    monkeypatch.setattr(settings, "TMAP_CACHE_DIR", str(writable))
    monkeypatch.setattr(settings, "TMAP_PRECOMPUTED_CACHE_DIR", str(precomputed))
    monkeypatch.setattr(module.httpx, "AsyncClient", ForbiddenClient)

    result = asyncio.run(
        TmapRouteCollector(avoid_stairs=True).collect_cached(ORIGIN, DEST)
    )

    assert result[0].path == [ORIGIN, DEST]
    assert not writable.exists()


def test_tmap_invalid_writable_cache_does_not_hide_valid_precomputed(
    monkeypatch,
    tmp_path,
):
    import collectors.tmap_collector as module

    writable = tmp_path / "writable"
    precomputed = tmp_path / "precomputed"
    payload = {
        "features": [{
            "geometry": {
                "type": "LineString",
                "coordinates": [
                    [ORIGIN.lng, ORIGIN.lat],
                    [DEST.lng, DEST.lat],
                ],
            },
            "properties": {
                "totalTime": 600,
                "totalDistance": 1000,
            },
        }],
    }
    module.write_precomputed_cache(
        ORIGIN,
        DEST,
        search_option=module.STAIR_EXCLUDED_SEARCH_OPTION,
        payload=payload,
        cache_dir=precomputed,
    )
    identity = module._cache_identity(
        ORIGIN,
        DEST,
        search_option=module.STAIR_EXCLUDED_SEARCH_OPTION,
    )
    invalid_path = module._cache_path(identity, str(writable))
    assert invalid_path is not None
    invalid_path.parent.mkdir(parents=True)
    invalid_path.write_text(json.dumps({
        "schemaVersion": module.CACHE_SCHEMA_VERSION,
        "cachedAtEpoch": 1,
        "payload": {"features": []},
    }), encoding="utf-8")
    monkeypatch.setattr(settings, "TMAP_CACHE_DIR", str(writable))
    monkeypatch.setattr(settings, "TMAP_PRECOMPUTED_CACHE_DIR", str(precomputed))

    result = asyncio.run(
        TmapRouteCollector(avoid_stairs=True).collect_cached(ORIGIN, DEST)
    )

    assert result[0].path == [ORIGIN, DEST]


def test_tmap_cached_only_miss_never_calls_provider(monkeypatch, tmp_path):
    import collectors.tmap_collector as module

    class ForbiddenClient:
        def __init__(self, *_args, **_kwargs):
            raise AssertionError("cached-only 조회가 TMAP 네트워크를 호출했습니다.")

    monkeypatch.setattr(settings, "TMAP_API_KEY", "test-secret")
    monkeypatch.setattr(settings, "TMAP_CACHE_DIR", str(tmp_path))
    monkeypatch.setattr(module.httpx, "AsyncClient", ForbiddenClient)

    assert asyncio.run(
        TmapRouteCollector(avoid_stairs=True).collect_cached(ORIGIN, DEST)
    ) == []


def test_tmap_wheelchair_request_uses_official_stair_excluded_option_and_ramp_codes(
    monkeypatch,
):
    import collectors.tmap_collector as module

    payload = {
        "features": [
            {
                "geometry": {
                    "type": "Point",
                    "coordinates": [129.0562, 35.1602],
                },
                "properties": {
                    "turnType": 129,
                    "totalTime": 600,
                    "totalDistance": 1000,
                },
            },
            {
                "geometry": {
                    "type": "LineString",
                    "coordinates": [
                        [ORIGIN.lng, ORIGIN.lat],
                        [DEST.lng, DEST.lat],
                    ],
                },
                "properties": {"facilityType": 11},
            },
        ],
    }
    captured = {}

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return payload

    class Client:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def post(self, *_args, **kwargs):
            captured.update(kwargs)
            return Response()

    monkeypatch.setattr(settings, "TMAP_API_KEY", "test-secret")
    monkeypatch.setattr(settings, "TMAP_CACHE_DIR", "")
    monkeypatch.setattr(module.httpx, "AsyncClient", Client)

    candidate = asyncio.run(
        TmapRouteCollector(avoid_stairs=True).collect(ORIGIN, DEST)
    )[0]

    assert captured["json"]["searchOption"] == "30"
    assert captured["params"] == {"version": "1"}
    assert candidate.accessibility_evidence == {
        "provider": "TMAP pedestrian",
        "search_option": "30",
        "stairs_excluded_by_provider": True,
        "stair_feature_count": 0,
        "ramp_points": [{
            "lat": 35.1602,
            "lng": 129.0562,
            "turn_type": 129,
            "facility_type": None,
            "replaces_stairs": True,
        }],
    }


def test_tmap_official_ramp_facility_lines_are_physical_ramp_evidence():
    collector = TmapRouteCollector(avoid_stairs=True)
    payload = {
        "features": [
            {
                "geometry": {
                    "type": "Point",
                    "coordinates": [ORIGIN.lng, ORIGIN.lat],
                },
                "properties": {
                    "totalTime": 600,
                    "totalDistance": 1000,
                },
            },
            {
                "geometry": {
                    "type": "LineString",
                    "coordinates": [
                        [ORIGIN.lng, ORIGIN.lat],
                        [DEST.lng, DEST.lat],
                    ],
                },
                "properties": {"facilityType": 20},
            },
        ],
    }

    candidate = collector._candidate_from_data(payload)

    assert candidate.accessibility_evidence["ramp_points"] == [
        {
            "lat": ORIGIN.lat,
            "lng": ORIGIN.lng,
            "turn_type": None,
            "facility_type": 20,
            "replaces_stairs": True,
        },
        {
            "lat": DEST.lat,
            "lng": DEST.lng,
            "turn_type": None,
            "facility_type": 20,
            "replaces_stairs": True,
        },
    ]


def test_tmap_stair_excluded_response_rejects_contradictory_stair_feature():
    collector = TmapRouteCollector(avoid_stairs=True)
    payload = {
        "features": [
            {
                "geometry": {
                    "type": "Point",
                    "coordinates": [ORIGIN.lng, ORIGIN.lat],
                },
                "properties": {
                    "turnType": 127,
                    "totalTime": 600,
                    "totalDistance": 1000,
                },
            },
            {
                "geometry": {
                    "type": "LineString",
                    "coordinates": [
                        [ORIGIN.lng, ORIGIN.lat],
                        [DEST.lng, DEST.lat],
                    ],
                },
                "properties": {"facilityType": 17},
            },
        ],
    }

    with pytest.raises(CollectorError, match="계단 제외 경로"):
        collector._candidate_from_data(payload)


def test_tmap_rejects_ramp_point_outside_returned_walk_geometry():
    collector = TmapRouteCollector(avoid_stairs=True)
    payload = {
        "features": [
            {
                "geometry": {
                    "type": "Point",
                    "coordinates": [129.08, 35.18],
                },
                "properties": {
                    "turnType": 129,
                    "totalTime": 600,
                    "totalDistance": 1000,
                },
            },
            {
                "geometry": {
                    "type": "LineString",
                    "coordinates": [
                        [ORIGIN.lng, ORIGIN.lat],
                        [DEST.lng, DEST.lat],
                    ],
                },
                "properties": {},
            },
        ],
    }

    with pytest.raises(CollectorError, match="보행 선형과 일치하지"):
        collector._candidate_from_data(payload)


def test_tmap_quota_backoff_limits_repeated_provider_calls(
    monkeypatch,
    tmp_path,
):
    import collectors.tmap_collector as module

    requests = 0

    class Client:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def post(self, *_args, **_kwargs):
            nonlocal requests
            requests += 1
            request = httpx.Request("POST", TmapRouteCollector.BASE_URL)
            return httpx.Response(
                429,
                request=request,
                json={"error": {"code": "QUOTA_EXCEEDED"}},
            )

    monkeypatch.setattr(settings, "TMAP_API_KEY", "test-secret")
    monkeypatch.setattr(settings, "TMAP_CACHE_DIR", str(tmp_path))
    monkeypatch.setattr(module.httpx, "AsyncClient", Client)
    module._clear_quota_backoff()

    with pytest.raises(CollectorError, match="한도 초과"):
        asyncio.run(TmapRouteCollector().collect(ORIGIN, DEST))
    with pytest.raises(CollectorError, match="대기 중"):
        asyncio.run(TmapRouteCollector().collect(
            Coordinate(35.17, 129.06),
            Coordinate(35.18, 129.07),
        ))

    assert requests == 1
    module._clear_quota_backoff()


def test_odsay_walk_geometry_defaults_to_estimated_without_provider(monkeypatch):
    monkeypatch.setattr(settings, "TMAP_API_KEY", "")
    monkeypatch.setattr(settings, "OSMNX_WALK_GEOMETRY_ENABLED", False)

    path, quality, evidence = asyncio.run(
        OdsayRouteCollector()._walk_geometry(ORIGIN, DEST)
    )

    assert path == [ORIGIN, DEST]
    assert quality == "estimated"
    assert evidence == {}


def test_wheelchair_prefilter_rejects_unconfirmed_bus_before_ors():
    collector = OdsayRouteCollector(uses_wheelchair=True)
    confirmed = {
        "subPath": [{
            "trafficType": 2,
            "lane": [{"busNo": "100", "lowFloorYn": "Y"}],
        }],
    }
    unknown = {
        "subPath": [{
            "trafficType": 2,
            "lane": [{"busNo": "100"}],
        }],
    }

    assert collector._wheelchair_transit_prerequisites_known(
        confirmed,
        ORIGIN,
        DEST,
    ) is True
    assert collector._wheelchair_transit_prerequisites_known(
        unknown,
        ORIGIN,
        DEST,
    ) is False


def test_wheelchair_prefilter_requires_official_subway_endpoint_exits():
    line = 1
    start_name = "테스트시작역"
    end_name = "테스트도착역"
    exits = {
        (line, "테스트시작"): (
            AccessibleSubwayExit("1", ORIGIN, 11),
        ),
        (line, "테스트도착"): (
            AccessibleSubwayExit("2", DEST, 22),
        ),
    }
    path = {
        "subPath": [{
            "trafficType": 1,
            "startName": start_name,
            "endName": end_name,
            "lane": [{"subwayCode": 71}],
        }],
    }

    assert OdsayRouteCollector(
        uses_wheelchair=True,
        accessible_subway_exits=exits,
    )._wheelchair_transit_prerequisites_known(
        path,
        ORIGIN,
        DEST,
    ) is True
    assert OdsayRouteCollector(
        uses_wheelchair=True,
        accessible_subway_exits={},
    )._wheelchair_transit_prerequisites_known(
        path,
        ORIGIN,
        DEST,
    ) is False


def test_odsay_walk_geometry_prefers_tmap(monkeypatch):
    async def tmap_collect(_self, _start, _end):
        return [SimpleNamespace(path=[ORIGIN, DEST])]

    async def osmnx_collect(_self, _start, _end):
        raise AssertionError("TMAP 성공 후 OSMnx를 호출하면 안 됩니다.")

    monkeypatch.setattr(settings, "TMAP_API_KEY", "test-key")
    monkeypatch.setattr(settings, "OSMNX_WALK_GEOMETRY_ENABLED", True)
    monkeypatch.setattr(TmapRouteCollector, "collect", tmap_collect)
    monkeypatch.setattr(OsmnxRouteCollector, "collect", osmnx_collect)

    path, quality, evidence = asyncio.run(
        OdsayRouteCollector(avoid_stairs=True)._walk_geometry(ORIGIN, DEST)
    )

    assert path == [ORIGIN, DEST]
    assert quality == "exact"
    assert evidence == {}


def test_odsay_wheelchair_walk_uses_ors_and_merges_similar_tmap_ramp(
    monkeypatch,
):
    async def ors_collect(_self, _start, _end):
        return [SimpleNamespace(
            path=[ORIGIN, DEST],
            accessibility_evidence={
                "providers": ["openrouteservice wheelchair"],
                "wheelchair_constraints_applied": True,
                "wheelchair_restrictions": WHEELCHAIR_RESTRICTIONS,
                "stairs_excluded_by_provider": True,
                "wheelchair_data_limitations": ["OSM 태그 누락 가능"],
                "wheelchair_constraint_categories": [
                    "steps", "surface", "width", "wheelchair_access"
                ],
            },
        )]

    async def tmap_collect(_self, _start, _end):
        return [SimpleNamespace(
            path=[ORIGIN, DEST],
            accessibility_evidence={
                "provider": "TMAP pedestrian",
                "stairs_excluded_by_provider": True,
                "ramp_points": [{
                    "lat": 35.16,
                    "lng": 129.05,
                    "turn_type": 129,
                    "replaces_stairs": True,
                }],
            },
        )]

    monkeypatch.setattr(settings, "ORS_API_KEY", "ors-key")
    monkeypatch.setattr(settings, "TMAP_API_KEY", "tmap-key")
    monkeypatch.setattr(OrsWheelchairRouteCollector, "collect", ors_collect)
    monkeypatch.setattr(TmapRouteCollector, "collect_cached", tmap_collect)

    path, quality, evidence = asyncio.run(
        OdsayRouteCollector(
            avoid_stairs=True,
            uses_wheelchair=True,
        )._walk_geometry(ORIGIN, DEST)
    )

    assert path == [ORIGIN, DEST]
    assert quality == "exact"
    assert evidence["wheelchair_constraints_applied"] is True
    assert evidence["ramp_points"][0]["replaces_stairs"] is True
    assert evidence["providers"] == [
        "openrouteservice wheelchair",
        "TMAP pedestrian",
    ]


def test_odsay_wheelchair_walk_never_falls_back_when_ors_is_unavailable(
    monkeypatch,
):
    async def ors_collect(_self, _start, _end):
        raise CollectorNotConfigured("ORS_API_KEY가 설정되지 않았습니다.")

    async def tmap_collect(_self, _start, _end):
        raise AssertionError("ORS 실패 후 TMAP 경로를 통행 가능으로 쓰면 안 됩니다.")

    monkeypatch.setattr(settings, "ORS_API_KEY", "")
    monkeypatch.setattr(settings, "TMAP_API_KEY", "tmap-key")
    monkeypatch.setattr(OrsWheelchairRouteCollector, "collect", ors_collect)
    monkeypatch.setattr(TmapRouteCollector, "collect_cached", tmap_collect)

    with pytest.raises(CollectorNotConfigured):
        asyncio.run(
            OdsayRouteCollector(
                avoid_stairs=True,
                uses_wheelchair=True,
            )._walk_geometry(ORIGIN, DEST)
        )


def test_odsay_walk_geometry_uses_osmnx_only_when_enabled(monkeypatch):
    async def osmnx_collect(_self, _start, _end):
        return [SimpleNamespace(path=[ORIGIN, DEST])]

    monkeypatch.setattr(settings, "TMAP_API_KEY", "")
    monkeypatch.setattr(settings, "OSMNX_WALK_GEOMETRY_ENABLED", True)
    monkeypatch.setattr(settings, "OSMNX_WALK_GEOMETRY_BLOCKING", False)
    monkeypatch.setattr(
        OsmnxRouteCollector,
        "collect_cached_or_schedule",
        osmnx_collect,
    )

    path, quality, evidence = asyncio.run(
        OdsayRouteCollector()._walk_geometry(ORIGIN, DEST)
    )

    assert path == [ORIGIN, DEST]
    assert quality == "exact"
    assert evidence == {}


def test_odsay_walk_geometry_can_block_for_labeling_collection(monkeypatch):
    async def osmnx_collect(_self, _start, _end):
        return [SimpleNamespace(path=[ORIGIN, DEST])]

    async def cached_collect(_self, _start, _end):
        raise AssertionError("동기 수집 모드에서 캐시 전용 경로를 호출했습니다.")

    monkeypatch.setattr(settings, "TMAP_API_KEY", "")
    monkeypatch.setattr(settings, "OSMNX_WALK_GEOMETRY_ENABLED", True)
    monkeypatch.setattr(settings, "OSMNX_WALK_GEOMETRY_BLOCKING", True)
    monkeypatch.setattr(OsmnxRouteCollector, "collect", osmnx_collect)
    monkeypatch.setattr(
        OsmnxRouteCollector,
        "collect_cached_or_schedule",
        cached_collect,
    )

    path, quality, evidence = asyncio.run(
        OdsayRouteCollector()._walk_geometry(ORIGIN, DEST)
    )

    assert path == [ORIGIN, DEST]
    assert quality == "exact"
    assert evidence == {}


def test_odsay_walk_geometry_falls_back_when_enabled_providers_fail(monkeypatch):
    async def fail_collect(_self, _start, _end):
        raise CollectorError("provider unavailable")

    monkeypatch.setattr(settings, "TMAP_API_KEY", "test-key")
    monkeypatch.setattr(settings, "OSMNX_WALK_GEOMETRY_ENABLED", True)
    monkeypatch.setattr(TmapRouteCollector, "collect", fail_collect)
    monkeypatch.setattr(
        OsmnxRouteCollector,
        "collect_cached_or_schedule",
        fail_collect,
    )

    path, quality, evidence = asyncio.run(
        OdsayRouteCollector()._walk_geometry(ORIGIN, DEST)
    )

    assert path == [ORIGIN, DEST]
    assert quality == "estimated"
    assert evidence == {}


def test_odsay_walk_geometry_returns_immediately_while_cache_warms(
    monkeypatch,
    tmp_path,
):
    import collectors.osmnx_collector as osmnx_collector

    warmed = False

    def slow_graph(_origin, _destination):
        nonlocal warmed
        time.sleep(0.05)
        warmed = True
        return object()

    monkeypatch.setattr(settings, "TMAP_API_KEY", "")
    monkeypatch.setattr(settings, "OSMNX_WALK_GEOMETRY_ENABLED", True)
    monkeypatch.setattr(osmnx_collector, "GRAPH_CACHE_DIR", tmp_path)
    osmnx_collector._graphs.clear()
    osmnx_collector._routing_indexes.clear()
    osmnx_collector._warming_keys.clear()
    monkeypatch.setattr(osmnx_collector, "_get_graph", slow_graph)

    async def run():
        started = time.perf_counter()
        path, quality, evidence = await OdsayRouteCollector()._walk_geometry(
            ORIGIN,
            DEST,
        )
        elapsed = time.perf_counter() - started
        tasks = tuple(osmnx_collector._warm_tasks)
        if tasks:
            await asyncio.gather(*tasks)
        return path, quality, evidence, elapsed

    path, quality, evidence, elapsed = asyncio.run(run())

    assert path == [ORIGIN, DEST]
    assert quality == "estimated"
    assert evidence == {}
    assert elapsed < 0.04
    assert warmed is True


def test_osmnx_uses_writable_app_cache_without_status_rate_limit():
    import collectors.osmnx_collector as osmnx_collector

    assert osmnx_collector.ox.settings.overpass_rate_limit is False
    assert osmnx_collector.ox.settings.cache_folder == (
        osmnx_collector.GRAPH_CACHE_DIR / "http"
    )
    assert osmnx_collector.ox.settings.http_user_agent.startswith("KT-10-")
    assert osmnx_collector.ox.settings.overpass_url == str(
        settings.OSMNX_OVERPASS_URL
    ).rstrip("/")


def test_osmnx_prefers_prebuilt_regional_graph(monkeypatch, tmp_path):
    import networkx as nx
    import collectors.osmnx_collector as osmnx_collector

    regional_path = tmp_path / "busan-walk.graphml"
    regional_path.touch()
    graph = nx.DiGraph()
    loads = 0

    def load_graph(_path, **_kwargs):
        nonlocal loads
        loads += 1
        return graph

    monkeypatch.setattr(osmnx_collector, "GRAPH_CACHE_DIR", tmp_path)
    monkeypatch.setattr(osmnx_collector.nx, "read_graphml", load_graph)
    monkeypatch.setattr(
        osmnx_collector.ox.graph,
        "graph_from_bbox",
        lambda *_args, **_kwargs: pytest.fail(
            "지역 보행 그래프가 있으면 Overpass를 호출하면 안 됩니다."
        ),
    )
    osmnx_collector._graphs.clear()
    osmnx_collector._digraphs.clear()
    osmnx_collector._routing_indexes.clear()

    first = osmnx_collector._get_graph(ORIGIN, DEST)
    second = osmnx_collector._get_graph(ORIGIN, DEST)

    assert first is graph
    assert second is graph
    assert loads == 1


def test_osmnx_fails_explicitly_when_graph_unavailable(monkeypatch):
    import collectors.osmnx_collector as osmnx_collector

    def _raise(*args, **kwargs):
        raise RuntimeError("network unavailable in test environment")

    monkeypatch.setattr(osmnx_collector, "_get_graph", _raise)

    with pytest.raises(CollectorError):
        asyncio.run(OsmnxRouteCollector().collect(ORIGIN, DEST))


def test_osmnx_handles_multidigraph_parallel_edges(monkeypatch):
    """
    OSMnx 그래프는 MultiDiGraph이며 병렬 간선을 가질 수 있다.
    nx.shortest_simple_paths는 MultiDiGraph를 지원하지 않으므로
    DiGraph로 변환하는 처리가 누락되면 NetworkXNotImplemented가 발생한다.
    """
    import networkx as nx
    import collectors.osmnx_collector as osmnx_collector

    G = nx.MultiDiGraph()
    G.add_node(1, x=ORIGIN.lng, y=ORIGIN.lat)
    G.add_node(2, x=129.0560, y=35.1600)
    G.add_node(3, x=DEST.lng, y=DEST.lat)
    G.add_edge(1, 2, length=100.0)
    G.add_edge(1, 2, length=90.0)  # 병렬 간선
    G.add_edge(2, 3, length=150.0)
    G.add_edge(2, 1, length=90.0)
    G.add_edge(3, 2, length=150.0)
    G.graph["crs"] = "EPSG:4326"

    monkeypatch.setattr(osmnx_collector, "_get_graph", lambda *_: G)

    result = asyncio.run(OsmnxRouteCollector().collect(ORIGIN, DEST))
    assert len(result) == 1
    assert result[0].source == "osmnx"
    assert result[0].raw_response is None
    assert result[0].distance_m == 240.0  # 90(최단 병렬 간선) + 150
    assert result[0].duration_min is None


def test_osmnx_resnaps_away_from_disconnected_nearest_nodes(monkeypatch):
    import networkx as nx
    import collectors.osmnx_collector as osmnx_collector

    graph = nx.MultiDiGraph()
    graph.add_node(1, x=ORIGIN.lng + 0.0001, y=ORIGIN.lat + 0.0001)
    graph.add_node(2, x=DEST.lng - 0.0001, y=DEST.lat - 0.0001)
    graph.add_edge(1, 2, length=250.0)
    graph.add_edge(2, 1, length=250.0)
    graph.add_node(3, x=ORIGIN.lng, y=ORIGIN.lat)
    graph.add_node(4, x=DEST.lng, y=DEST.lat)
    graph.graph["crs"] = "EPSG:4326"

    monkeypatch.setattr(osmnx_collector, "_get_graph", lambda *_: graph)

    result = asyncio.run(OsmnxRouteCollector().collect(ORIGIN, DEST))

    assert result[0].path == [
        Coordinate(lat=ORIGIN.lat + 0.0001, lng=ORIGIN.lng + 0.0001),
        Coordinate(lat=DEST.lat - 0.0001, lng=DEST.lng - 0.0001),
    ]
    assert result[0].distance_m == 250.0


def test_osmnx_resnaps_to_strongly_connected_walking_core(monkeypatch):
    import networkx as nx
    import collectors.osmnx_collector as osmnx_collector

    graph = nx.MultiDiGraph()
    graph.add_node(1, x=ORIGIN.lng + 0.0001, y=ORIGIN.lat + 0.0001)
    graph.add_node(2, x=DEST.lng - 0.0001, y=DEST.lat - 0.0001)
    graph.add_edge(1, 2, length=250.0)
    graph.add_edge(2, 1, length=250.0)
    graph.add_node(3, x=ORIGIN.lng, y=ORIGIN.lat)
    graph.add_node(4, x=DEST.lng, y=DEST.lat)
    graph.add_edge(1, 3, length=10.0)
    graph.add_edge(4, 2, length=10.0)
    graph.graph["crs"] = "EPSG:4326"

    monkeypatch.setattr(osmnx_collector, "_get_graph", lambda *_: graph)

    result = asyncio.run(OsmnxRouteCollector().collect(ORIGIN, DEST))

    assert result[0].path == [
        Coordinate(lat=ORIGIN.lat + 0.0001, lng=ORIGIN.lng + 0.0001),
        Coordinate(lat=DEST.lat - 0.0001, lng=DEST.lng - 0.0001),
    ]
    assert result[0].distance_m == 250.0


def test_osmnx_uses_distinct_connected_nodes_for_short_walk(monkeypatch):
    import networkx as nx
    import collectors.osmnx_collector as osmnx_collector

    graph = nx.MultiDiGraph()
    graph.add_node(1, x=ORIGIN.lng, y=ORIGIN.lat)
    graph.add_node(2, x=ORIGIN.lng + 0.0001, y=ORIGIN.lat + 0.0001)
    graph.add_edge(1, 2, length=15.0)
    graph.add_edge(2, 1, length=15.0)
    graph.graph["crs"] = "EPSG:4326"
    very_close = Coordinate(
        lat=ORIGIN.lat + 0.000001,
        lng=ORIGIN.lng + 0.000001,
    )

    monkeypatch.setattr(osmnx_collector, "_get_graph", lambda *_: graph)

    result = asyncio.run(OsmnxRouteCollector().collect(ORIGIN, very_close))

    assert len(result[0].path) == 2
    assert result[0].distance_m == 15.0


def test_odsay_load_lane_restores_map_base():
    """공식 loadLane 응답의 상대 graphPos에 mapObject 기준점을 복원한다."""
    data = {
        "result": {
            "lane": [{
                "section": [{"graphPos": [
                    {"x": 3.0500, "y": 0.1150},
                    {"x": 3.0510, "y": 0.1160},
                ]}]
            }]
        }
    }
    coords = OdsayRouteCollector._lane_coordinates(data, "126:35@71:2:1:2")
    assert coords == [
        Coordinate(lat=35.1150, lng=129.0500),
        Coordinate(lat=35.1160, lng=129.0510),
    ]


def test_odsay_load_lane_keeps_absolute_coordinates():
    data = {"result": {"lane": [{"section": [{"graphPos": [
        {"x": 129.0500, "y": 35.1150}, {"x": 129.0510, "y": 35.1160},
    ]}]}]}}
    coords = OdsayRouteCollector._lane_coordinates(data, "126:35@71:2:1:2")
    assert coords[0] == Coordinate(lat=35.1150, lng=129.0500)


def test_odsay_normalizes_abbreviated_search_map_object():
    assert OdsayRouteCollector._load_lane_map_object("71216:1:17:20") == "0:0@71216:1:17:20"
    assert (
        OdsayRouteCollector._load_lane_map_object(
            "70002:2:70231:70219@70001:2:70119:70113"
        )
        == "0:0@70002:2:70231:70219@70001:2:70119:70113"
    )
    assert (
        OdsayRouteCollector._load_lane_map_object("126:35@100:1:1:2")
        == "126:35@100:1:1:2"
    )


def test_odsay_collect_defers_load_lane_and_keeps_refinement_descriptor(
    monkeypatch,
):
    """최초 수집은 search 1회만 호출하고 loadLane은 호출하지 않는다."""
    import collectors.odsay_collector as module

    search_payload = {"result": {"path": [{
        "info": {"totalTime": 20, "totalDistance": 5000, "totalWalk": 100, "mapObj": "100:1:1:2"},
        "subPath": [{
            "trafficType": 2, "sectionTime": 18, "distance": 4900,
            "startName": "부산역", "endName": "서면역", "lane": [{"busNo": "100"}],
            "startX": 129.04, "startY": 35.115,
            "endX": 129.059, "endY": 35.157,
        }],
    }]}}
    requested_urls = []

    class Response:
        def __init__(self, payload): self.payload = payload
        def raise_for_status(self): return None
        def json(self): return self.payload

    class Client:
        def __init__(self, *args, **kwargs): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *args): return None
        async def get(self, url, **kwargs):
            requested_urls.append(url)
            assert not url.endswith("loadLane")
            return Response(search_payload)

    monkeypatch.setattr(settings, "ODSAY_API_KEY", "test-key")
    monkeypatch.setattr(settings, "ODSAY_LOAD_LANE_ENABLED", True)
    monkeypatch.setattr(module.httpx, "AsyncClient", Client)
    result = asyncio.run(OdsayRouteCollector().collect(ORIGIN, DEST))
    assert requested_urls == [OdsayRouteCollector.BASE_URL]
    assert len(result) == 1
    assert result[0].duration_min == 20
    assert result[0].distance_m == 5000
    # 정류장 좌표 기반 표시 선형은 exact로 위장하지 않는다.
    assert result[0].geometry_quality == "estimated"
    assert result[0].segments[0]["mode"] == "bus"
    assert result[0].segments[0]["geometry_quality"] == "estimated"
    assert len(result[0].segments[0]["path"]) == 2
    descriptor = result[0].transit_refinement
    assert descriptor is not None
    assert descriptor["map_object"] == "100:1:1:2"
    assert descriptor["provider_candidate_index"] == 1
    assert descriptor["origin"] == {"lat": ORIGIN.lat, "lng": ORIGIN.lng}
    assert descriptor["destination"] == {"lat": DEST.lat, "lng": DEST.lng}


def test_odsay_refine_transit_fetches_exact_lane_geometry(monkeypatch):
    """선택된 후보 정밀화는 loadLane 1회로 exact 선형만 조회한다."""
    import collectors.odsay_collector as module

    lane_payload = {"result": {"lane": [{"section": [{"graphPos": [
        {"x": 129.04, "y": 35.115}, {"x": 129.059, "y": 35.157},
    ]}]}]}}
    requested_urls = []

    class Response:
        def __init__(self, payload): self.payload = payload
        def raise_for_status(self): return None
        def json(self): return self.payload

    class Client:
        def __init__(self, *args, **kwargs): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *args): return None
        async def get(self, url, **kwargs):
            requested_urls.append(url)
            assert url.endswith("loadLane")
            assert kwargs["params"]["mapObject"] == "0:0@100:1:1:2"
            return Response(lane_payload)

    monkeypatch.setattr(settings, "ODSAY_API_KEY", "test-key")
    monkeypatch.setattr(module.httpx, "AsyncClient", Client)
    paths = asyncio.run(
        OdsayRouteCollector().refine_transit("100:1:1:2", ORIGIN, DEST)
    )
    assert requested_urls == [OdsayRouteCollector.LANE_URL]
    assert paths == [[
        Coordinate(lat=35.115, lng=129.04),
        Coordinate(lat=35.157, lng=129.059),
    ]]


def test_odsay_labeling_mode_skips_load_lane_and_marks_transit_estimated(
    monkeypatch,
):
    import collectors.odsay_collector as module

    search_payload = {"result": {"path": [{
        "info": {
            "totalTime": 20,
            "totalDistance": 5000,
            "totalWalk": 100,
        },
        "subPath": [{
            "trafficType": 2,
            "sectionTime": 18,
            "distance": 4900,
            "startX": 129.04,
            "startY": 35.115,
            "endX": 129.059,
            "endY": 35.157,
            "passStopList": {"stations": [
                {"x": "129.04", "y": "35.115"},
                {"x": "129.05", "y": "35.14"},
                {"x": "129.059", "y": "35.157"},
            ]},
            "lane": [{"busNo": "100"}],
        }],
    }]}}
    requested_urls = []

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return search_payload

    class Client:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def get(self, url, **kwargs):
            requested_urls.append(url)
            return Response()

    monkeypatch.setattr(settings, "ODSAY_API_KEY", "test-key")
    monkeypatch.setattr(settings, "ODSAY_LOAD_LANE_ENABLED", False)
    monkeypatch.setattr(module.httpx, "AsyncClient", Client)

    result = asyncio.run(OdsayRouteCollector().collect(ORIGIN, DEST))

    assert len(result) == 1
    assert requested_urls == [OdsayRouteCollector.BASE_URL]
    assert result[0].geometry_quality == "estimated"
    assert result[0].segments[0]["geometry_quality"] == "estimated"
    assert result[0].segments[0]["path"] == [
        Coordinate(lat=35.115, lng=129.04),
        Coordinate(lat=35.14, lng=129.05),
        Coordinate(lat=35.157, lng=129.059),
    ]


def test_odsay_respects_requested_candidate_limit_in_batches_of_three(monkeypatch):
    import collectors.odsay_collector as module

    search_payload = {
        "result": {"path": [{"candidate": index} for index in range(7)]}
    }
    active = 0
    max_active = 0

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return search_payload

    class Client:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def get(self, *_args, **_kwargs):
            return Response()

    async def fake_build(path, _origin, _destination):
        nonlocal active, max_active
        active += 1
        max_active = max(max_active, active)
        await asyncio.sleep(0.01)
        active -= 1
        return SimpleNamespace(candidate=path["candidate"])

    collector = OdsayRouteCollector()
    monkeypatch.setattr(settings, "ODSAY_API_KEY", "test-key")
    monkeypatch.setattr(module.httpx, "AsyncClient", Client)
    monkeypatch.setattr(collector, "_build_candidate", fake_build)

    result = asyncio.run(
        collector.collect(ORIGIN, DEST, max_candidates=5)
    )

    assert [item.candidate for item in result] == [0, 1, 2, 3, 4]
    assert max_active == 3


def test_odsay_rejects_malformed_map_object_tokens():
    with pytest.raises(CollectorError, match="노선 토큰"):
        OdsayRouteCollector._load_lane_map_object("malformed")
    with pytest.raises(CollectorError, match="노선 토큰"):
        OdsayRouteCollector._load_lane_map_object("126:35@too:few")


def test_odsay_lane_paths_preserve_empty_lane_position():
    payload = {"result": {"lane": [
        {"section": [{"graphPos": [{"x": "bad", "y": 35.1}]}]},
        {"section": [{"graphPos": [
            {"x": 129.05, "y": 35.11},
            {"x": 129.06, "y": 35.12},
        ]}]},
    ]}}

    paths = OdsayRouteCollector._lane_paths(
        payload,
        "126:35@100:1:1:2@101:1:1:2",
    )

    assert paths[0] == []
    assert paths[1][0] == Coordinate(lat=35.11, lng=129.05)


def test_odsay_zero_distance_transfer_does_not_create_detour(monkeypatch):
    collector = OdsayRouteCollector()
    shared_stop = {"startX": 129.05, "startY": 35.10}
    path = {
        "info": {"totalTime": 20, "totalDistance": 2000},
        "subPath": [
            {"trafficType": 3, "sectionTime": 3, "distance": 100},
            {
                "trafficType": 2,
                "sectionTime": 8,
                "distance": 900,
                "startX": 129.04,
                "startY": 35.11,
                "endX": 129.05,
                "endY": 35.10,
            },
            {"trafficType": 3, "sectionTime": 0, "distance": 0},
            {
                "trafficType": 2,
                "sectionTime": 6,
                "distance": 900,
                **shared_stop,
                "endX": 129.06,
                "endY": 35.12,
            },
            {"trafficType": 3, "sectionTime": 3, "distance": 100},
        ],
    }
    walk_calls = []

    async def fake_walk(start, end):
        walk_calls.append((start, end))
        return [start, end], "exact", {}

    monkeypatch.setattr(settings, "ODSAY_LOAD_LANE_ENABLED", False)
    monkeypatch.setattr(collector, "_walk_geometry", fake_walk)

    route = asyncio.run(collector._build_candidate(
        path,
        ORIGIN,
        DEST,
    ))

    zero_walk = route.segments[2]
    assert zero_walk["distance_m"] == 0
    assert zero_walk["path"][0] == zero_walk["path"][1]
    assert zero_walk["geometry_quality"] == "exact"
    assert len(walk_calls) == 2


def test_odsay_builds_independent_walk_sections_concurrently(monkeypatch):
    collector = OdsayRouteCollector()
    path = {
        "info": {"totalTime": 20, "totalDistance": 2000},
        "subPath": [
            {"trafficType": 3, "sectionTime": 3, "distance": 100},
            {
                "trafficType": 1,
                "sectionTime": 14,
                "distance": 1800,
                "startX": 129.04,
                "startY": 35.11,
                "endX": 129.06,
                "endY": 35.12,
            },
            {"trafficType": 3, "sectionTime": 3, "distance": 100},
        ],
    }
    both_started = asyncio.Event()
    started = 0

    async def fake_walk(start, end):
        nonlocal started
        started += 1
        if started == 2:
            both_started.set()
        await asyncio.wait_for(both_started.wait(), timeout=0.2)
        return [start, end], "exact", {}

    monkeypatch.setattr(settings, "ODSAY_LOAD_LANE_ENABLED", False)
    monkeypatch.setattr(collector, "_walk_geometry", fake_walk)

    route = asyncio.run(collector._build_candidate(path, ORIGIN, DEST))

    assert started == 2
    assert [segment["mode"] for segment in route.segments] == [
        "walk",
        "subway",
        "walk",
    ]


def test_odsay_deduplicates_same_normalized_walk_section(monkeypatch):
    collector = OdsayRouteCollector(
        avoid_stairs=True,
        uses_wheelchair=True,
    )
    calls = 0

    async def fake_walk(start, end):
        nonlocal calls
        calls += 1
        await asyncio.sleep(0.01)
        return WalkGeometryResult([start, end], "exact", {})

    monkeypatch.setattr(collector, "_walk_geometry", fake_walk)
    nearly_same_origin = Coordinate(
        lat=ORIGIN.lat + 0.000000001,
        lng=ORIGIN.lng + 0.000000001,
    )

    async def run():
        return await asyncio.gather(
            collector._shared_walk_geometry(ORIGIN, DEST),
            collector._shared_walk_geometry(nearly_same_origin, DEST),
        )

    first, second = asyncio.run(run())

    assert calls == 1
    assert first is second


@pytest.mark.parametrize("invalid_info", [None, [], "malformed"])
def test_odsay_skips_invalid_candidate_and_keeps_next_valid_one(
    monkeypatch,
    invalid_info,
):
    import collectors.odsay_collector as module

    invalid = {
        "info": invalid_info,
        "subPath": [{
            "trafficType": 2,
            "sectionTime": 18,
            "distance": 4900,
        }],
    }
    valid = {
        "info": {
            "totalTime": 20,
            "totalDistance": 5000,
            "mapObj": "101:1:1:2",
        },
        "subPath": [{
            "trafficType": 2,
            "sectionTime": 18,
            "distance": 4900,
            "startX": 129.04,
            "startY": 35.115,
            "endX": 129.059,
            "endY": 35.157,
        }],
    }
    search_payload = {"result": {"path": [invalid, valid]}}
    lane_payload = {"result": {"lane": [{"section": [{"graphPos": [
        {"x": 129.04, "y": 35.115},
        {"x": 129.059, "y": 35.157},
    ]}]}]}}

    class Response:
        def __init__(self, payload):
            self.payload = payload

        def raise_for_status(self):
            return None

        def json(self):
            return self.payload

    class Client:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def get(self, url, **kwargs):
            return Response(
                lane_payload if url.endswith("loadLane") else search_payload
            )

    monkeypatch.setattr(settings, "ODSAY_API_KEY", "test-key")
    monkeypatch.setattr(module.httpx, "AsyncClient", Client)

    result = asyncio.run(OdsayRouteCollector().collect(ORIGIN, DEST))

    assert len(result) == 1
    assert result[0].duration_min == 20


@pytest.mark.parametrize("malformed_result", [None, [], "malformed"])
def test_odsay_rejects_non_object_result(monkeypatch, malformed_result):
    import collectors.odsay_collector as module

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"result": malformed_result}

    class Client:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def get(self, *_args, **_kwargs):
            return Response()

    monkeypatch.setattr(settings, "ODSAY_API_KEY", "test-key")
    monkeypatch.setattr(module.httpx, "AsyncClient", Client)

    with pytest.raises(CollectorError, match="result가 객체"):
        asyncio.run(OdsayRouteCollector().collect(ORIGIN, DEST))


@pytest.mark.parametrize(
    ("field", "malformed_value"),
    [
        ("geometry", None),
        ("geometry", []),
        ("geometry", "malformed"),
        ("properties", None),
        ("properties", []),
        ("properties", "malformed"),
    ],
)
def test_tmap_rejects_non_object_nested_fields(
    monkeypatch,
    field,
    malformed_value,
):
    import collectors.tmap_collector as module

    feature = {
        "geometry": {
            "type": "LineString",
            "coordinates": [
                [ORIGIN.lng, ORIGIN.lat],
                [DEST.lng, DEST.lat],
            ],
        },
        "properties": {
            "totalTime": 600,
            "totalDistance": 1000,
        },
    }
    feature[field] = malformed_value

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"features": [feature]}

    class Client:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def post(self, *_args, **_kwargs):
            return Response()

    monkeypatch.setattr(settings, "TMAP_API_KEY", "test-key")
    monkeypatch.setattr(module.httpx, "AsyncClient", Client)

    with pytest.raises(CollectorError, match=field):
        asyncio.run(TmapRouteCollector().collect(ORIGIN, DEST))


def test_odsay_rejects_missing_transit_lane_instead_of_shifting_next_lane():
    collector = OdsayRouteCollector()
    path = {
        "info": {
            "totalTime": 20,
            "totalDistance": 5000,
            "mapObj": "100:1:1:2@101:1:1:2",
        },
        "subPath": [
            {"trafficType": 2, "sectionTime": 8, "distance": 2000},
            {"trafficType": 1, "sectionTime": 10, "distance": 2900},
        ],
    }

    async def run():
        with pytest.raises(CollectorError, match="bus 구간"):
            await collector._build_candidate(
                path,
                ORIGIN,
                DEST,
            )

    asyncio.run(run())


@pytest.mark.parametrize("traffic_type", [True, False])
def test_odsay_rejects_boolean_traffic_type(traffic_type):
    collector = OdsayRouteCollector()
    path = {
        "info": {
            "totalTime": 20,
            "totalDistance": 5000,
            "mapObj": "100:1:1:2",
        },
        "subPath": [{
            "trafficType": traffic_type,
            "sectionTime": 18,
            "distance": 4900,
        }],
    }

    async def run():
        with pytest.raises(CollectorError, match="trafficType"):
            await collector._build_candidate(
                path,
                ORIGIN,
                DEST,
            )

    asyncio.run(run())
