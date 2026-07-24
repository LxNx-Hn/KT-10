"""
경로 좌표 시퀀스 → 피처 벡터 추출 모듈.

외부 API(카카오/네이버/TMAP/OSMnx)에서 받은 경로 좌표 리스트와
load_all_layers()가 반환한 GeoDataFrame 레이어들을 입력으로 받아
피처 딕셔너리를 반환한다.
"""
from shapely.geometry import LineString, MultiLineString
import geopandas as gpd
import numpy as np
import pandas as pd

# 부산 권역 거리 계산용 중부원점(GRS80) 투영 좌표계. 모든 버퍼 단위는 미터다.
METRIC_CRS = "EPSG:5179"
BUF_50M = 50.0
BUF_200M = 200.0


# ─────────────────────────────────────────────────────────────
# 내부 헬퍼 함수
# ─────────────────────────────────────────────────────────────

def _metric_layer(gdf: gpd.GeoDataFrame | None) -> gpd.GeoDataFrame | None:
    if gdf is None or len(gdf) == 0 or gdf.crs is None:
        return None
    return gdf if str(gdf.crs).upper() == METRIC_CRS else gdf.to_crs(METRIC_CRS)


def _nearby(gdf: gpd.GeoDataFrame | None, buffer) -> gpd.GeoDataFrame | None:
    layer = _metric_layer(gdf)
    if layer is None:
        return None
    return layer[layer.geometry.intersects(buffer)]


def _count(gdf: gpd.GeoDataFrame | None, buffer) -> int | None:
    """버퍼 내 행 수. 레이어 자체가 없으면 미확인(None)이다."""
    nearby = _nearby(gdf, buffer)
    return None if nearby is None else int(len(nearby))


def _any(gdf: gpd.GeoDataFrame | None, buffer) -> int | None:
    count = _count(gdf, buffer)
    return None if count is None else int(count > 0)


def _mean_col(gdf: gpd.GeoDataFrame | None, buffer, col: str) -> float | None:
    """버퍼 내 컬럼 평균. 레이어/주변 관측치/컬럼이 없으면 미확인이다."""
    nearby = _nearby(gdf, buffer)
    if nearby is None or len(nearby) == 0 or col not in nearby:
        return None
    mean = nearby[col].mean()
    return None if pd.isna(mean) else float(mean)


def _sum_nonnegative_col(
    gdf: gpd.GeoDataFrame | None,
    buffer,
    col: str,
) -> float | None:
    """버퍼 내 완전 관측된 비음수 수량을 합산한다."""
    nearby = _nearby(gdf, buffer)
    if nearby is None or col not in nearby:
        return None
    if len(nearby) == 0:
        return 0.0
    values = pd.to_numeric(nearby[col], errors="coerce")
    if (
        values.isna().any()
        or not np.isfinite(values.to_numpy(dtype=float)).all()
        or (values < 0).any()
    ):
        return None
    return float(values.sum())


def _any_col(gdf: gpd.GeoDataFrame | None, buffer, col: str) -> int | None:
    nearby = _nearby(gdf, buffer)
    if nearby is None or col not in nearby:
        return None
    if len(nearby) == 0:
        return 0
    return int(nearby[col].any())


def _zero_features() -> dict:
    """경로나 레이어를 확인할 수 없을 때의 명시적 미확인 피처."""
    return {
        "cctv_density_50m":              None,
        "crosswalk_count":               None,
        "crosswalk_signal_ratio":        None,
        "shelter_nearby":                None,
        "aed_nearby":                    None,
        "wheelchair_charger_nearby":     None,
        "smart_shelter_nearby":          None,
        "smart_shelter_has_ac":          None,
        "dongbaekjeon_store_count_200m": None,
        "bus_stop_count_200m":           None,
    }


# ─────────────────────────────────────────────────────────────
# 핵심 추출 함수
# ─────────────────────────────────────────────────────────────

def extract_route_features(
    route_coords: list[tuple[float, float]],
    data_layers: dict,
) -> dict:
    """단일 연속 경로 호환 API."""
    return extract_route_features_for_parts(
        [route_coords] if route_coords else [],
        data_layers,
    )


def extract_route_features_for_parts(
    route_parts: list[list[tuple[float, float]]],
    data_layers: dict,
) -> dict:
    """
    서로 끊어진 보행 parts 주변의 공간 피처를 계산하여 반환한다.

    Parameters
    ----------
    route_parts : list of lists of (lat, lng) tuples
        연결된 각 보행 구간의 좌표 시퀀스. 구간끼리는 연결하지 않는다.
        좌표는 (위도, 경도) 순서로 입력.
    data_layers : dict
        load_all_layers()가 반환한 GeoDataFrame 딕셔너리.

    Returns
    -------
    dict
        피처명 → 값 딕셔너리. 모든 피처는 float 또는 int 타입.

    Notes
    -----
    - 좌표가 2개 미만이면 전체 피처를 미확인(None)으로 반환.
    - 레이어가 없거나 비어있으면 실제 0과 구분하기 위해 None으로 처리.
    - 버퍼 크기: CCTV·횡단보도 50m / 쉼터·AED·충전기·동백전 200m.
    """
    if (
        not route_parts
        or any(len(part) < 2 for part in route_parts)
    ):
        return _zero_features()

    # (위도, 경도) → (경도, 위도) 순으로 각 LineString을 생성한다.
    # MultiLineString은 떨어진 보행 parts 사이에 가짜 선을 추가하지 않는다.
    lines = [
        LineString([(lng, lat) for lat, lng in part])
        for part in route_parts
    ]
    geometry = lines[0] if len(lines) == 1 else MultiLineString(lines)
    line_wgs84 = gpd.GeoSeries(
        [geometry],
        crs="EPSG:4326",
    )
    line = line_wgs84.to_crs(METRIC_CRS).iloc[0]
    if line.is_empty or not line.is_valid or line.length <= 0:
        return _zero_features()
    buf_50m = line.buffer(BUF_50M)
    buf_200m = line.buffer(BUF_200M)
    route_len_km = line.length / 1000.0

    cctv_count = _sum_nonnegative_col(
        data_layers.get("cctv"),
        buf_50m,
        "카메라대수",
    )

    return {
        # CCTV 밀도: 설치지점 행 수가 아닌 경로 1km당 실제 카메라 대수.
        "cctv_density_50m": round(
            cctv_count / route_len_km, 4
        ) if cctv_count is not None else None,
        # 횡단보도 (50m 버퍼)
        "crosswalk_count":        _count(data_layers.get("crosswalk"), buf_50m),
        "crosswalk_signal_ratio": _mean_col(data_layers.get("crosswalk"), buf_50m, "has_signal"),
        # 편의시설 존재 여부 (200m 버퍼)
        "shelter_nearby":           _any(data_layers.get("shelter"),            buf_200m),
        "aed_nearby":               _any(data_layers.get("aed"),                buf_200m),
        "wheelchair_charger_nearby":_any(data_layers.get("wheelchair_charger"), buf_200m),
        "smart_shelter_nearby":     _any(data_layers.get("smart_shelter"),      buf_200m),
        "smart_shelter_has_ac":     _any_col(data_layers.get("smart_shelter"),  buf_200m, "has_ac"),
        # 카운트 (200m 버퍼)
        "dongbaekjeon_store_count_200m": _count(data_layers.get("dongbaekjeon"), buf_200m),
        "bus_stop_count_200m":           _count(data_layers.get("bus_stop"),     buf_200m),
    }
