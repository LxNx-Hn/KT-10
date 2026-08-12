"""
데이터 레이어 로딩 및 GeoDataFrame 변환 모듈.

데이터팀에서 위경도·부산 필터링·필요 컬럼만 정리된 파일을 제공하므로,
이 모듈은 이상치 좌표 제거와 GeoDataFrame 변환만 담당한다.
"""
import hashlib
import json
from pathlib import Path
import re
from uuid import uuid4

import geopandas as gpd
import pandas as pd
from pyogrio.errors import (
    CRSError,
    DataLayerError,
    DataSourceError,
    FeatureError,
    FieldError,
    GeometryError,
)
from shapely.geometry import Point

REPO_ROOT = Path(__file__).resolve().parents[2]
RAW_DIR   = REPO_ROOT / "data" / "raw"
CACHE_DIR = REPO_ROOT / "ai" / "data" / "cache"
CACHE_SCHEMA_VERSION = "spatial-layer-cache-v2"
CACHE_GPKG_NAME = "all_layers.gpkg"
CACHE_MANIFEST_NAME = "all_layers.manifest.json"

SOURCE_FILES = (
    "부산광역시_무더위_쉼터_20251119.csv",
    "부산광역시_한파_쉼터_현황_20251119.csv",
    "부산광역시_방범용_CCTV_정보_20251229.csv",
    "CCTV정보_부산광역시.csv",
    "부산_AED_위경도_결과.xlsx",
    "부산전동휠체어급속충전기표준데이터.csv",
    "동백전_가맹점_현황.csv",
    "부산광역시_스마트_버스쉘터_설치_현황.csv",
    "busan_subway_station_accessibility_processed.xlsx",
    "busan_subway_station_convenience_20251231.csv",
    "busan_crosswalk_signal_shp_processed.xlsx",
    "bus_stop_national_csv_processed.xlsx",
    "busan_mobility_support_centers.csv",
    "busan_disabled_welfare_facilities.csv",
    "busan_barrier_free_culture_tourism.csv",
)

# 부산 좌표 유효 범위
BUSAN_LAT = (34.8, 35.5)
BUSAN_LNG = (128.7, 129.4)

# 기존 역 접근성 원본은 '역'·'n호선' 표기, 2025 역사 편의시설 원본은
# 'n' 표기를 사용한다. 두 공식 원본의 같은 역을 결합하기 위한 표기 정규화다.
# 아래 세 역은 환승역 중 이전 원본에서 노선 접미사를 생략한 경우이며, 각 역의
# 기본 명칭이 가리키는 노선을 명시한다. 시립미술관역은 현재 벡스코역 명칭으로
# 갱신된 원본과 결합한다.
_STATION_UNSUFFIXED_LINES = {
    "동래": "(1)",
    "수영": "(2)",
    "연산": "(1)",
}
_STATION_NAME_ALIASES = {"시립미술관": "벡스코"}


def _station_join_key(value: object, *, accessibility_source: bool) -> str:
    if not isinstance(value, str):
        raise ValueError("역명은 문자열이어야 합니다.")
    name = value.strip().replace(".", "")
    name = re.sub(r"역(?=\(|$)", "", name)
    name = re.sub(r"\((\d+)호선\)", r"(\1)", name)
    name = _STATION_NAME_ALIASES.get(name, name)
    if accessibility_source and "(" not in name:
        name += _STATION_UNSUFFIXED_LINES.get(name, "")
    # 2025 집계 원본의 동래(4호선)는 접미사 없이 표기되어 있다. 기존
    # 접근성 원본은 동래역(4호선)으로 표기하므로 이 원본에만 적용한다.
    if not accessibility_source and name == "동래":
        name = "동래(4)"
    return name


def _filter_busan(df: pd.DataFrame, lat_col: str = "위도", lng_col: str = "경도") -> pd.DataFrame:
    """부산 범위를 벗어난 좌표를 가진 행을 제거한다."""
    df = df.copy()
    df[lat_col] = pd.to_numeric(df[lat_col], errors="coerce")
    df[lng_col] = pd.to_numeric(df[lng_col], errors="coerce")
    return df[
        df[lat_col].between(*BUSAN_LAT) &
        df[lng_col].between(*BUSAN_LNG)
    ].copy()


def _to_gdf(df: pd.DataFrame, lat_col: str = "위도", lng_col: str = "경도") -> gpd.GeoDataFrame:
    """pandas DataFrame → GeoDataFrame (EPSG:4326)"""
    geometry = [Point(row[lng_col], row[lat_col]) for _, row in df.iterrows()]
    return gpd.GeoDataFrame(df, geometry=geometry, crs="EPSG:4326")


def _read_csv(fname: str) -> pd.DataFrame:
    """인코딩 자동 감지로 CSV 로딩."""
    errors: list[Exception] = []
    for enc in ["utf-8-sig", "cp949", "euc-kr"]:
        try:
            return pd.read_csv(RAW_DIR / fname, encoding=enc)
        except (UnicodeError, pd.errors.ParserError) as exc:
            errors.append(exc)
    attempted = ", ".join(["utf-8-sig", "cp949", "euc-kr"])
    raise ValueError(
        f"CSV 파일을 지원 인코딩으로 읽지 못했습니다: {fname} ({attempted})"
    ) from errors[-1]


# ─────────────────────────────────────────────────────────────
# 레이어별 로딩 함수
# ─────────────────────────────────────────────────────────────

def load_shelter() -> gpd.GeoDataFrame:
    """무더위쉼터 + 한파쉼터 통합 레이어."""
    files = [
        ("부산광역시_무더위_쉼터_20251119.csv", "무더위"),
        ("부산광역시_한파_쉼터_현황_20251119.csv", "한파"),
    ]
    dfs = []
    for fname, stype in files:
        df = _read_csv(fname)
        df["쉼터유형"] = stype
        dfs.append(df[["쉼터명", "위도", "경도", "쉼터유형"]])

    df_all = pd.concat(dfs, ignore_index=True).dropna(subset=["위도", "경도"])
    df_all = _filter_busan(df_all)
    return _to_gdf(df_all)


def load_cctv() -> gpd.GeoDataFrame:
    """
    CCTV 두 파일 병합.
    두 파일은 좌표 기준 중복이 없는 별개 출처이므로 단순 concat 후 이상치만 제거한다.
    """
    rows = []

    # 파일 1: 이지원 (장비종류 컬럼 → 설치목적구분으로 통일)
    df1 = _read_csv("부산광역시_방범용_CCTV_정보_20251229.csv")
    rows.append(
        df1[["위도", "경도"]].assign(설치목적구분=df1["장비종류"], 카메라대수=1)
    )

    # 파일 2: 송정아 (카메라대수 컬럼 있음)
    df2 = _read_csv("CCTV정보_부산광역시.csv")
    rows.append(df2[["위도", "경도", "설치목적구분", "카메라대수"]])

    df_all = pd.concat(rows, ignore_index=True).dropna(subset=["위도", "경도"])
    df_all = _filter_busan(df_all)
    return _to_gdf(df_all)


def load_aed() -> gpd.GeoDataFrame:
    """AED 위치 레이어."""
    df = pd.read_excel(RAW_DIR / "부산_AED_위경도_결과.xlsx")
    df = _filter_busan(df.dropna(subset=["위도", "경도"]))
    return _to_gdf(df[["설치위치", "도로명주소", "위도", "경도"]])


def load_wheelchair_charger() -> gpd.GeoDataFrame:
    """전동휠체어급속충전기 레이어."""
    df = _read_csv("부산전동휠체어급속충전기표준데이터.csv")
    df = _filter_busan(df.dropna(subset=["위도", "경도"]))
    return _to_gdf(
        df[["시설명", "위도", "경도",
            "평일운영시작시각", "평일운영종료시각",
            "공기주입가능여부", "휴대전화충전가능여부"]]
    )


def load_mobility_support_center() -> gpd.GeoDataFrame:
    """교통약자 이동지원센터 위치와 보유 차량 정보 레이어."""
    df = _read_csv("busan_mobility_support_centers.csv")
    df = _filter_busan(df.dropna(subset=["위도", "경도"]))
    return _to_gdf(
        df[[
            "센터명",
            "도로명주소",
            "예약전화번호",
            "보유차량대수",
            "슬로프형차량대수",
            "리프트형차량대수",
            "데이터기준일자",
            "품질상태",
            "위도",
            "경도",
        ]]
    )


def load_disabled_welfare_facility() -> gpd.GeoDataFrame:
    """장애인복지시설 목적지 탐색용 위치·운영 정보 레이어."""
    df = _read_csv("busan_disabled_welfare_facilities.csv")
    df = _filter_busan(df.dropna(subset=["위도", "경도"]))
    return _to_gdf(
        df[[
            "구군명",
            "시설유형",
            "시설명",
            "도로명주소",
            "전화번호",
            "정원",
            "데이터기준일자",
            "위도",
            "경도",
        ]]
    )


def _yes_no_flag(values: pd.Series) -> pd.Series:
    """원본의 Y/N 값만 이진값으로 정규화하고 그 외 값은 결측으로 보존한다."""
    normalized = values.astype("string").str.strip().str.upper()
    return normalized.map({"Y": 1, "N": 0}).astype("Int64")


def load_barrier_free_culture_tourism() -> gpd.GeoDataFrame:
    """배리어프리 문화·관광 목적지와 제공된 편의시설 정보 레이어."""
    df = _read_csv("busan_barrier_free_culture_tourism.csv")
    df = _filter_busan(df.dropna(subset=["위도", "경도"]))
    flags = pd.DataFrame({
        "accessible_entrance": _yes_no_flag(df["장애인용 출입문"]),
        "wheelchair_rental": _yes_no_flag(df["휠체어 대여 가능 여부"]),
        "accessible_toilet": _yes_no_flag(df["장애인 화장실 유무"]),
        "accessible_parking": _yes_no_flag(df["장애인 전용 주차장 여부"]),
        "guide_dog_allowed": _yes_no_flag(df["시각장애인 안내견 동반 가능 여부"]),
        "braille_guide": _yes_no_flag(df["점자 가이드 여부"]),
    }, index=df.index)
    normalized = pd.concat([
        df[[
            "시설명",
            "카테고리1",
            "카테고리2",
            "카테고리3",
            "도로명주소",
            "지번주소",
            "전화번호",
            "운영시간",
            "최종작성일",
            "위도",
            "경도",
        ]],
        flags,
    ], axis=1)
    return _to_gdf(normalized)


def load_dongbaekjeon() -> gpd.GeoDataFrame:
    """동백전 가맹점 레이어."""
    df = _read_csv("동백전_가맹점_현황.csv")
    df = _filter_busan(df.dropna(subset=["위도", "경도"]))
    return _to_gdf(df[["가맹점 명", "주소", "위도", "경도"]])


def load_smart_shelter() -> gpd.GeoDataFrame:
    """스마트버스쉘터 레이어 — 부대시설 파싱 포함."""
    from preprocessing.parse_facilities import parse_facilities

    df = _read_csv("부산광역시_스마트_버스쉘터_설치_현황.csv")
    df = _filter_busan(df.dropna(subset=["위도", "경도"]))
    facility_df = df["부대시설 "].apply(parse_facilities).apply(pd.Series)
    df = pd.concat([df[["정류소명", "위도", "경도"]], facility_df], axis=1)
    return _to_gdf(df)


def load_subway() -> gpd.GeoDataFrame:
    """도시철도 역 접근성 레이어."""
    df = pd.read_excel(RAW_DIR / "busan_subway_station_accessibility_processed.xlsx")
    df = _filter_busan(df.dropna(subset=["위도", "경도"]))
    df["elevator_accessible"] = (df["엘리베이터"] == "O").astype(int)
    convenience = _read_csv("busan_subway_station_convenience_20251231.csv")
    ramp_column = "외부경사로(지상역 출구)"
    if not {"역명", ramp_column}.issubset(convenience.columns):
        raise ValueError("역사 편의시설 원본에 외부경사로 수량 컬럼이 없습니다.")
    ramp_counts = convenience[["역명", ramp_column]].copy()
    ramp_counts["station_join_key"] = ramp_counts["역명"].map(
        lambda value: _station_join_key(value, accessibility_source=False)
    )
    ramp_counts["external_ramp_count"] = pd.to_numeric(
        ramp_counts[ramp_column],
        errors="coerce",
    ).astype("Int64")
    if ramp_counts["external_ramp_count"].isna().any() or (ramp_counts["external_ramp_count"] < 0).any():
        raise ValueError("역사 외부경사로 수량이 비어 있거나 음수입니다.")
    if ramp_counts["station_join_key"].duplicated().any():
        raise ValueError("역사 편의시설 원본에 중복된 결합 역명이 있습니다.")
    df["station_join_key"] = df["역명"].map(
        lambda value: _station_join_key(value, accessibility_source=True)
    )
    if df["station_join_key"].duplicated().any():
        raise ValueError("역 접근성 원본에 중복된 결합 역명이 있습니다.")
    df = df.merge(
        ramp_counts[["station_join_key", "external_ramp_count"]],
        on="station_join_key",
        how="left",
        validate="one_to_one",
    )
    if df["external_ramp_count"].isna().any():
        raise ValueError("역 접근성 원본과 역사 외부경사로 원본의 역명을 모두 결합하지 못했습니다.")
    return _to_gdf(df[[
        "역코드",
        "역명",
        "elevator_accessible",
        "external_ramp_count",
        "위도",
        "경도",
    ]])


def load_crosswalk() -> gpd.GeoDataFrame:
    """횡단보도 신호등 레이어."""
    df = pd.read_excel(RAW_DIR / "busan_crosswalk_signal_shp_processed.xlsx")
    # 위도/경도가 없을 때만 lat/lng를 rename (중복 방지)
    if "위도" not in df.columns or "경도" not in df.columns:
        df = df.rename(columns={"lat": "위도", "lng": "경도"})
    df = _filter_busan(df.dropna(subset=["위도", "경도"]))
    df["has_signal"] = (df["light_yn"] == "유").astype(int)
    return _to_gdf(df[["gugun", "has_signal", "위도", "경도"]])


def load_bus_stop() -> gpd.GeoDataFrame:
    """
    버스정류장 레이어.
    ⚠️ 전국 227,065행 → 반드시 부산만 필터링 후 사용 (약 9,975행).
    """
    df = pd.read_excel(RAW_DIR / "bus_stop_national_csv_processed.xlsx")
    df = df[df["도시명"].str.contains("부산", na=False)]   # 부산 필터링
    df = _filter_busan(df.dropna(subset=["위도", "경도"]))
    return _to_gdf(df[["정류장번호", "정류장명", "위도", "경도"]])


# ─────────────────────────────────────────────────────────────
# 전체 레이어 로딩 (안전한 GeoPackage 캐시 포함)
# ─────────────────────────────────────────────────────────────

LAYER_LOADERS = {
    "shelter": load_shelter,
    "cctv": load_cctv,
    "aed": load_aed,
    "wheelchair_charger": load_wheelchair_charger,
    "mobility_support_center": load_mobility_support_center,
    "disabled_welfare_facility": load_disabled_welfare_facility,
    "barrier_free_culture_tourism": load_barrier_free_culture_tourism,
    "dongbaekjeon": load_dongbaekjeon,
    "smart_shelter": load_smart_shelter,
    "subway": load_subway,
    "crosswalk": load_crosswalk,
    "bus_stop": load_bus_stop,
}


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _source_state() -> list[dict[str, str | int]]:
    state: list[dict[str, str | int]] = []
    for name in SOURCE_FILES:
        path = RAW_DIR / name
        if not path.is_file():
            raise FileNotFoundError(f"공간 레이어 원본 파일이 없습니다: {path}")
        state.append({
            "path": name,
            "bytes": path.stat().st_size,
            "sha256": _file_sha256(path),
        })
    return state


def _validate_layer(
    name: str,
    layer: gpd.GeoDataFrame,
    *,
    expected_count: int | None = None,
) -> None:
    if not isinstance(layer, gpd.GeoDataFrame):
        raise ValueError(f"{name}: GeoDataFrame이 아닙니다.")
    if expected_count is not None and len(layer) != expected_count:
        raise ValueError(
            f"{name}: cache 행 수가 manifest와 다릅니다."
        )
    if layer.empty:
        raise ValueError(f"{name}: 레이어가 비어 있습니다.")
    if layer.crs is None or layer.crs.to_epsg() != 4326:
        raise ValueError(f"{name}: 좌표계가 EPSG:4326이 아닙니다.")
    if layer.geometry.isna().any() or not layer.geometry.is_valid.all():
        raise ValueError(f"{name}: 비어 있거나 유효하지 않은 geometry가 있습니다.")
    if not layer.geometry.geom_type.eq("Point").all():
        raise ValueError(f"{name}: Point가 아닌 geometry가 있습니다.")
    bounds = layer.total_bounds
    if not (
        BUSAN_LNG[0] <= bounds[0] <= bounds[2] <= BUSAN_LNG[1]
        and BUSAN_LAT[0] <= bounds[1] <= bounds[3] <= BUSAN_LAT[1]
    ):
        raise ValueError(f"{name}: 부산 범위를 벗어난 geometry가 있습니다.")


def _load_cache(
    cache_path: Path,
    manifest_path: Path,
    source_state: list[dict[str, str | int]],
) -> dict[str, gpd.GeoDataFrame] | None:
    if not cache_path.is_file() or not manifest_path.is_file():
        return None
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if (
            not isinstance(manifest, dict)
            or manifest.get("cache_schema_version") != CACHE_SCHEMA_VERSION
            or manifest.get("source_state") != source_state
            or manifest.get("cache_sha256") != _file_sha256(cache_path)
        ):
            return None
        layer_manifest = manifest.get("layers")
        if not isinstance(layer_manifest, dict):
            return None
        expected_names = set(LAYER_LOADERS)
        available_names = set(gpd.list_layers(cache_path)["name"])
        if set(layer_manifest) != expected_names or available_names != expected_names:
            return None

        layers: dict[str, gpd.GeoDataFrame] = {}
        for name in LAYER_LOADERS:
            metadata = layer_manifest.get(name)
            if not isinstance(metadata, dict):
                return None
            layer = gpd.read_file(cache_path, layer=name)
            _validate_layer(
                name,
                layer,
                expected_count=metadata.get("rows"),
            )
            layers[name] = layer
        print("캐시에서 공간 레이어를 로딩했습니다.")
        return layers
    except (
        CRSError,
        DataLayerError,
        DataSourceError,
        FeatureError,
        FieldError,
        GeometryError,
        json.JSONDecodeError,
        KeyError,
        OSError,
        TypeError,
        ValueError,
    ) as exc:
        print(f"공간 레이어 캐시를 무시하고 재생성합니다: {type(exc).__name__}")
        return None


def _write_cache(
    layers: dict[str, gpd.GeoDataFrame],
    cache_path: Path,
    manifest_path: Path,
    source_state: list[dict[str, str | int]],
) -> None:
    token = uuid4().hex
    temporary_cache = CACHE_DIR / f".all_layers.{token}.tmp.gpkg"
    temporary_manifest = CACHE_DIR / f".{CACHE_MANIFEST_NAME}.{token}.tmp"
    try:
        for index, (name, layer) in enumerate(layers.items()):
            _validate_layer(name, layer)
            layer.to_file(
                temporary_cache,
                layer=name,
                driver="GPKG",
                mode="w" if index == 0 else "a",
                index=False,
            )
        manifest = {
            "cache_schema_version": CACHE_SCHEMA_VERSION,
            "source_state": source_state,
            "cache_sha256": _file_sha256(temporary_cache),
            "layers": {
                name: {
                    "rows": len(layer),
                    "crs": "EPSG:4326",
                    "geometry_type": "Point",
                }
                for name, layer in layers.items()
            },
        }
        temporary_manifest.write_text(
            json.dumps(
                manifest,
                ensure_ascii=False,
                sort_keys=True,
                indent=2,
            ) + "\n",
            encoding="utf-8",
        )
        temporary_cache.replace(cache_path)
        temporary_manifest.replace(manifest_path)
    finally:
        temporary_cache.unlink(missing_ok=True)
        temporary_manifest.unlink(missing_ok=True)


def load_all_layers(use_cache: bool = True) -> dict:
    """원본 변경을 검증한 GeoPackage cache 또는 원본에서 9개 레이어를 읽는다."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_path = CACHE_DIR / CACHE_GPKG_NAME
    manifest_path = CACHE_DIR / CACHE_MANIFEST_NAME
    source_state = _source_state()

    if use_cache:
        cached = _load_cache(cache_path, manifest_path, source_state)
        if cached is not None:
            return cached

    print("데이터 공간 레이어를 원본에서 로딩합니다.")
    layers = {
        name: loader()
        for name, loader in LAYER_LOADERS.items()
    }
    for name, layer in layers.items():
        _validate_layer(name, layer)
        print(f"  {name}: {len(layer):,}행")

    _write_cache(
        layers,
        cache_path,
        manifest_path,
        source_state,
    )
    print("GeoPackage 공간 레이어 캐시 저장을 완료했습니다.")
    return layers
