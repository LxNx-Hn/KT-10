# Claude Code 작업 지시서 — AI 피처 추출 및 스코어링 파이프라인

> 이 문서는 Claude Code가 읽고 순서대로 작업하기 위한 지시서입니다.
> 작업 시작 전 이 문서를 전부 읽고 구조를 완전히 파악한 뒤 진행하세요.

---

## 0. 작업 개요 및 전제 조건

### 프로젝트 개요

부산 교통약자 맞춤형 경로 추천 서비스의 AI 파이프라인입니다.
외부 API(카카오/네이버/TMAP/OSMnx)에서 받은 경로 후보들을 수집된 공간 데이터와 매칭하여
피처 벡터로 변환하고, XGBoost로 프로필별 점수를 산출하는 구조입니다.

### 전제 조건

데이터팀에서 아래 기준으로 전처리된 파일들이 `data/raw/` 에 있다고 가정합니다.
- 부산 지역으로 한정 필터링 완료
- 위경도(`위도`, `경도`) 컬럼 반드시 포함
- 필요한 컬럼만 정리된 상태

**현재 사용 가능한 파일 목록**

```
data/raw/
├── 부산광역시_무더위_쉼터_20251119.csv       # 1,789행
├── 부산광역시_한파_쉼터_현황_20251119.csv    # 1,126행
├── 부산광역시_방범용_CCTV_정보_20251229.csv  # 21,060행  ← 데이터팀 병합 파일 수신 전까지 임시 사용
├── CCTV정보_부산광역시.csv                   # 18,074행  ← 동일
├── 부산광역시_스마트_버스쉘터_설치_현황.csv  # 44행
├── 부산전동휠체어급속충전기표준데이터.csv    # 199행
├── 동백전_가맹점_현황.csv                    # 131,266행
├── 부산_AED_위경도_결과.xlsx                 # 2,628행
├── bus_stop_national_csv_processed.xlsx      # 227,065행 ← 반드시 부산만 필터링 후 사용
├── busan_crosswalk_signal_shp_processed.xlsx # 3,812행
└── busan_subway_station_accessibility_processed.xlsx  # 114행
```

**⚠️ 주의사항 (반드시 준수)**
- `bus_stop_national_csv_processed.xlsx` 는 전국 데이터. `도시명 == '부산광역시'` 로 반드시 필터링
- CCTV 두 파일은 중복 없음(별개 출처). 단순 concat 후 이상치만 제거
- 부산 좌표 범위: `위도 34.8~35.5 / 경도 128.7~129.4` — 이 범위 벗어난 행은 모두 제거
- 모든 코드에 한국어 docstring 작성

---

## 1. 디렉토리 구조

아래 구조를 정확히 생성하세요.

```
ai_pipeline/
├── data/
│   ├── raw/                     # 데이터팀 제공 원본 파일
│   └── cache/                   # GeoDataFrame pickle 캐시
├── preprocessing/
│   ├── __init__.py
│   ├── load_layers.py            # 데이터 레이어 로딩 및 GeoDataFrame 변환
│   └── parse_facilities.py      # 스마트버스쉘터 부대시설 텍스트 → 불리언 파싱
├── features/
│   ├── __init__.py
│   └── extractor.py             # 경로 좌표 → 피처 벡터 추출
├── scoring/
│   ├── __init__.py
│   ├── train.py                  # XGBRanker 학습 (가상 데이터 → 실데이터 교체 구조)
│   ├── predict.py                # 추론: XGB → 로짓 패널티 → Softmax → Top-K
│   └── explain.py               # SHAP 기반 추천 이유 자동 생성
├── tests/
│   ├── __init__.py
│   ├── test_load_layers.py
│   ├── test_extractor.py
│   └── test_scoring.py
├── requirements.txt
└── README.md
```

---

## 2. requirements.txt

```
pandas==2.2.2
geopandas==1.0.1
shapely==2.0.6
numpy==1.26.4
xgboost==2.1.1
scikit-learn==1.5.1
shap==0.46.0
openpyxl==3.1.5
```

---

## 3. preprocessing/parse_facilities.py

스마트버스쉘터 `부대시설` 컬럼이 자유 텍스트 형태이므로 불리언 피처로 변환합니다.

```python
"""스마트버스쉘터 부대시설 텍스트 파싱 모듈."""


def parse_facilities(text: str) -> dict:
    """
    '냉난방기, 공기청정기, 온열의자' 형태의 자유 텍스트를
    불리언 피처 딕셔너리로 변환한다.

    Parameters
    ----------
    text : str
        부대시설 컬럼 원본 텍스트.

    Returns
    -------
    dict
        피처명 → bool 딕셔너리.
    """
    text = str(text)
    return {
        "has_ac":           "냉난방" in text or "냉방" in text,
        "has_air_purifier": "공기청정" in text,
        "has_heated_seat":  "온열의자" in text or "냉온열의자" in text,
        "has_charger":      "충전기" in text,
        "has_wifi":         "와이파이" in text,
        "has_kiosk":        "키오스크" in text,
        "has_auto_door":    "자동문" in text,
    }
```

---

## 4. preprocessing/load_layers.py

각 파일을 로딩하여 GeoDataFrame으로 변환하고 pickle 캐시로 저장합니다.
`load_all_layers(use_cache=True)` 를 호출하면 최초 1회만 실제 로딩하고 이후엔 캐시를 씁니다.

아래 내용을 그대로 구현하세요. 주석 위치와 구조 변경 금지.

```python
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

RAW_DIR   = Path("ai_pipeline/data/raw")
CACHE_DIR = Path("ai_pipeline/data/cache")

# 부산 좌표 유효 범위
BUSAN_LAT = (34.8, 35.5)
BUSAN_LNG = (128.7, 129.4)


def _filter_busan(df: pd.DataFrame, lat_col: str = "위도", lng_col: str = "경도") -> pd.DataFrame:
    """부산 범위를 벗어난 좌표를 가진 행을 제거한다."""
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
    # lat/lng 컬럼을 위도/경도로 통일
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
```

---

## 5. features/extractor.py

경로 좌표 시퀀스와 공간 레이어를 받아 피처 벡터를 반환하는 핵심 함수입니다.
아래 내용을 그대로 구현하세요.

```python
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
# 위도 1도 ≈ 111km → 50m ≈ 0.00045도 / 200m ≈ 0.0018도
BUF_50M  = 0.00045
BUF_200M = 0.0018


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
        "dongbaekjeon_store_count_200m": 0,
        "bus_stop_count_200m":           0,
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
    - 버퍼 크기: CCTV·횡단보도 50m / 쉼터·AED·충전기·동백전 200m.
    """
    if len(route_coords) < 2:
        return _zero_features()

    # (위도, 경도) → (경도, 위도) 순으로 LineString 생성 (Shapely 기본: x=경도, y=위도)
    line         = LineString([(lng, lat) for lat, lng in route_coords])
    buf_50m      = line.buffer(BUF_50M)
    buf_200m     = line.buffer(BUF_200M)
    route_len_km = max(line.length * 111.0, 0.1)  # 위경도 → km 근사, 최솟값 0.1

    return {
        # CCTV 밀도: 경로 1km당 CCTV 수 (50m 버퍼)
        "cctv_density_50m": round(
            _count(data_layers.get("cctv"), buf_50m) / route_len_km, 4
        ),
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
```

---

## 6. scoring/train.py

XGBRanker를 프로필별로 학습합니다.
현재는 가상 데이터로 파이프라인 구조를 검증하며, 실데이터 수신 후 `generate_synthetic_data()` 만 교체합니다.

```python
"""
XGBRanker 학습 모듈.

현재는 가상 데이터(synthetic data)로 파이프라인 구조를 검증한다.
실데이터 수신 후 generate_synthetic_data()를 실제 데이터 로딩으로 교체한다.
"""
import pickle
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.model_selection import GroupKFold
from xgboost import XGBRanker

PROFILES   = ["general", "elderly", "child", "disabled"]
MODEL_DIR  = Path("ai_pipeline/data")

# 전체 피처 컬럼 (API 경로 응답 기반 피처 + 공간 데이터 기반 피처)
FEATURE_COLS = [
    # 경사·지형 (API 경로 응답 기반 — 실데이터 수신 후 채워짐)
    "avg_slope_percent", "max_slope_percent", "min_slope_percent", "slope_iqr",
    # 이동·접근성 (API 경로 응답 기반)
    "stair_count", "elevator_ratio", "transfer_count",
    "walk_distance_m", "total_duration_min", "is_low_floor_bus",
    # 안전 (공간 데이터 기반 — extractor.py 출력)
    "cctv_density_50m", "crosswalk_count", "crosswalk_signal_ratio",
    # 편의시설 (공간 데이터 기반 — extractor.py 출력)
    "shelter_nearby", "aed_nearby", "wheelchair_charger_nearby",
    "smart_shelter_nearby", "smart_shelter_has_ac",
    # 부산 특화 (공간 데이터 기반 — extractor.py 출력)
    "dongbaekjeon_store_count_200m", "bus_stop_count_200m",
    # 환경 (수동 입력)
    "crowd_level", "weather_risk",
]


def generate_synthetic_data(n_groups: int = 300, n_routes: int = 3, seed: int = 42) -> pd.DataFrame:
    """
    가상 경로 데이터 생성.

    ⚠️ 실데이터 수신 후 이 함수를 실제 데이터 로딩으로 교체한다.
    함수 시그니처(반환 타입 포함)는 유지하여 train_rankers()와의 호환성 보존.
    """
    np.random.seed(seed)
    records = []

    for g in range(n_groups):
        for _ in range(n_routes):
            slope_vals = np.random.uniform(0, 20, 10)
            rec = {
                "group_id": g,
                # 경사
                "avg_slope_percent": float(slope_vals.mean()),
                "max_slope_percent": float(slope_vals.max()),
                "min_slope_percent": float(np.random.uniform(-10, 0)),
                "slope_iqr":         float(np.percentile(slope_vals, 75) - np.percentile(slope_vals, 25)),
                # 이동
                "stair_count":       int(np.random.randint(0, 10)),
                "elevator_ratio":    float(np.random.uniform(0, 1)),
                "transfer_count":    int(np.random.randint(0, 3)),
                "walk_distance_m":   float(np.random.uniform(100, 2000)),
                "total_duration_min":float(np.random.uniform(5, 60)),
                "is_low_floor_bus":  int(np.random.choice([0, 1])),
                # 안전 (공간 데이터 기반)
                "cctv_density_50m":          float(np.random.uniform(0, 5)),
                "crosswalk_count":           int(np.random.randint(0, 10)),
                "crosswalk_signal_ratio":    float(np.random.uniform(0, 1)),
                # 편의시설
                "shelter_nearby":            int(np.random.randint(0, 2)),
                "aed_nearby":                int(np.random.randint(0, 2)),
                "wheelchair_charger_nearby": int(np.random.randint(0, 2)),
                "smart_shelter_nearby":      int(np.random.randint(0, 2)),
                "smart_shelter_has_ac":      int(np.random.randint(0, 2)),
                # 부산 특화
                "dongbaekjeon_store_count_200m": int(np.random.randint(0, 30)),
                "bus_stop_count_200m":           int(np.random.randint(0, 8)),
                # 환경
                "crowd_level":  float(np.random.uniform(0, 1)),
                "weather_risk": float(np.random.uniform(0, 30)),
            }
            # 프로필별 라벨: 해당 프로필에 유리한 피처일수록 높은 순위
            rec["label_general"]  = int((-rec["avg_slope_percent"] * 0.1 + np.random.randn()) > 0)
            rec["label_elderly"]  = int((-rec["stair_count"] + rec["elevator_ratio"] * 2 + np.random.randn()) > 0)
            rec["label_child"]    = int((rec["crosswalk_signal_ratio"] * 2 - rec["crosswalk_count"] * 0.2 + np.random.randn()) > 0)
            rec["label_disabled"] = int((-rec["stair_count"] * 2 + rec["elevator_ratio"] * 3 + rec["is_low_floor_bus"] * 2 + np.random.randn()) > 0)
            records.append(rec)

    return pd.DataFrame(records)


def train_rankers(df: pd.DataFrame = None) -> dict:
    """
    프로필별 XGBRanker를 GroupKFold CV로 학습하고 dict로 반환한다.

    Parameters
    ----------
    df : pd.DataFrame, optional
        학습 데이터. None이면 가상 데이터로 학습.

    Returns
    -------
    dict
        profile명 → XGBRanker 딕셔너리.
    """
    if df is None:
        print("📊 가상 데이터로 학습 (실데이터 수신 후 교체 필요)")
        df = generate_synthetic_data()

    X      = df[FEATURE_COLS]
    gkf    = GroupKFold(n_splits=5)
    rankers = {}

    for profile in PROFILES:
        y      = df[f"label_{profile}"]
        groups = df.groupby("group_id").size().values

        ranker = XGBRanker(
            objective="rank:pairwise",
            max_depth=6,
            learning_rate=0.05,
            n_estimators=300,
            subsample=0.8,
            colsample_bytree=0.8,
            min_child_weight=3,
            tree_method="hist",
            random_state=42,
        )

        for tr_idx, val_idx in gkf.split(X, y, groups=df["group_id"]):
            g_tr  = df.iloc[tr_idx].groupby("group_id").size().values
            g_val = df.iloc[val_idx].groupby("group_id").size().values
            ranker.fit(
                X.iloc[tr_idx], y.iloc[tr_idx], group=g_tr,
                eval_set=[(X.iloc[val_idx], y.iloc[val_idx])],
                eval_group=[g_val],
                verbose=False,
            )

        rankers[profile] = ranker
        print(f"  [{profile}] 학습 완료")

    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    with open(MODEL_DIR / "rankers.pkl", "wb") as f:
        pickle.dump(rankers, f)
    print(f"✅ 모델 저장: {MODEL_DIR / 'rankers.pkl'}")
    return rankers


def load_rankers() -> dict:
    """저장된 모델을 로딩. 없으면 가상 데이터로 새로 학습."""
    model_path = MODEL_DIR / "rankers.pkl"
    if not model_path.exists():
        print("⚠️ 저장된 모델 없음 → 새로 학습")
        return train_rankers()
    with open(model_path, "rb") as f:
        return pickle.load(f)
```

---

## 7. scoring/predict.py

XGBoost 점수 → 로짓 패널티 → Softmax → Top-K 반환의 전체 추론 파이프라인입니다.

```python
"""
추론 모듈.

XGBoost 점수에 프로필별 로짓 패널티를 적용하고 Softmax로 확률을 계산하여
상위 K개 경로 순위를 반환한다.

로짓 패널티 설계 원칙:
  - 양수 값: 해당 피처가 클수록 불리 (로짓에서 감산)
  - 음수 값: 해당 피처가 클수록 유리 (로짓에서 가산 = 보너스)
  - 베이스라인: 고정 상수. 추후 날씨·혼잡도에 따른 동적 조정으로 확장 예정.
"""
import numpy as np
import pandas as pd

from scoring.train import FEATURE_COLS

# 프로필별 로짓 패널티 테이블 (베이스라인 고정값)
LOGIT_PENALTIES: dict[str, dict[str, float]] = {
    "general": {
        "avg_slope_percent": 0.2,
        "crosswalk_count":   0.1,
        "crowd_level":       0.3,
        "weather_risk":      0.3,
    },
    "elderly": {
        "stair_count":         2.0,
        "avg_slope_percent":   1.5,
        "max_slope_percent":   1.0,
        "transfer_count":      1.2,
        "walk_distance_m":     0.001,
        "crowd_level":         0.8,
        "weather_risk":        1.0,
        "elevator_ratio":     -1.5,   # 엘리베이터 있으면 가산
        "shelter_nearby":     -0.8,   # 쉼터 근접 시 가산
        "smart_shelter_has_ac":-0.6,  # 냉난방 쉘터 근접 시 가산
    },
    "child": {
        "stair_count":              0.5,
        "crosswalk_count":          0.8,
        "crowd_level":              0.5,
        "weather_risk":             0.8,
        "crosswalk_signal_ratio":  -1.0,  # 신호등 많을수록 가산
    },
    "disabled": {
        "stair_count":                3.0,
        "avg_slope_percent":          2.0,
        "max_slope_percent":          1.5,
        "walk_distance_m":            0.0008,
        "elevator_ratio":            -2.0,   # 최대 가산
        "is_low_floor_bus":          -1.5,
        "wheelchair_charger_nearby": -0.5,
    },
}


def _softmax(logits: np.ndarray) -> np.ndarray:
    """수치 안정 Softmax."""
    e = np.exp(logits - logits.max())
    return e / e.sum()


def predict_and_rank(
    rankers: dict,
    route_features_list: list[dict],
    profile: str,
    top_k: int = 3,
) -> list[dict]:
    """
    경로 후보 리스트를 받아 프로필별 추천 순위를 반환한다.

    Parameters
    ----------
    rankers : dict
        train_rankers()가 반환한 {profile: XGBRanker} 딕셔너리.
    route_features_list : list of dict
        경로 후보별 피처 딕셔너리 리스트.
        없는 피처 키는 0으로 자동 처리.
    profile : str
        사용자 프로필 ("general" / "elderly" / "child" / "disabled").
    top_k : int
        반환할 상위 경로 수 (기본 3).

    Returns
    -------
    list of dict
        순위별 결과 리스트.
        각 dict: {"rank", "route_index", "xgb_score", "adjusted_score", "probability"}
    """
    ranker = rankers.get(profile)
    if ranker is None:
        raise ValueError(f"프로필 '{profile}'에 대한 모델이 없습니다.")

    # 없는 피처 키는 0으로 채워 DataFrame 구성
    X = pd.DataFrame([
        {col: feat.get(col, 0) for col in FEATURE_COLS}
        for feat in route_features_list
    ])

    # ① XGBoost 베이스 점수
    xgb_scores = ranker.predict(X)

    # ② 프로필별 로짓 패널티 적용
    penalties = LOGIT_PENALTIES.get(profile, {})
    adjusted  = xgb_scores.astype(float).copy()
    for i, feat_dict in enumerate(route_features_list):
        for feat_name, weight in penalties.items():
            adjusted[i] -= weight * feat_dict.get(feat_name, 0)

    # ③ Softmax → 확률
    probs      = _softmax(adjusted)
    ranked_idx = np.argsort(probs)[::-1][:top_k]

    return [
        {
            "rank":           rank + 1,
            "route_index":    int(idx),
            "xgb_score":      round(float(xgb_scores[idx]), 4),
            "adjusted_score": round(float(adjusted[idx]), 4),
            "probability":    round(float(probs[idx]), 4),
        }
        for rank, idx in enumerate(ranked_idx)
    ]
```

---

## 8. scoring/explain.py

SHAP 기반 추천 이유 자동 생성 모듈입니다.

```python
"""SHAP 기반 추천 이유 자동 생성 모듈."""
import shap
import pandas as pd

from scoring.train import FEATURE_COLS

# 피처별 (긍정 메시지, 부정 메시지) 쌍
# None은 해당 방향으로 메시지를 생성하지 않음
REASON_MAP: dict[str, tuple[str | None, str | None]] = {
    "elevator_ratio":              ("승강기로 이동할 수 있어 계단을 피할 수 있어요", "승강기 접근이 어려운 구간이 있어요"),
    "stair_count":                 ("계단이 없는 편이에요", "계단이 많아 이동이 불편할 수 있어요"),
    "avg_slope_percent":           ("평지 위주의 경로예요", "경사 구간이 있어요"),
    "max_slope_percent":           ("가장 가파른 구간도 완만한 편이에요", "급경사 구간이 포함돼 있어요"),
    "transfer_count":              ("환승 없이 한 번에 이동해요", "환승이 있는 경로예요"),
    "crowd_level":                 ("혼잡하지 않은 경로예요", "혼잡한 구간이 포함돼 있어요"),
    "is_low_floor_bus":            ("저상버스가 포함된 경로예요", "저상버스가 없는 경로예요"),
    "crosswalk_signal_ratio":      ("신호등 있는 횡단보도 위주예요", "신호등 없는 횡단보도가 포함돼 있어요"),
    "shelter_nearby":              ("경로 근처에 쉼터가 있어요", None),
    "smart_shelter_has_ac":        ("냉난방 가능한 버스쉘터가 근처에 있어요", None),
    "aed_nearby":                  ("경로 근처에 AED가 설치돼 있어요", None),
    "wheelchair_charger_nearby":   ("경로 근처에 전동휠체어 충전기가 있어요", None),
    "dongbaekjeon_store_count_200m":("동백전 가맹점이 많은 구역을 지나요", None),
    "cctv_density_50m":            ("CCTV가 잘 설치된 안전한 경로예요", "CCTV가 적은 구간이 있어요"),
}


def generate_reasons(
    ranker,
    X_route: pd.DataFrame,
    top_n: int = 4,
) -> list[str]:
    """
    학습된 XGBRanker와 SHAP을 활용해 추천 이유 문장 리스트를 반환한다.

    Parameters
    ----------
    ranker : XGBRanker
        학습된 모델.
    X_route : pd.DataFrame
        경로 1개의 피처 DataFrame (1행). 컬럼은 FEATURE_COLS와 일치해야 함.
    top_n : int
        반환할 이유 문장 최대 개수 (기본 4).

    Returns
    -------
    list of str
        추천 이유 문장 리스트.
    """
    explainer   = shap.TreeExplainer(ranker)
    shap_values = explainer.shap_values(X_route)

    # SHAP 절댓값 기준 상위 피처 선택
    top_feats = (
        pd.Series(shap_values[0], index=X_route.columns)
        .abs()
        .nlargest(top_n)
        .index
    )

    reasons = []
    for feat in top_feats:
        if feat not in REASON_MAP:
            continue
        pos_msg, neg_msg = REASON_MAP[feat]
        shap_val = shap_values[0][X_route.columns.get_loc(feat)]
        msg = pos_msg if shap_val > 0 else neg_msg
        if msg:
            reasons.append(msg)

    return reasons
```

---

## 9. tests/ — 반드시 작성하고 전부 통과시킬 것

### tests/test_load_layers.py

```python
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
```

### tests/test_extractor.py

```python
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
```

### tests/test_scoring.py

```python
"""XGBoost 학습 및 추론 테스트."""
import pytest
from scoring.train import train_rankers, FEATURE_COLS
from scoring.predict import predict_and_rank


@pytest.fixture(scope="module")
def rankers():
    return train_rankers()


def test_all_profiles_trained(rankers):
    """4개 프로필 모두 모델이 학습되어야 한다."""
    assert set(rankers.keys()) == {"general", "elderly", "child", "disabled"}


def test_predict_top_k(rankers):
    """top_k=3 설정 시 결과가 3개여야 한다."""
    dummy = [{col: 0.5 for col in FEATURE_COLS} for _ in range(3)]
    result = predict_and_rank(rankers, dummy, "elderly", top_k=3)
    assert len(result) == 3


def test_predict_rank_order(rankers):
    """결과는 rank 오름차순이어야 한다."""
    dummy = [{col: 0.5 for col in FEATURE_COLS} for _ in range(3)]
    result = predict_and_rank(rankers, dummy, "general", top_k=3)
    ranks = [r["rank"] for r in result]
    assert ranks == sorted(ranks)


def test_predict_probability_sum(rankers):
    """probability 합이 1.0이어야 한다 (부동소수점 허용 오차 내)."""
    dummy = [{col: 0.5 for col in FEATURE_COLS} for _ in range(3)]
    result = predict_and_rank(rankers, dummy, "general", top_k=3)
    total = sum(r["probability"] for r in result)
    assert abs(total - 1.0) < 0.01


def test_disabled_prefers_elevator(rankers):
    """
    장애인 프로필은 엘리베이터 있고 계단 없는 경로를 1순위로 선호해야 한다.
    """
    base = {col: 0.5 for col in FEATURE_COLS}
    routes = [
        {**base, "stair_count": 8, "elevator_ratio": 0.0},   # 최악
        {**base, "stair_count": 0, "elevator_ratio": 1.0},   # 최적
        {**base, "stair_count": 3, "elevator_ratio": 0.5},   # 중간
    ]
    result = predict_and_rank(rankers, routes, "disabled", top_k=3)
    best_route_idx = result[0]["route_index"]
    assert best_route_idx == 1, f"장애인 1순위가 예상(1)과 다름: {best_route_idx}"
```

---

## 10. README.md 내용

아래 내용으로 `README.md` 를 작성하세요.

````markdown
# AI 피처 추출 및 스코어링 파이프라인

부산 교통약자 맞춤형 경로 추천 서비스의 AI 파이프라인입니다.

## 설치

```bash
pip install -r requirements.txt
```

## 실행 순서

### 1. 가상 데이터로 파이프라인 검증 (데이터 없이 바로 실행 가능)

```python
from preprocessing.load_layers import load_all_layers
from features.extractor import extract_route_features
from scoring.train import train_rankers
from scoring.predict import predict_and_rank
from scoring.explain import generate_reasons
import pandas as pd

# 레이어 로딩
layers = load_all_layers()

# 경로 피처 추출 (실제 API 경로 좌표로 교체)
route_coords = [(35.1626, 129.0530), (35.1578, 129.0594)]
spatial_feats = extract_route_features(route_coords, layers)

# 모델 학습 (가상 데이터 기반)
rankers = train_rankers()

# 추론
route_features_list = [spatial_feats]   # 실제로는 경로 후보 3개
result = predict_and_rank(rankers, route_features_list, profile="elderly")
print(result)

# 추천 이유 생성
X_route = pd.DataFrame([{col: spatial_feats.get(col, 0) for col in rankers["elderly"].feature_names_in_}])
reasons = generate_reasons(rankers["elderly"], X_route)
print(reasons)
```

### 2. 실데이터 연동 후 교체 방법

`scoring/train.py` 의 `generate_synthetic_data()` 함수를 실제 데이터 로딩으로 교체합니다.
함수 반환 타입(pandas DataFrame, 컬럼 구조)은 유지해야 합니다.

### 3. 테스트 실행

```bash
pytest tests/ -v
```

## 레이어 캐시 초기화

데이터 파일이 변경되면 캐시를 재생성합니다.

```python
from preprocessing.load_layers import load_all_layers
layers = load_all_layers(use_cache=False)
```

## 주의사항

- `bus_stop_national_csv_processed.xlsx` 는 전국 데이터. 부산 필터링은 `load_bus_stop()` 내부에서 자동 처리
- CCTV 두 파일은 데이터팀 통합 파일 수신 전까지 임시 병합 사용
- `generate_synthetic_data()` 는 실데이터 수신 후 반드시 교체할 것
````

---

## 11. 작업 순서

아래 순서를 반드시 지켜서 작업하세요.

1. 디렉토리 구조 생성 및 `requirements.txt` 작성
2. `preprocessing/parse_facilities.py` 작성
3. `preprocessing/load_layers.py` 작성
4. `features/extractor.py` 작성
5. `scoring/train.py` 작성
6. `scoring/predict.py` 작성
7. `scoring/explain.py` 작성
8. `tests/` 3개 파일 작성
9. `pytest tests/ -v` 실행 → 모든 테스트 통과 확인
10. `README.md` 작성

---

## 12. 최종 확인 체크리스트

작업 완료 후 아래를 반드시 확인하세요.

- [ ] `pytest tests/ -v` 전체 통과
- [ ] `bus_stop` 레이어 행 수가 15,000 미만 (부산 필터링 확인)
- [ ] `cctv` 레이어 행 수가 30,000 이상 (두 파일 병합 확인)
- [ ] 모든 레이어의 위도가 34.8~35.5, 경도가 128.7~129.4 범위 내
- [ ] `generate_synthetic_data()` 함수 상단에 `⚠️ 실데이터 수신 후 교체` 주석 포함
- [ ] 모든 함수에 한국어 docstring 작성 완료
- [ ] `load_all_layers(use_cache=True)` 두 번째 호출 시 캐시에서 로딩되는 것 확인
