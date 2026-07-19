"""
데이터 레이어 로딩 및 GeoDataFrame 변환 모듈.

데이터팀에서 위경도·부산 필터링·필요 컬럼만 정리된 파일을 제공하므로,
이 모듈은 이상치 좌표 제거와 GeoDataFrame 변환만 담당한다.
"""
import pickle
import warnings
from pathlib import Path

import geopandas as gpd
import pandas as pd
from shapely.geometry import Point

warnings.filterwarnings("ignore")

RAW_DIR   = Path("ai/data/raw")
CACHE_DIR = Path("ai/data/cache")

# 부산 좌표 유효 범위
BUSAN_LAT = (34.8, 35.5)
BUSAN_LNG = (128.7, 129.4)


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
    for enc in ["utf-8-sig", "cp949", "euc-kr"]:
        try:
            return pd.read_csv(RAW_DIR / fname, encoding=enc)
        except Exception:
            continue
    raise ValueError(f"파일 로딩 실패: {fname}")


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
    return _to_gdf(df[["역코드", "역명", "elevator_accessible", "위도", "경도"]])


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
# 전체 레이어 로딩 (캐시 포함)
# ─────────────────────────────────────────────────────────────

def load_all_layers(use_cache: bool = True) -> dict:
    """
    모든 레이어를 로딩하여 dict로 반환한다.

    Parameters
    ----------
    use_cache : bool
        True이면 pickle 캐시 사용 (최초 1회만 실제 로딩).
        데이터 파일이 변경되면 False로 설정하여 재로딩.

    Returns
    -------
    dict
        레이어명 → GeoDataFrame 딕셔너리.
    """
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_path = CACHE_DIR / "all_layers.pkl"

    if use_cache and cache_path.exists():
        with open(cache_path, "rb") as f:
            print("✅ 캐시에서 레이어 로딩")
            return pickle.load(f)

    print("📦 데이터 레이어 로딩 중...")
    layers = {
        "shelter":            load_shelter(),
        "cctv":               load_cctv(),
        "aed":                load_aed(),
        "wheelchair_charger": load_wheelchair_charger(),
        "dongbaekjeon":       load_dongbaekjeon(),
        "smart_shelter":      load_smart_shelter(),
        "subway":             load_subway(),
        "crosswalk":          load_crosswalk(),
        "bus_stop":           load_bus_stop(),
    }

    for name, gdf in layers.items():
        print(f"  {name}: {len(gdf):,}행")

    with open(cache_path, "wb") as f:
        pickle.dump(layers, f)
    print("✅ 캐시 저장 완료")
    return layers
