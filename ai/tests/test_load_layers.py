"""데이터 레이어 로딩 테스트."""
import geopandas as gpd
import pytest
from shapely.geometry import Point

import preprocessing.load_layers as load_layers_module
from preprocessing.load_layers import load_all_layers


@pytest.fixture(scope="module")
def layers():
    return load_all_layers(use_cache=False)


def test_all_layers_count(layers):
    """총 12개 레이어가 로딩되어야 한다."""
    assert len(layers) == 12


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


def test_accessibility_destination_layers_preserve_declared_fields(layers):
    mobility = layers["mobility_support_center"]
    welfare = layers["disabled_welfare_facility"]
    tourism = layers["barrier_free_culture_tourism"]

    assert len(mobility) == 1
    assert {"슬로프형차량대수", "리프트형차량대수"}.issubset(mobility.columns)
    # 원본 243건 중 부산 유효 범위 밖 좌표 5건은 원본에 보존하고 지도 레이어에서만 제외한다.
    assert len(welfare) == 238
    assert {"시설유형", "전화번호"}.issubset(welfare.columns)
    assert len(tourism) == 457
    assert {
        "accessible_entrance",
        "wheelchair_rental",
        "accessible_toilet",
        "accessible_parking",
    }.issubset(tourism.columns)


def test_subway_layer_keeps_official_station_external_ramp_counts(layers):
    subway = layers["subway"]

    assert len(subway) == 114
    assert subway["external_ramp_count"].notna().all()
    assert (subway["external_ramp_count"] >= 0).all()
    # 부산교통공사 2025-12-31 원본: 외부경사로 보유 역 15개, 총 25개.
    assert int((subway["external_ramp_count"] > 0).sum()) == 15
    assert int(subway["external_ramp_count"].sum()) == 25


def test_safe_cache_is_reused_and_invalidated_by_source_content(
    monkeypatch,
    tmp_path,
):
    raw_dir = tmp_path / "raw"
    cache_dir = tmp_path / "cache"
    raw_dir.mkdir()
    source = raw_dir / "source.csv"
    source.write_text("v1", encoding="utf-8")
    calls = 0

    def load_sample():
        nonlocal calls
        calls += 1
        return gpd.GeoDataFrame(
            {"version": [calls]},
            geometry=[Point(129.0, 35.1)],
            crs="EPSG:4326",
        )

    monkeypatch.setattr(load_layers_module, "RAW_DIR", raw_dir)
    monkeypatch.setattr(load_layers_module, "CACHE_DIR", cache_dir)
    monkeypatch.setattr(load_layers_module, "SOURCE_FILES", ("source.csv",))
    monkeypatch.setattr(
        load_layers_module,
        "LAYER_LOADERS",
        {"sample": load_sample},
    )

    first = load_layers_module.load_all_layers()
    second = load_layers_module.load_all_layers()
    source.write_text("v2", encoding="utf-8")
    third = load_layers_module.load_all_layers()

    assert first["sample"]["version"].iloc[0] == 1
    assert second["sample"]["version"].iloc[0] == 1
    assert third["sample"]["version"].iloc[0] == 2
    assert calls == 2
    assert (cache_dir / "all_layers.gpkg").is_file()
    assert (cache_dir / "all_layers.manifest.json").is_file()
    assert not (cache_dir / "all_layers.pkl").exists()


def test_csv_missing_file_is_not_hidden_as_encoding_failure(
    monkeypatch,
    tmp_path,
):
    monkeypatch.setattr(load_layers_module, "RAW_DIR", tmp_path)

    with pytest.raises(FileNotFoundError):
        load_layers_module._read_csv("missing.csv")
