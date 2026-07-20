"""90m DEM 경사 계산과 외부 응답 계약 테스트."""
import asyncio

import httpx
import pytest

from features.elevation import calculate_slope_features, extract_elevation_features


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
        assert request.url.params.get("latitude") == "35.115,35.116"
        return httpx.Response(200, json={"elevation": [10.0, 12.0]})

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await extract_elevation_features(
                [(35.115, 129.04), (35.116, 129.04)], client
            )

    result = asyncio.run(run())
    assert result["elevation_status"] == "estimated_90m"
    assert result["elevation_source"].startswith("Copernicus")


def test_elevation_failure_is_explicitly_unavailable():
    async def run():
        transport = httpx.MockTransport(lambda _: httpx.Response(503))
        async with httpx.AsyncClient(transport=transport) as client:
            return await extract_elevation_features([(35.115, 129.04), (35.116, 129.04)], client)

    result = asyncio.run(run())
    assert result["elevation_status"] == "unavailable"
    assert result["avg_slope_percent"] is None
