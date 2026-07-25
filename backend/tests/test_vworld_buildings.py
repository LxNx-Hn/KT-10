import asyncio
from datetime import datetime
from zoneinfo import ZoneInfo

import httpx
import pytest

from app.data.routes import demo_candidates
from app.models import LatLng
from app.providers.vworld_buildings import (
    _building_rows,
    _path_query_boxes,
    get_vworld_buildings,
)
from app.settings import settings
from app.shade import calculate_shade

KST = ZoneInfo("Asia/Seoul")


def _exact_route():
    route = demo_candidates()[0].model_copy(deep=True)
    points = [
        LatLng(lat=35.1600, lng=129.0500),
        LatLng(lat=35.1610, lng=129.0510),
        LatLng(lat=35.1620, lng=129.0520),
        LatLng(lat=35.1630, lng=129.0530),
    ]
    route.path = points
    route.geometry_quality = "exact"
    for index, segment in enumerate(route.segments):
        segment.path = points[index:index + 2]
        segment.geometry_quality = "exact"
    return route


def _feature_collection() -> dict:
    return {
        "response": {
            "status": "OK",
            "record": {"total": "2"},
            "result": {
                "featureCollection": {
                    "features": [
                        {
                            "id": "first",
                            "properties": {"ufid": "bld-1", "height": "12.5"},
                            "geometry": {
                                "type": "Polygon",
                                "coordinates": [[
                                    [129.05, 35.16],
                                    [129.0501, 35.16],
                                    [129.0501, 35.1601],
                                    [129.05, 35.1601],
                                    [129.05, 35.16],
                                ]],
                            },
                        },
                        {
                            "id": "second",
                            "properties": {"ufid": "bld-2", "height": "0"},
                            "geometry": {
                                "type": "MultiPolygon",
                                "coordinates": [[[
                                    [129.051, 35.161],
                                    [129.0511, 35.161],
                                    [129.0511, 35.1611],
                                    [129.051, 35.1611],
                                    [129.051, 35.161],
                                ]]],
                            },
                        },
                    ],
                },
            },
        },
    }


def test_vworld_provider_keeps_unknown_height_as_none_and_reuses_cache(
    monkeypatch,
    tmp_path,
):
    monkeypatch.setattr(settings, "vworld_api_key", "test-secret")
    monkeypatch.setattr(settings, "vworld_api_domain", "http://localhost:8002")
    monkeypatch.setattr(settings, "vworld_cache_dir", str(tmp_path))
    seen_request: httpx.Request | None = None
    request_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal request_count, seen_request
        request_count += 1
        seen_request = request
        return httpx.Response(200, json=_feature_collection())

    result = asyncio.run(
        get_vworld_buildings(
            [_exact_route()],
            transport=httpx.MockTransport(handler),
        )
    )
    first_request_count = request_count
    cached_result = asyncio.run(
        get_vworld_buildings(
            [_exact_route()],
            transport=httpx.MockTransport(handler),
        )
    )

    assert result["dataQuality"] == "public"
    assert result["cacheComplete"] is True
    assert cached_result == result
    assert request_count == first_request_count
    assert result["featureCount"] == 2
    assert result["buildings"][0]["heightM"] == 12.5
    assert result["buildings"][1]["heightM"] is None
    assert result["buildings"][0]["buildingId"] == "bld-1"
    assert seen_request is not None
    assert seen_request.url.params["data"] == "LT_C_BLDGINFO"
    assert seen_request.url.params["geometry"] == "true"
    assert seen_request.url.params["domain"] == "http://localhost:8002"


def test_vworld_provider_keeps_impossible_height_unknown():
    features = _feature_collection()["response"]["result"][
        "featureCollection"
    ]["features"]
    features[0]["properties"]["height"] = "19860821"

    buildings = _building_rows(features)

    assert buildings[0]["heightM"] is None


def test_vworld_http_error_does_not_expose_api_key(monkeypatch):
    secret = "must-not-appear"
    monkeypatch.setattr(settings, "vworld_api_key", secret)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, request=request)

    with pytest.raises(RuntimeError) as captured:
        asyncio.run(
            get_vworld_buildings(
                [_exact_route()],
                transport=httpx.MockTransport(handler),
            )
        )
    assert "HTTP 401" in str(captured.value)
    assert secret not in str(captured.value)


def test_vworld_provider_requires_key(monkeypatch):
    monkeypatch.setattr(settings, "vworld_api_key", "")
    with pytest.raises(RuntimeError, match="VWORLD_API_KEY"):
        asyncio.run(get_vworld_buildings([_exact_route()]))


def test_vworld_cache_only_does_not_schedule_or_download(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "vworld_api_key", "test-secret")
    monkeypatch.setattr(settings, "vworld_cache_dir", str(tmp_path))

    def fail_if_scheduled(*_args, **_kwargs):
        raise AssertionError("캐시 전용 조회에서 외부 보충 작업을 예약하면 안 됩니다.")

    monkeypatch.setattr(
        "app.providers.vworld_buildings._schedule_query_box_warm",
        fail_if_scheduled,
    )

    result = asyncio.run(
        get_vworld_buildings([_exact_route()], cache_only=True)
    )

    assert result["cacheComplete"] is False
    assert result["featureCount"] == 0
    assert result["buildings"] == []


def test_vworld_provider_rejects_invalid_total_count(monkeypatch):
    monkeypatch.setattr(settings, "vworld_api_key", "test-secret")
    payload = _feature_collection()
    payload["response"]["record"]["total"] = "not-a-number"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, request=request, json=payload)

    with pytest.raises(RuntimeError, match="전체 건수"):
        asyncio.run(
            get_vworld_buildings(
                [_exact_route()],
                transport=httpx.MockTransport(handler),
            )
        )


def test_vworld_provider_rejects_early_pagination_end(monkeypatch):
    monkeypatch.setattr(settings, "vworld_api_key", "test-secret")
    first = _feature_collection()
    first["response"]["record"]["total"] = "3"

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.params["page"] == "1":
            return httpx.Response(200, request=request, json=first)
        return httpx.Response(
            200,
            request=request,
            json={
                "response": {
                    "status": "OK",
                    "record": {"total": "3"},
                    "result": {
                        "featureCollection": {"features": []}
                    },
                }
            },
        )

    with pytest.raises(RuntimeError, match="먼저 종료"):
        asyncio.run(
            get_vworld_buildings(
                [_exact_route()],
                transport=httpx.MockTransport(handler),
            )
        )


def test_vworld_provider_rejects_duplicate_feature_across_pages(monkeypatch):
    monkeypatch.setattr(settings, "vworld_api_key", "test-secret")
    first = _feature_collection()
    first_features = first["response"]["result"]["featureCollection"]["features"]
    first["response"]["record"]["total"] = "2"
    first["response"]["result"]["featureCollection"]["features"] = [
        first_features[0]
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, request=request, json=first)

    with pytest.raises(RuntimeError, match="중복 feature ID"):
        asyncio.run(
            get_vworld_buildings(
                [_exact_route()],
                transport=httpx.MockTransport(handler),
            )
        )


def test_long_walk_is_split_into_local_corridor_boxes():
    boxes = _path_query_boxes([
        LatLng(lat=35.1000, lng=129.0000),
        LatLng(lat=35.1500, lng=129.0000),
    ])

    assert len(boxes) > 5
    assert all(max_lat - min_lat < 0.01 for _, min_lat, _, max_lat in boxes)


def test_public_shade_reports_height_coverage_without_zero_fill():
    buildings = {
        "source": "VWorld LT_C_BLDGINFO WFS",
        "dataQuality": "public",
        "buildings": [
            {
                "id": "known",
                "heightM": 15.0,
                "footprint": [
                    {"lat": 35.1792, "lng": 129.0752},
                    {"lat": 35.1792, "lng": 129.0754},
                    {"lat": 35.1794, "lng": 129.0754},
                    {"lat": 35.1794, "lng": 129.0752},
                    {"lat": 35.1792, "lng": 129.0752},
                ],
            },
            {
                "id": "unknown",
                "heightM": None,
                "footprint": [
                    {"lat": 35.1795, "lng": 129.0755},
                    {"lat": 35.1795, "lng": 129.0756},
                    {"lat": 35.1796, "lng": 129.0756},
                    {"lat": 35.1796, "lng": 129.0755},
                    {"lat": 35.1795, "lng": 129.0755},
                ],
            },
        ],
    }
    shade = calculate_shade(
        _exact_route(),
        datetime(2026, 7, 23, 14, 0, tzinfo=KST),
        buildings,
    )
    assert shade.status == "estimated_public"
    assert shade.data_quality == "public"
    assert shade.building_height_coverage == 0.5
    assert shade.estimate_kind == "lower_bound"
    assert shade.known_height_building_count == 1
    assert shade.building_count == 2
    assert shade.includes_tree_shade is False
    assert shade.shadow_polygons


def test_public_shade_rejects_impossible_height_without_zero_fill():
    buildings = {
        "source": "VWorld LT_C_BLDGINFO WFS",
        "dataQuality": "public",
        "buildings": [{
            "id": "outlier",
            "heightM": 19_860_821,
            "footprint": [
                {"lat": 35.1792, "lng": 129.0752},
                {"lat": 35.1792, "lng": 129.0754},
                {"lat": 35.1794, "lng": 129.0754},
                {"lat": 35.1794, "lng": 129.0752},
                {"lat": 35.1792, "lng": 129.0752},
            ],
        }],
    }

    shade = calculate_shade(
        _exact_route(),
        datetime(2026, 7, 23, 14, 0, tzinfo=KST),
        buildings,
    )

    assert shade.status == "unavailable"
    assert shade.building_height_coverage == 0
    assert shade.known_height_building_count == 0
    assert shade.building_count == 1
    assert shade.shade_ratio is None


def test_public_shade_does_not_use_estimated_straight_walk_geometry():
    route = _exact_route()
    route.geometry_quality = "estimated"
    for segment in route.segments:
        segment.geometry_quality = "estimated"
    shade = calculate_shade(
        route,
        datetime(2026, 7, 23, 14, 0, tzinfo=KST),
        {
            "source": "VWorld LT_C_BLDGINFO WFS",
            "dataQuality": "public",
            "buildings": [],
        },
    )

    assert shade.status == "unavailable"
    assert shade.shade_ratio is None
    assert "실제 도로 geometry" in shade.calculation_note


def test_public_shade_waits_for_complete_building_corridor_cache():
    shade = calculate_shade(
        _exact_route(),
        datetime(2026, 7, 23, 14, 0, tzinfo=KST),
        {
            "source": "VWorld LT_C_BLDGINFO WFS",
            "dataQuality": "public",
            "cacheComplete": False,
            "buildings": [],
        },
    )

    assert shade.status == "unavailable"
    assert shade.shade_ratio is None
    assert "사전계산 중" in shade.calculation_note


def test_public_transit_route_without_walking_geometry_is_unavailable():
    buildings = {
        "source": "VWorld LT_C_BLDGINFO WFS",
        "dataQuality": "public",
        "buildings": [{
            "id": "known",
            "heightM": 15.0,
            "footprint": [
                {"lat": 35.16, "lng": 129.05},
                {"lat": 35.16, "lng": 129.051},
                {"lat": 35.161, "lng": 129.051},
                {"lat": 35.161, "lng": 129.05},
                {"lat": 35.16, "lng": 129.05},
            ],
        }],
    }
    shade = calculate_shade(
        demo_candidates()[1],
        datetime(2026, 7, 23, 14, 0, tzinfo=KST),
        buildings,
    )
    assert shade.status == "unavailable"
    assert "실외 도보 구간" in shade.calculation_note
