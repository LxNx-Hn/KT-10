import asyncio
from datetime import datetime
from zoneinfo import ZoneInfo

import httpx
import pytest

from app.data.routes import demo_candidates
from app.providers.vworld_buildings import get_vworld_buildings
from app.settings import settings
from app.shade import calculate_shade

KST = ZoneInfo("Asia/Seoul")


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


def test_vworld_provider_keeps_unknown_height_as_none(monkeypatch):
    monkeypatch.setattr(settings, "vworld_api_key", "test-secret")
    monkeypatch.setattr(settings, "vworld_api_domain", "http://localhost:8002")
    seen_request: httpx.Request | None = None

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal seen_request
        seen_request = request
        return httpx.Response(200, json=_feature_collection())

    result = asyncio.run(
        get_vworld_buildings(
            demo_candidates()[:1],
            transport=httpx.MockTransport(handler),
        )
    )

    assert result["dataQuality"] == "public"
    assert result["featureCount"] == 2
    assert result["buildings"][0]["heightM"] == 12.5
    assert result["buildings"][1]["heightM"] is None
    assert result["buildings"][0]["buildingId"] == "bld-1"
    assert seen_request is not None
    assert seen_request.url.params["data"] == "LT_C_BLDGINFO"
    assert seen_request.url.params["geometry"] == "true"
    assert seen_request.url.params["domain"] == "http://localhost:8002"


def test_vworld_http_error_does_not_expose_api_key(monkeypatch):
    secret = "must-not-appear"
    monkeypatch.setattr(settings, "vworld_api_key", secret)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, request=request)

    with pytest.raises(RuntimeError) as captured:
        asyncio.run(
            get_vworld_buildings(
                demo_candidates()[:1],
                transport=httpx.MockTransport(handler),
            )
        )
    assert "HTTP 401" in str(captured.value)
    assert secret not in str(captured.value)


def test_vworld_provider_requires_key(monkeypatch):
    monkeypatch.setattr(settings, "vworld_api_key", "")
    with pytest.raises(RuntimeError, match="VWORLD_API_KEY"):
        asyncio.run(get_vworld_buildings(demo_candidates()[:1]))


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
        demo_candidates()[0],
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
