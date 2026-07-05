"""데이터 레이어 로딩 테스트."""
import pytest
from preprocessing.load_layers import load_all_layers


@pytest.fixture(scope="module")
def layers():
    return load_all_layers(use_cache=False)


def test_all_layers_count(layers):
    """총 9개 레이어가 로딩되어야 한다."""
    assert len(layers) == 9


def test_all_layers_nonempty(layers):
    """모든 레이어는 최소 1행 이상이어야 한다."""
    for name, gdf in layers.items():
        assert len(gdf) > 0, f"{name} 레이어가 비어있음"


def test_busan_range(layers):
    """모든 레이어의 좌표가 부산 범위 안에 있어야 한다."""
    for name, gdf in layers.items():
        lats = gdf.geometry.y
        lngs = gdf.geometry.x
        assert lats.between(34.8, 35.5).all(), f"{name}: 부산 범위 벗어난 위도 존재"
        assert lngs.between(128.7, 129.4).all(), f"{name}: 부산 범위 벗어난 경도 존재"


def test_bus_stop_busan_only(layers):
    """버스정류장 레이어는 전국 데이터 필터링이 완료된 상태여야 한다 (약 10,000행 이하)."""
    assert len(layers["bus_stop"]) < 15000, "버스정류장 부산 필터링이 안 된 것으로 보임"


def test_cctv_merged(layers):
    """CCTV 두 파일 병합 후 30,000행 이상이어야 한다."""
    assert len(layers["cctv"]) > 30000, f"CCTV 병합 결과 부족: {len(layers['cctv'])}행"
