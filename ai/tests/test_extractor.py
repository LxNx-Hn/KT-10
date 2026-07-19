"""피처 추출 테스트."""
import pytest
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
    """모든 피처 값이 float 또는 int 타입이어야 한다."""
    route = [(35.1578, 129.0594), (35.1626, 129.0530)]
    feats = extract_route_features(route, layers)
    for key, val in feats.items():
        assert isinstance(val, (int, float)), f"{key}의 타입이 잘못됨: {type(val)}"


def test_extract_value_range(layers):
    """비율 피처(0~1)가 범위를 벗어나지 않아야 한다."""
    route = [(35.1578, 129.0594), (35.1626, 129.0530)]
    feats = extract_route_features(route, layers)
    assert 0 <= feats["crosswalk_signal_ratio"] <= 1
    assert feats["cctv_density_50m"] >= 0


def test_extract_empty_route(layers):
    """좌표가 없으면 모든 피처가 0이어야 한다."""
    feats = extract_route_features([], layers)
    assert feats == _zero_features()
