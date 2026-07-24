"""90m DEM 경사 계산과 외부 응답 계약 테스트."""
import asyncio

import httpx
import math
import pytest

from config import settings
from features.elevation import (
    _sample,
    calculate_slope_features,
    calculate_slope_features_for_parts,
    extract_elevation_features,
    extract_elevation_features_for_parts,
)


def test_calculate_uphill_and_downhill_features():
    coords = [(35.1150, 129.0400), (35.1159, 129.0400), (35.1168, 129.0400)]
    result = calculate_slope_features(coords, [10.0, 15.0, 12.0])
    assert result["elevation_status"] == "estimated_90m"
    assert result["elevation_gain_m"] == 5.0
    assert result["elevation_loss_m"] == 3.0
    assert result["max_slope_percent"] == pytest.approx(5.0, abs=0.1)
    assert result["min_slope_percent"] == pytest.approx(-3.0, abs=0.1)


def test_extract_elevation_contract_with_mock_transport():
    def handler(request: httpx.Request) -> httpx.Response:
        latitudes = request.url.params.get("latitude", "").split(",")
        assert latitudes[0] == "35.115"
        assert latitudes[-1] == "35.116"
        assert len(latitudes) == 3
        return httpx.Response(200, json={"elevation": [10.0, 11.0, 12.0]})

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await extract_elevation_features(
                [(35.115, 129.04), (35.116, 129.04)], client
            )

    result = asyncio.run(run())
    assert result["elevation_status"] == "estimated_90m"
    assert result["elevation_source"].startswith("Copernicus")


def test_elevation_cache_avoids_repeated_provider_call(monkeypatch, tmp_path):
    requests = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal requests
        requests += 1
        return httpx.Response(200, json={"elevation": [10.0, 11.0, 12.0]})

    monkeypatch.setattr(settings, "ELEVATION_CACHE_DIR", str(tmp_path))
    monkeypatch.setattr(settings, "ELEVATION_CACHE_TTL_SECONDS", 3600)

    async def run():
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(handler)
        ) as client:
            first = await extract_elevation_features(
                [(35.115, 129.04), (35.116, 129.04)],
                client,
            )
            second = await extract_elevation_features(
                [(35.115, 129.04), (35.116, 129.04)],
                client,
            )
            return first, second

    first, second = asyncio.run(run())

    assert requests == 1
    assert second == first
    assert next(tmp_path.glob("*.json")).is_file()


def test_elevation_failure_is_explicitly_unavailable():
    async def run():
        transport = httpx.MockTransport(lambda _: httpx.Response(503))
        async with httpx.AsyncClient(transport=transport) as client:
            return await extract_elevation_features([(35.115, 129.04), (35.116, 129.04)], client)

    result = asyncio.run(run())
    assert result["elevation_status"] == "unavailable"
    assert result["avg_slope_percent"] is None


@pytest.mark.parametrize("payload", [None, [], "malformed"])
def test_non_object_open_meteo_response_is_explicitly_unavailable(payload):
    async def run():
        transport = httpx.MockTransport(
            lambda _: httpx.Response(200, json=payload)
        )
        async with httpx.AsyncClient(transport=transport) as client:
            return await extract_elevation_features(
                [(35.115, 129.04), (35.116, 129.04)],
                client,
            )

    result = asyncio.run(run())

    assert result["elevation_status"] == "unavailable"
    assert result["avg_slope_percent"] is None


def test_sparse_long_geometry_is_sampled_by_distance():
    sampled = _sample([(35.0, 129.0), (35.01, 129.0)])

    assert len(sampled) > 2
    assert sampled[0] == (35.0, 129.0)
    assert sampled[-1] == (35.01, 129.0)


def test_non_finite_elevation_is_rejected_instead_of_leaking_nan():
    result = calculate_slope_features(
        [(35.0, 129.0), (35.001, 129.0)],
        [10.0, math.nan],
    )

    assert result["elevation_status"] == "invalid"
    assert result["avg_slope_percent"] is None


def test_average_slope_is_weighted_by_travel_distance():
    # 첫 구간 약 10배 길고 1%, 둘째 구간은 약 10% 경사다.
    coords = [(35.0, 129.0), (35.01, 129.0), (35.011, 129.0)]
    first_distance_m = 1111.95
    second_distance_m = 111.20
    elevations = [0.0, first_distance_m * 0.01, first_distance_m * 0.01 + second_distance_m * 0.10]

    result = calculate_slope_features(coords, elevations)

    assert result["avg_slope_percent"] == pytest.approx(1.82, abs=0.1)


def test_disconnected_parts_do_not_create_artificial_elevation_gain():
    parts = [
        [(35.0000, 129.0000), (35.0004, 129.0000)],
        [(35.0100, 129.0000), (35.0104, 129.0000)],
    ]

    result = calculate_slope_features_for_parts(
        parts,
        [[10.0, 10.0], [100.0, 100.0]],
    )

    assert result["elevation_status"] == "estimated_90m"
    assert result["avg_slope_percent"] == 0
    assert result["elevation_gain_m"] == 0
    assert result["elevation_loss_m"] == 0


def test_extract_elevation_parts_preserves_boundaries_in_one_api_batch():
    requests = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal requests
        requests += 1
        latitudes = request.url.params.get("latitude", "").split(",")
        assert len(latitudes) == 4
        return httpx.Response(
            200,
            json={"elevation": [10.0, 10.0, 100.0, 100.0]},
        )

    async def run():
        parts = [
            [(35.0000, 129.0000), (35.0004, 129.0000)],
            [(35.0100, 129.0000), (35.0104, 129.0000)],
        ]
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(handler)
        ) as client:
            return await extract_elevation_features_for_parts(parts, client)

    result = asyncio.run(run())

    assert requests == 1
    assert result["elevation_gain_m"] == 0
    assert result["max_slope_percent"] == 0
