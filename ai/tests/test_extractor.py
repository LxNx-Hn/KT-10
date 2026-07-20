"""피처 추출 테스트."""
import pytest
import geopandas as gpd
from shapely.geometry import Point
from preprocessing.load_layers import load_all_layers
from features.extractor import extract_route_features, _zero_features


@pytest.fixture(scope="module")
def layers():
    return load_all_layers()


def test_extract_returns_all_keys(layers):
    """추출된 피처 딕셔너리가 모든 키를 포함해야 한다."""
    route = [(35.1578, 129.0594), (35.1626, 129.0530)]
    feats = extract_route_features(route, layers)
    for key in _zero_features():
        assert key in feats, f"피처 키 누락: {key}"


def test_extract_value_types(layers):
    """관측된 피처는 숫자이고 미확인은 None이어야 한다."""
    route = [(35.1578, 129.0594), (35.1626, 129.0530)]
    feats = extract_route_features(route, layers)
    for key, val in feats.items():
        assert val is None or isinstance(val, (int, float)), f"{key}의 타입이 잘못됨: {type(val)}"


def test_extract_value_range(layers):
    """비율 피처(0~1)가 범위를 벗어나지 않아야 한다."""
    route = [(35.1578, 129.0594), (35.1626, 129.0530)]
    feats = extract_route_features(route, layers)
    assert feats["crosswalk_signal_ratio"] is None or 0 <= feats["crosswalk_signal_ratio"] <= 1
    assert feats["cctv_density_50m"] is None or feats["cctv_density_50m"] >= 0


def test_extract_empty_route(layers):
    """좌표가 없으면 모든 피처가 미확인이어야 한다."""
    feats = extract_route_features([], layers)
    assert feats == _zero_features()


def test_buffer_is_measured_in_meters():
    """경로에서 약 30m 지점은 포함하고 약 300m 지점은 50m 버퍼에서 제외한다."""
    route = [(35.1150, 129.0400), (35.1160, 129.0400)]
    cctv = gpd.GeoDataFrame(
        {"name": ["near", "far"]},
        geometry=[Point(129.0403, 35.1155), Point(129.0433, 35.1155)],
        crs="EPSG:4326",
    )
    feats = extract_route_features(route, {"cctv": cctv})
    assert feats["cctv_density_50m"] is not None
    assert 8 < feats["cctv_density_50m"] < 10
