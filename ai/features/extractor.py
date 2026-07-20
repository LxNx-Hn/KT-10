"""
경로 좌표 시퀀스 → 피처 벡터 추출 모듈.

외부 API(카카오/네이버/TMAP/OSMnx)에서 받은 경로 좌표 리스트와
load_all_layers()가 반환한 GeoDataFrame 레이어들을 입력으로 받아
피처 딕셔너리를 반환한다.
"""
from shapely.geometry import LineString
import geopandas as gpd
import pandas as pd

# 버퍼 크기 (위경도 기준 근사값 — 정밀 투영 변환 불필요 수준)
# 위도 1도 ≈ 111km → 50m ≈ 0.00045도 / 200m ≈ 0.0018도 / 300m ≈ 0.0027도
BUF_50M  = 0.00045
BUF_200M = 0.0018
BUF_300M = 0.0027   # 동백전 가맹점 전용


# ─────────────────────────────────────────────────────────────
# 내부 헬퍼 함수
# ─────────────────────────────────────────────────────────────

def _count(gdf: gpd.GeoDataFrame | None, buffer) -> int:
    """버퍼 내 GeoDataFrame 행 수를 반환. None이면 0."""
    if gdf is None or len(gdf) == 0:
        return 0
    return gdf[gdf.geometry.within(buffer)].shape[0]


def _any(gdf: gpd.GeoDataFrame | None, buffer) -> int:
    """버퍼 내 행이 1개 이상이면 1, 아니면 0."""
    return int(_count(gdf, buffer) > 0)


def _mean_col(gdf: gpd.GeoDataFrame | None, buffer, col: str) -> float:
    """버퍼 내 행의 특정 컬럼 평균값. 행이 없으면 기본값 1.0 반환."""
    if gdf is None or len(gdf) == 0:
        return 1.0
    nearby = gdf[gdf.geometry.within(buffer)]
    if len(nearby) == 0:
        return 1.0
    return float(nearby[col].mean())


def _any_col(gdf: gpd.GeoDataFrame | None, buffer, col: str) -> int:
    """버퍼 내 행 중 특정 컬럼이 True인 행이 1개 이상이면 1, 아니면 0."""
    if gdf is None or len(gdf) == 0:
        return 0
    nearby = gdf[gdf.geometry.within(buffer)]
    if len(nearby) == 0:
        return 0
    return int(nearby[col].any())


def _zero_features() -> dict:
    """경로가 비어있을 때 반환할 0값 피처 딕셔너리."""
    return {
        "cctv_density_50m":              0.0,
        "crosswalk_count":               0,
        "crosswalk_signal_ratio":        1.0,
        "shelter_nearby":                0,
        "aed_nearby":                    0,
        "wheelchair_charger_nearby":     0,
        "smart_shelter_nearby":          0,
        "smart_shelter_has_ac":          0,
        "dongbaekjeon_store_count_300m": 0,
        "bus_stop_count_200m":           0,
        "accident_zone_count":           0,
    }


# ─────────────────────────────────────────────────────────────
# 핵심 추출 함수
# ─────────────────────────────────────────────────────────────

def extract_route_features(
    route_coords: list[tuple[float, float]],
    data_layers: dict,
) -> dict:
    """
    경로 1개의 피처 벡터를 계산하여 반환한다.

    Parameters
    ----------
    route_coords : list of (lat, lng) tuples
        경로 좌표 시퀀스. 최소 2개 이상 필요.
        좌표는 (위도, 경도) 순서로 입력.
    data_layers : dict
        load_all_layers()가 반환한 GeoDataFrame 딕셔너리.

    Returns
    -------
    dict
        피처명 → 값 딕셔너리. 모든 피처는 float 또는 int 타입.

    Notes
    -----
    - 좌표가 2개 미만이면 전체 피처를 0으로 반환.
    - 레이어가 없거나 비어있으면 해당 피처는 0으로 처리.
    - 버퍼 크기: CCTV·횡단보도 50m / 쉼터·AED·충전기 200m / 동백전 가맹점 300m.
    """
    if len(route_coords) < 2:
        return _zero_features()

    # (위도, 경도) → (경도, 위도) 순으로 LineString 생성 (Shapely 기본: x=경도, y=위도)
    line         = LineString([(lng, lat) for lat, lng in route_coords])
    buf_50m      = line.buffer(BUF_50M)
    buf_200m     = line.buffer(BUF_200M)
    buf_300m     = line.buffer(BUF_300M)
    route_len_km = max(line.length * 111.0, 0.1)  # 위경도 → km 근사, 최솟값 0.1

    accident = data_layers.get("accident")
    accident_count = 0
    if accident is not None and len(accident) > 0:
        accident_count = int(accident[accident.geometry.intersects(line)].shape[0])

    return {
        # CCTV 밀도: 경로 1km당 CCTV 수 (50m 버퍼)
        "cctv_density_50m": round(
            _count(data_layers.get("cctv"), buf_50m) / route_len_km, 4
        ),
        # 횡단보도 (50m 버퍼)
        "crosswalk_count":        _count(data_layers.get("crosswalk"), buf_50m),
        "crosswalk_signal_ratio": _mean_col(data_layers.get("crosswalk"), buf_50m, "has_signal"),
        # 사고다발구간 통과 수 (경로 자체와의 교차 여부)
        "accident_zone_count": accident_count,
        # 편의시설 존재 여부 (200m 버퍼)
        "shelter_nearby":           _any(data_layers.get("shelter"),            buf_200m),
        "aed_nearby":               _any(data_layers.get("aed"),                buf_200m),
        "wheelchair_charger_nearby":_any(data_layers.get("wheelchair_charger"), buf_200m),
        "smart_shelter_nearby":     _any(data_layers.get("smart_shelter"),      buf_200m),
        "smart_shelter_has_ac":     _any_col(data_layers.get("smart_shelter"),  buf_200m, "has_ac"),
        # 카운트 (동백전 300m / 버스정류장 200m)
        "dongbaekjeon_store_count_300m": _count(data_layers.get("dongbaekjeon"), buf_300m),
        "bus_stop_count_200m":           _count(data_layers.get("bus_stop"),     buf_200m),
    }
