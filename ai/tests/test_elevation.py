"""90m DEM 경사 계산과 외부 응답 계약 테스트."""
import asyncio
import math
from pathlib import Path

import httpx
import numpy as np
import pytest
import rasterio
import features.elevation as elevation_module
from config import settings
from features.elevation import (
    LOCAL_DEM_SOURCE,
    REGIONAL_DEM_SOURCE,
    _dem_tile_id,
    _haversine_m,
    _sample,
    calculate_slope_features,
    calculate_slope_features_for_parts,
    extract_elevation_features,
    extract_elevation_features_for_parts,
    prepare_regional_dem,
)
from rasterio.transform import from_origin
from rasterio.warp import transform as transform_coordinates


@pytest.fixture(autouse=True)
def isolate_regional_dem(monkeypatch, tmp_path):
    missing_regional_dem = tmp_path / "missing-regional-dem.tif"
    monkeypatch.setattr(
        settings,
        "ELEVATION_REGIONAL_DEM_PATH",
        str(missing_regional_dem),
    )
    # 운영 Compose가 지역 DEM 경로를 주입하므로, 공급자 모의 테스트는
    # 설정값뿐 아니라 경로 해석 자체를 격리한다.
    monkeypatch.setattr(
        elevation_module,
        "_regional_dem_path",
        lambda: missing_regional_dem,
    )
    monkeypatch.setattr(settings, "ELEVATION_DEM_DIR", "")
    monkeypatch.setattr(settings, "ELEVATION_CACHE_DIR", "")
    monkeypatch.setattr(elevation_module, "_regional_dem", None)
    yield
    elevation_module._regional_dem = None


def test_bundled_qgis_regional_dem_avoids_remote_provider(monkeypatch, tmp_path):
    regional_path = (
        Path(__file__).resolve().parents[1]
        / "data"
        / "precomputed"
        / "busan_dem_clipped_90m.tif"
    )
    monkeypatch.setattr(
        settings,
        "ELEVATION_REGIONAL_DEM_PATH",
        str(regional_path),
    )
    monkeypatch.setattr(
        elevation_module,
        "_regional_dem_path",
        lambda: regional_path,
    )
    monkeypatch.setattr(settings, "ELEVATION_DEM_DIR", "")
    monkeypatch.setattr(settings, "ELEVATION_CACHE_DIR", str(tmp_path / "cache"))

    def handler(_request: httpx.Request) -> httpx.Response:
        raise AssertionError("부산 QGIS DEM 범위에서는 원격 고도 API를 호출하면 안 됩니다.")

    async def run():
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(handler)
        ) as client:
            return await extract_elevation_features(
                [(35.115, 129.04), (35.116, 129.04)],
                client,
            )

    result = asyncio.run(run())

    assert prepare_regional_dem() == {
        "path": str(regional_path),
        "width": 546,
        "height": 627,
        "resolution_m": 90,
    }
    assert result["elevation_status"] == "estimated_90m"
    assert result["elevation_source"] == REGIONAL_DEM_SOURCE


def test_copernicus_tile_id_uses_southwest_degree():
    assert (
        _dem_tile_id(35.1796, 129.0756)
        == "Copernicus_DSM_COG_30_N35_00_E129_00_DEM"
    )


def test_local_dem_avoids_remote_provider(monkeypatch, tmp_path):
    dem_dir = tmp_path / "dem"
    dem_dir.mkdir()
    tile_id = _dem_tile_id(35.1, 129.1)
    tile_path = dem_dir / f"{tile_id}.tif"
    terrain = np.repeat(
        np.arange(100, dtype=np.float32)[:, np.newaxis],
        100,
        axis=1,
    )
    with rasterio.open(
        tile_path,
        "w",
        driver="GTiff",
        height=100,
        width=100,
        count=1,
        dtype="float32",
        crs="EPSG:4326",
        transform=from_origin(129.0, 36.0, 0.01, 0.01),
        nodata=-9999,
    ) as dataset:
        dataset.write(terrain, 1)

    monkeypatch.setattr(settings, "ELEVATION_DEM_DIR", str(dem_dir))
    monkeypatch.setattr(settings, "ELEVATION_CACHE_DIR", str(tmp_path / "cache"))

    def handler(_request: httpx.Request) -> httpx.Response:
        raise AssertionError("로컬 DEM이 있으면 원격 고도 API를 호출하면 안 됩니다.")

    async def run():
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(handler)
        ) as client:
            return await extract_elevation_features(
                [(35.10, 129.10), (35.11, 129.10)],
                client,
            )

    result = asyncio.run(run())

    assert result["elevation_status"] == "estimated_90m"
    assert result["elevation_source"] == LOCAL_DEM_SOURCE
    assert result["avg_slope_percent"] is not None


def test_calculate_uphill_and_downhill_features():
    coords = [(35.1150, 129.0400), (35.1159, 129.0400), (35.1168, 129.0400)]
    result = calculate_slope_features(coords, [10.0, 15.0, 12.0])
    assert result["elevation_status"] == "estimated_90m"
    assert result["elevation_gain_m"] == 5.0
    assert result["elevation_loss_m"] == 3.0
    assert result["max_slope_percent"] == pytest.approx(5.0, abs=0.1)
    assert result["min_slope_percent"] == pytest.approx(-3.0, abs=0.1)
    assert len(result["slope_segments"]) == 2
    assert result["slope_segments"][0]["start"] == {
        "lat": coords[0][0],
        "lng": coords[0][1],
    }
    assert result["slope_segments"][0]["slope_percent"] == pytest.approx(
        5.0, abs=0.1
    )


def test_extract_elevation_contract_with_mock_transport(monkeypatch):
    monkeypatch.setattr(
        settings, "ELEVATION_NETWORK_FALLBACK_ENABLED", True
    )

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
    monkeypatch.setattr(
        settings, "ELEVATION_NETWORK_FALLBACK_ENABLED", True
    )
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


def test_fifteen_km_geometry_keeps_ninety_meter_sampling():
    sampled = _sample([(35.0, 129.0), (35.1349, 129.0)])

    assert len(sampled) > 100
    assert max(
        _haversine_m(start, end)
        for start, end in zip(sampled, sampled[1:])
    ) <= 90.1


def test_fifteen_km_elevation_is_split_into_provider_batches(
    monkeypatch,
    tmp_path,
):
    batch_sizes = []

    def handler(request: httpx.Request) -> httpx.Response:
        batch_size = len(request.url.params.get("latitude", "").split(","))
        batch_sizes.append(batch_size)
        return httpx.Response(200, json={"elevation": [10.0] * batch_size})

    monkeypatch.setattr(settings, "ELEVATION_DEM_DIR", "")
    monkeypatch.setattr(settings, "ELEVATION_CACHE_DIR", str(tmp_path))
    monkeypatch.setattr(
        settings, "ELEVATION_NETWORK_FALLBACK_ENABLED", True
    )

    async def run():
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(handler)
        ) as client:
            return await extract_elevation_features(
                [(35.0, 129.0), (35.1349, 129.0)],
                client,
            )

    result = asyncio.run(run())

    assert batch_sizes == [100, len(result["slope_segments"]) + 1 - 100]
    assert len(result["slope_segments"]) > 100
    assert max(
        segment["distance_m"]
        for segment in result["slope_segments"]
    ) <= 90.1


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
    assert len(result["slope_segments"]) == 2
    assert all(
        segment["distance_m"] < 100
        for segment in result["slope_segments"]
    )


def test_extract_elevation_parts_preserves_boundaries_in_one_api_batch(
    monkeypatch,
):
    monkeypatch.setattr(
        settings, "ELEVATION_NETWORK_FALLBACK_ENABLED", True
    )
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


def _corner_walk_parts():
    """직각으로 꺾이는 실제 보행로 모양의 두 part."""

    def densify(waypoints, steps=20):
        points = [waypoints[0]]
        for start, end in zip(waypoints, waypoints[1:]):
            for index in range(1, steps + 1):
                ratio = index / steps
                points.append((
                    start[0] + (end[0] - start[0]) * ratio,
                    start[1] + (end[1] - start[1]) * ratio,
                ))
        return points

    first = densify([
        (35.1000, 129.0000),
        (35.1000, 129.0060),
        (35.1040, 129.0060),
    ])
    second = densify([
        (35.1200, 129.0000),
        (35.1240, 129.0000),
        (35.1240, 129.0050),
    ])
    return [first, second]


def test_slope_segment_path_follows_original_walk_geometry(monkeypatch):
    """경사 구간 표시 경로는 표본 직선이 아니라 원본 정점을 따라간다.

    90m 표본만 이으면 그 사이의 코너가 잘려 실제 보행로를 벗어난 선이
    그려지므로, 지도에 그릴 경로는 원본 polyline의 부분경로여야 한다.
    """
    monkeypatch.setattr(settings, "ELEVATION_NETWORK_FALLBACK_ENABLED", True)
    monkeypatch.setattr(settings, "ELEVATION_CACHE_DIR", "")
    parts = _corner_walk_parts()

    def handler(request: httpx.Request) -> httpx.Response:
        count = len(request.url.params.get("latitude", "").split(","))
        return httpx.Response(
            200, json={"elevation": [float(index) for index in range(count)]}
        )

    async def run():
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(handler)
        ) as client:
            return await extract_elevation_features_for_parts(parts, client)

    result = asyncio.run(run())

    assert result["elevation_status"] == "estimated_90m"
    segments = result["slope_segments"]
    assert segments

    part_vertices = [set(part) for part in parts]
    for segment in segments:
        path = segment["path"]
        assert len(path) >= 2
        # 표시 경로의 양 끝은 경사를 계산한 표본과 정확히 같아야 한다.
        assert path[0] == segment["start"]
        assert path[-1] == segment["end"]
        # 표시 경로의 모든 정점은 원본 보행 part 하나 안에 있어야 한다.
        # 서로 끊어진 part를 잇는 가짜 선을 만들지 않는다.
        assert any(
            all(
                (point["lat"], point["lng"]) in vertices
                or point in (segment["start"], segment["end"])
                for point in path
            )
            for vertices in part_vertices
        )

    # 코너 정점이 실제로 살아 있어야 한다. 표본 직선이면 3점 이상 나오지 않는다.
    assert any(len(segment["path"]) > 2 for segment in segments)


def test_slope_segment_path_does_not_change_slope_metrics(monkeypatch):
    """표시 경로를 추가해도 경사·고도 수치 계약은 그대로다."""
    monkeypatch.setattr(settings, "ELEVATION_NETWORK_FALLBACK_ENABLED", True)
    monkeypatch.setattr(settings, "ELEVATION_CACHE_DIR", "")
    parts = _corner_walk_parts()

    def handler(request: httpx.Request) -> httpx.Response:
        count = len(request.url.params.get("latitude", "").split(","))
        return httpx.Response(
            200, json={"elevation": [float(index) for index in range(count)]}
        )

    async def run():
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(handler)
        ) as client:
            return await extract_elevation_features_for_parts(parts, client)

    result = asyncio.run(run())
    sampled = [_sample(part) for part in parts]
    offset = 0
    elevations = []
    for part in sampled:
        elevations.append([float(offset + index) for index in range(len(part))])
        offset += len(part)
    baseline = calculate_slope_features_for_parts(sampled, elevations)

    metrics = (
        "avg_slope_percent",
        "max_slope_percent",
        "min_slope_percent",
        "slope_iqr",
        "uphill_distance_m",
        "downhill_distance_m",
        "elevation_gain_m",
        "elevation_loss_m",
    )
    for key in metrics:
        assert result[key] == baseline[key]
    assert len(result["slope_segments"]) == len(baseline["slope_segments"])
    for enriched, plain in zip(
        result["slope_segments"], baseline["slope_segments"]
    ):
        assert enriched["start"] == plain["start"]
        assert enriched["end"] == plain["end"]
        assert enriched["slope_percent"] == plain["slope_percent"]
        assert enriched["distance_m"] == plain["distance_m"]
    # 표시 경로 없이 계산한 결과에는 path를 만들어 넣지 않는다.
    assert all("path" not in segment for segment in baseline["slope_segments"])


def test_live_default_makes_no_elevation_network_fallback(monkeypatch, tmp_path):
    """지역 DEM이 응답하지 못해도 기본 설정에서는 network fallback이 없다."""
    monkeypatch.setattr(settings, "ELEVATION_DEM_DIR", str(tmp_path / "dem"))
    monkeypatch.setattr(settings, "ELEVATION_CACHE_DIR", "")

    def handler(_request: httpx.Request) -> httpx.Response:
        raise AssertionError(
            "운영 기본 설정에서는 고도 network fallback을 호출하면 안 됩니다."
        )

    async def run():
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(handler)
        ) as client:
            return await extract_elevation_features(
                [(35.115, 129.04), (35.116, 129.04)], client
            )

    result = asyncio.run(run())

    # 누락 고도를 0이나 합성값으로 채우지 않고 미확인으로 명시한다.
    assert result["elevation_status"] == "unavailable"
    assert result["avg_slope_percent"] is None
    assert result["slope_segments"] == []


# --- 해안 인접 구간 경사 미확인 문제 (docs/reports/2026-08-14-coastal-elevation-gap) ---

def _write_synthetic_regional_dem(path, values, nodata=-9999.0):
    """EPSG:5179 90m 격자 합성 DEM을 쓰고 transform을 반환한다."""
    transform = from_origin(1_140_000.0, 1_690_000.0, 90, 90)
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        height=values.shape[0],
        width=values.shape[1],
        count=1,
        dtype="float32",
        crs="EPSG:5179",
        transform=transform,
        nodata=nodata,
    ) as dataset:
        dataset.write(values.astype("float32"), 1)
    return transform


def _use_synthetic_dem(monkeypatch, path):
    monkeypatch.setattr(settings, "ELEVATION_REGIONAL_DEM_PATH", str(path))
    monkeypatch.setattr(elevation_module, "_regional_dem_path", lambda: path)
    monkeypatch.setattr(elevation_module, "_regional_dem", None)


def _grid_corner(transform, row, col):
    """픽셀 (row,col)·(row,col+1)·(row+1,col)·(row+1,col+1)이 만나는 점의 WGS84 좌표.

    이 점은 bilinear 가중치가 네 칸 모두 0.25가 되므로 부분 결측 보간을
    결정적으로 검증할 수 있다.
    """
    x, y = transform * (col + 1, row + 1)
    lngs, lats = transform_coordinates("EPSG:5179", "EPSG:4326", [x], [y])
    return lats[0], lngs[0]


def _coastal_dem_values(width, land_columns, height=3):
    """값 = col*3 + row 인 육지와 nodata 바다로 이루어진 격자."""
    values = np.full((height, width), -9999.0)
    for row in range(height):
        for col in land_columns:
            values[row, col] = col * 3 + row
    return values


def test_partially_masked_bilinear_uses_valid_neighbours(monkeypatch, tmp_path):
    """해안 픽셀 이웃이 바다여도 실측 육지 칸만으로 고도를 만든다."""
    values = _coastal_dem_values(6, land_columns=range(4))
    dem = tmp_path / "coastal.tif"
    transform = _write_synthetic_regional_dem(dem, values)
    _use_synthetic_dem(monkeypatch, dem)

    full = _grid_corner(transform, 0, 1)      # cols 1,2 · rows 0,1 → 4칸 유효
    partial = _grid_corner(transform, 0, 3)   # cols 3,4 → col 4가 바다
    empty = _grid_corner(transform, 0, 4)     # cols 4,5 → 전부 바다

    result = elevation_module._regional_dem_elevations([full, partial, empty])

    assert result is not None
    assert result[0] == pytest.approx((3 + 6 + 4 + 7) / 4)
    # 유효한 두 칸(9, 10)만 가중치 재정규화한 값이며 그 범위를 벗어나지 않는다.
    assert result[1] == pytest.approx(9.5)
    assert 9.0 <= result[1] <= 10.0
    # 유효 칸이 하나도 없으면 값을 만들지 않는다.
    assert result[2] is None


def _coastal_route(transform, sample_count):
    """격자 교차점 위를 90m 간격으로 지나는 보행 경로 한 벌."""
    start = _grid_corner(transform, 0, 0)
    end = _grid_corner(transform, 0, sample_count - 1)
    return [start, end]


def _run_parts(route):
    return asyncio.run(extract_elevation_features_for_parts([route]))


def test_coastal_route_survives_when_only_sea_samples_are_missing(
    monkeypatch, tmp_path,
):
    """바다 위 표본만 버리고 육지 표본으로 경사를 계산한다."""
    values = _coastal_dem_values(12, land_columns=range(9))
    dem = tmp_path / "coast-pass.tif"
    transform = _write_synthetic_regional_dem(dem, values)
    _use_synthetic_dem(monkeypatch, dem)

    result = _run_parts(_coastal_route(transform, 10))

    assert result["elevation_status"] == "estimated_90m"
    assert result["elevation_source"] == REGIONAL_DEM_SOURCE
    # 표본 10개 중 마지막 1개만 완전 결측이므로 구간은 8개 남는다.
    assert len(result["slope_segments"]) == 8


def test_coastal_route_below_coverage_threshold_stays_unavailable(
    monkeypatch, tmp_path,
):
    """유효 표본이 기준에 못 미치면 남은 표본으로 경사를 지어내지 않는다."""
    values = _coastal_dem_values(12, land_columns=range(7))
    dem = tmp_path / "coast-sparse.tif"
    transform = _write_synthetic_regional_dem(dem, values)
    _use_synthetic_dem(monkeypatch, dem)

    result = _run_parts(_coastal_route(transform, 10))

    assert result["elevation_status"] == "unavailable"
    assert result["avg_slope_percent"] is None


def test_long_missing_gap_stays_unavailable(monkeypatch, tmp_path):
    """연속 결측이 길면 그 사이 언덕을 숨기므로 미확인으로 둔다."""
    land = list(range(5)) + list(range(8, 14))
    values = _coastal_dem_values(14, land_columns=land)
    dem = tmp_path / "coast-gap.tif"
    transform = _write_synthetic_regional_dem(dem, values)
    _use_synthetic_dem(monkeypatch, dem)

    result = _run_parts(_coastal_route(transform, 12))

    assert result["elevation_status"] == "unavailable"


def test_single_missing_sample_is_within_allowed_gap(monkeypatch, tmp_path):
    """표본 한 개(180m)까지는 버리고 계산한다."""
    land = list(range(6)) + list(range(8, 14))
    values = _coastal_dem_values(14, land_columns=land)
    dem = tmp_path / "coast-one-gap.tif"
    transform = _write_synthetic_regional_dem(dem, values)
    _use_synthetic_dem(monkeypatch, dem)

    result = _run_parts(_coastal_route(transform, 12))

    assert result["elevation_status"] == "estimated_90m"
    # 표본 12개 중 1개를 버려 11개가 남고 구간은 10개다.
    assert len(result["slope_segments"]) == 10


def test_route_entirely_over_water_is_unavailable(monkeypatch, tmp_path):
    """DEM에 실측이 전혀 없는 구간은 계속 미확인이다."""
    values = _coastal_dem_values(12, land_columns=[])
    dem = tmp_path / "all-sea.tif"
    transform = _write_synthetic_regional_dem(dem, values)
    _use_synthetic_dem(monkeypatch, dem)
    monkeypatch.setattr(settings, "ELEVATION_NETWORK_FALLBACK_ENABLED", False)

    result = _run_parts(_coastal_route(transform, 10))

    assert result["elevation_status"] == "unavailable"


def test_dropped_samples_keep_display_path_aligned(monkeypatch, tmp_path):
    """표본을 버리면 표시용 경로도 같은 기준으로 다시 만든다."""
    land = list(range(6)) + list(range(8, 14))
    values = _coastal_dem_values(14, land_columns=land)
    dem = tmp_path / "coast-align.tif"
    transform = _write_synthetic_regional_dem(dem, values)
    _use_synthetic_dem(monkeypatch, dem)

    result = _run_parts(_coastal_route(transform, 12))

    assert result["elevation_status"] == "estimated_90m"
    for segment in result["slope_segments"]:
        path = segment["path"]
        assert path[0]["lat"] == pytest.approx(segment["start"]["lat"])
        assert path[0]["lng"] == pytest.approx(segment["start"]["lng"])
        assert path[-1]["lat"] == pytest.approx(segment["end"]["lat"])
        assert path[-1]["lng"] == pytest.approx(segment["end"]["lng"])


def test_fully_valid_route_result_is_unchanged(monkeypatch, tmp_path):
    """4칸이 모두 유효한 경로는 수정 전과 같은 값을 낸다."""
    values = _coastal_dem_values(14, land_columns=range(14))
    dem = tmp_path / "inland.tif"
    transform = _write_synthetic_regional_dem(dem, values)
    _use_synthetic_dem(monkeypatch, dem)

    result = _run_parts(_coastal_route(transform, 10))

    assert result["elevation_status"] == "estimated_90m"
    assert len(result["slope_segments"]) == 9
    # 열 방향으로 90m마다 3m씩 오르므로 약 3.33% 오르막이 이어진다.
    assert result["avg_slope_percent"] == pytest.approx(3.333, abs=0.05)
    assert result["elevation_loss_m"] == pytest.approx(0.0)
