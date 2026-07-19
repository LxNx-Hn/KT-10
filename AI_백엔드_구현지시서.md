# AI · 백엔드 전체 구현 지시서 — 실제 동작 기준

> 이 문서는 실제로 서버가 돌아가고 API가 응답하는 수준의 완전한 구현을 목표로 합니다.
> 클로드작업.md 에서 설계한 AI 파이프라인과 백엔드 API를 실제로 연결하여
> 프론트엔드에서 출발지·도착지를 입력하면 경로 추천 결과가 반환되는 전체 흐름을 구현합니다.
>
> 작업 전 아래 파일을 먼저 전부 읽으세요.
> - 클로드작업.md (AI 파이프라인 설계)
> - backend/app/main.py
> - backend/app/routers/
> - ai/ 전체

---

## 0. 전체 동작 흐름

```
[프론트엔드]
  출발지·도착지 입력 + 프로필 선택 + 날씨 선택
        ↓ POST /api/routes/recommend
[백엔드 FastAPI]
  1. 카카오 로컬 API로 출발지·도착지 좌표 변환
  2. AI 서버에 경로 추천 요청
        ↓ POST http://ai:8001/recommend
[AI FastAPI 서버]
  3. ODsay API로 경로 후보 수집 (최대 3개)
  4. TMAP으로 보행자 구간 상세 수집
  5. OSMnx fallback (항상 최소 1개 보장)
  6. 중복 경로 병합
  7. 공간 데이터와 매칭하여 피처 벡터 추출
  8. XGBRanker로 베이스 점수 산출
  9. 로짓 패널티 적용 (프로필별)
  10. Softmax 연산 → Top-3 순위 결정
  11. SHAP으로 추천 이유 생성
        ↓ 응답 반환
[백엔드]
  12. AI 응답을 프론트 형식으로 가공하여 반환
[프론트엔드]
  13. 카카오맵에 경로 폴리라인 표시 + 경로 카드 렌더링
```

---

## 1. AI 서버 (ai/)

### 1-1. ai/config.py

```python
"""AI 서버 설정. .env 파일에서 API 키를 읽는다."""
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    ODSAY_API_KEY: str = ""
    TMAP_API_KEY:  str = ""

    class Config:
        env_file = "ai/.env"
        env_file_encoding = "utf-8"


settings = Settings()
```

### 1-2. ai/main.py

```python
"""AI FastAPI 서버 진입점."""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from ai.api.router import router

app = FastAPI(title="교통약자 경로추천 AI 서버")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)


@app.get("/health")
async def health():
    return {"status": "ok", "service": "ai"}
```

### 1-3. ai/merger/route_merger.py

```python
"""중복 경로 병합 모듈."""
from dataclasses import dataclass, field
from math import radians, cos, sin, asin, sqrt
from ai.collectors.base import Coordinate

MERGE_THRESHOLD_M = 30.0


@dataclass
class MergedRoute:
    sources:      list
    path:         list
    duration_min: float
    distance_m:   float
    raw_response: dict = field(default_factory=dict)
    source:       str  = ""


def _haversine(c1: Coordinate, c2: Coordinate) -> float:
    """두 좌표 간 거리(m) 계산."""
    R = 6371000
    lat1, lon1 = radians(c1.lat), radians(c1.lng)
    lat2, lon2 = radians(c2.lat), radians(c2.lng)
    dlat, dlon = lat2 - lat1, lon2 - lon1
    a = sin(dlat/2)**2 + cos(lat1) * cos(lat2) * sin(dlon/2)**2
    return R * 2 * asin(sqrt(a))


def _sample_path(path: list, n=10) -> list:
    """경로를 n개 좌표로 균등 샘플링."""
    if len(path) <= n:
        return path
    step = len(path) / n
    return [path[int(i * step)] for i in range(n)]


def _path_similarity(a: list, b: list) -> float:
    """두 경로의 샘플링 좌표 간 평균 거리(m)를 반환. 값이 작을수록 유사."""
    sa, sb = _sample_path(a), _sample_path(b)
    if not sa or not sb:
        return float("inf")
    return sum(_haversine(p1, p2) for p1, p2 in zip(sa, sb)) / len(sa)


def merge_route_candidates(candidates: list) -> list:
    """
    경로 후보 리스트를 받아 중복을 병합한 MergedRoute 리스트를 반환한다.
    병합 기준: 샘플링 좌표 간 평균 거리 <= MERGE_THRESHOLD_M
    """
    merged: list[MergedRoute] = []

    for cand in candidates:
        matched = False
        for m in merged:
            if _path_similarity(cand.path, m.path) <= MERGE_THRESHOLD_M:
                if cand.source not in m.sources:
                    m.sources.append(cand.source)
                if cand.raw_response and not m.raw_response:
                    m.raw_response = cand.raw_response
                matched = True
                break

        if not matched:
            merged.append(MergedRoute(
                sources=[cand.source],
                source=cand.source,
                path=cand.path,
                duration_min=cand.duration_min,
                distance_m=cand.distance_m,
                raw_response=cand.raw_response or {},
            ))

    return merged
```

### 1-4. ai/api/router.py

```python
"""AI 서버 FastAPI 라우터 — 경로 추천 엔드포인트."""
import asyncio
import pandas as pd
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ai.collectors.base import Coordinate
from ai.collectors.odsay_collector import OdsayRouteCollector
from ai.collectors.tmap_collector import TmapRouteCollector
from ai.collectors.osmnx_collector import OsmnxRouteCollector
from ai.merger.route_merger import merge_route_candidates
from ai.preprocessing.load_layers import load_all_layers
from ai.features.extractor import extract_route_features
from ai.scoring.train import load_rankers, FEATURE_COLS
from ai.scoring.predict import predict_and_rank
from ai.scoring.explain import generate_reasons

router = APIRouter()

_layers  = None
_rankers = None


def _get_layers():
    global _layers
    if _layers is None:
        _layers = load_all_layers(use_cache=True)
    return _layers


def _get_rankers():
    global _rankers
    if _rankers is None:
        _rankers = load_rankers()
    return _rankers


class RecommendRequest(BaseModel):
    origin_lat:      float
    origin_lng:      float
    origin_name:     str
    dest_lat:        float
    dest_lng:        float
    dest_name:       str
    profile:         str
    weather:         str = "normal"
    prioritize_weather_safety: bool = False


@router.post("/recommend")
async def recommend(req: RecommendRequest):
    """
    출발지·도착지·프로필·날씨를 받아 추천 경로 Top-3를 반환한다.

    흐름:
      경로 수집 → 병합 → 피처 추출 → XGB 스코어링
      → 로짓 패널티 → Softmax → SHAP 추천 이유 → 응답 반환
    """
    if req.profile not in ("general", "elderly", "child", "disabled"):
        raise HTTPException(status_code=400, detail=f"지원하지 않는 프로필: {req.profile}")

    origin = Coordinate(lat=req.origin_lat, lng=req.origin_lng)
    dest   = Coordinate(lat=req.dest_lat,   lng=req.dest_lng)

    # 1. 경로 후보 수집 (병렬 호출)
    collectors = [OdsayRouteCollector(), TmapRouteCollector(), OsmnxRouteCollector()]
    src_names  = ["odsay", "tmap", "osmnx"]

    results = await asyncio.gather(
        *[c.collect(origin, dest) for c in collectors],
        return_exceptions=True,
    )

    all_candidates    = []
    sources_succeeded = []
    sources_failed    = []

    for i, result in enumerate(results):
        src = src_names[i]
        if isinstance(result, Exception) or not result:
            sources_failed.append(src)
        else:
            sources_succeeded.append(src)
            all_candidates.extend(result)

    if not all_candidates:
        raise HTTPException(status_code=503, detail="경로 수집 실패 — 모든 소스 응답 없음")

    # 2. 중복 병합
    merged = merge_route_candidates(all_candidates)

    # 3. 날씨 위험도
    weather_risk = _calc_weather_risk(req.weather, req.prioritize_weather_safety)

    # 4. 피처 추출
    layers = _get_layers()
    route_features_list = []

    for candidate in merged:
        coords        = [(c.lat, c.lng) for c in candidate.path]
        spatial_feats = extract_route_features(coords, layers)
        api_feats     = _parse_api_features(candidate)
        env_feats     = {
            "crowd_level":  _estimate_crowd_level(req.weather),
            "weather_risk": weather_risk,
        }

        all_feats = {**api_feats, **spatial_feats, **env_feats}

        # 메타 정보 (스코어링 후 응답 조립에 사용)
        all_feats["_sources"]      = candidate.sources
        all_feats["_duration_min"] = candidate.duration_min
        all_feats["_distance_m"]   = candidate.distance_m
        all_feats["_path"]         = [{"lat": c.lat, "lng": c.lng} for c in candidate.path]

        route_features_list.append(all_feats)

    # 5. XGB 스코어링 → 로짓 패널티 → Softmax
    rankers = _get_rankers()
    ranked  = predict_and_rank(rankers, route_features_list, req.profile, top_k=3)

    # 6. 응답 조립
    routes = []
    for rank_info in ranked:
        idx  = rank_info["route_index"]
        feat = route_features_list[idx]

        X_route = pd.DataFrame([{col: feat.get(col, 0) for col in FEATURE_COLS}])
        reasons = generate_reasons(rankers[req.profile], X_route)
        tags    = _generate_tags(feat, weather_risk)

        routes.append({
            "rank":         rank_info["rank"],
            "sources":      feat["_sources"],
            "path":         feat["_path"],
            "duration_min": feat["_duration_min"],
            "distance_m":   feat["_distance_m"],
            "final_score":  round(rank_info["adjusted_score"] * 100, 1),
            "probability":  rank_info["probability"],
            "features": {
                "stair_count":            feat.get("stair_count", 0),
                "avg_slope_percent":      feat.get("avg_slope_percent", 0),
                "max_slope_percent":      feat.get("max_slope_percent", 0),
                "elevator_ratio":         feat.get("elevator_ratio", 0),
                "transfer_count":         feat.get("transfer_count", 0),
                "walk_distance_m":        feat.get("walk_distance_m", 0),
                "is_low_floor_bus":       feat.get("is_low_floor_bus", 0),
                "shelter_nearby":         feat.get("shelter_nearby", 0),
                "aed_nearby":             feat.get("aed_nearby", 0),
                "crosswalk_count":        feat.get("crosswalk_count", 0),
                "crosswalk_signal_ratio": feat.get("crosswalk_signal_ratio", 1.0),
            },
            "reasons": reasons,
            "tags":    tags,
        })

    return {
        "routes": routes,
        "metadata": {
            "sources_attempted": src_names,
            "sources_succeeded": sources_succeeded,
            "sources_failed":    sources_failed,
            "profile": req.profile,
            "weather": req.weather,
        },
    }


# ─────────────────────────────────────────
# 내부 헬퍼 함수
# ─────────────────────────────────────────

def _parse_api_features(candidate) -> dict:
    """
    ODsay / TMAP raw_response에서 접근성 피처를 파싱한다.
    응답이 없거나 파싱 불가 시 기본값(0)으로 채운다.
    """
    raw = candidate.raw_response or {}

    transfer_count  = 0
    walk_distance_m = 0
    stair_count     = 0
    is_low_floor    = 0
    elevator_ratio  = 0.0

    # ODsay 응답 파싱
    info = raw.get("info", {})
    transfer_count  = info.get("transferCount", 0)
    walk_distance_m = info.get("totalWalk", 0)

    sub_paths = raw.get("subPath", [])
    elevator_segments = 0
    total_segments    = max(len(sub_paths), 1)

    for sub in sub_paths:
        if sub.get("trafficType") == 2:
            lanes = sub.get("lane", [{}])
            for lane in lanes:
                if "저상" in str(lane.get("busNo", "")):
                    is_low_floor = 1
        if sub.get("trafficType") == 3:
            if sub.get("stairInfo", {}).get("elevatorYN") == "Y":
                elevator_segments += 1

    elevator_ratio = elevator_segments / total_segments

    # TMAP 응답 파싱 (facilityType으로 계단 카운트)
    for feat in raw.get("features", []):
        props    = feat.get("properties", {})
        facility = str(props.get("facilityType", ""))
        if "계단" in facility:
            stair_count += 1

    return {
        "avg_slope_percent": 0.0,   # TODO: DEM 데이터 연동 후 채움
        "max_slope_percent": 0.0,
        "min_slope_percent": 0.0,
        "slope_iqr":         0.0,
        "stair_count":       stair_count,
        "elevator_ratio":    elevator_ratio,
        "transfer_count":    transfer_count,
        "walk_distance_m":   walk_distance_m,
        "total_duration_min": candidate.duration_min,
        "is_low_floor_bus":  is_low_floor,
    }


def _calc_weather_risk(weather: str, prioritize: bool) -> float:
    """날씨 조건 → 위험도 점수 (0~30)."""
    base = {"normal": 0, "heatwave": 20, "coldwave": 20, "rain": 15, "bad_air": 10}
    risk = float(base.get(weather, 0))
    return risk * 1.5 if prioritize else risk


def _estimate_crowd_level(weather: str) -> float:
    """날씨 조건으로 혼잡도 추정 (0~1). 실제 KT 교통카드 데이터 수신 후 교체."""
    return {"heatwave": 0.3, "coldwave": 0.3, "rain": 0.6}.get(weather, 0.5)


def _generate_tags(feat: dict, weather_risk: float) -> list:
    """경로 특성 태그 생성."""
    tags = []

    if feat.get("is_low_floor_bus"):
        tags.append({"label": "저상버스 확인", "tone": "positive"})
    elif feat.get("transfer_count", 0) == 0 and feat.get("walk_distance_m", 0) < 200:
        tags.append({"label": "버스 미이용", "tone": "neutral"})
    else:
        tags.append({"label": "일반버스(저상 아님)", "tone": "negative"})

    if feat.get("elevator_ratio", 0) > 0.5:
        tags.append({"label": "승강기 양호", "tone": "positive"})

    if weather_risk < 10:
        tags.append({"label": "날씨 위험 낮음", "tone": "positive"})
    elif weather_risk >= 20:
        tags.append({"label": "날씨 위험 높음", "tone": "negative"})

    if feat.get("shelter_nearby"):
        tags.append({"label": "쉼터 근접", "tone": "positive"})

    if feat.get("aed_nearby"):
        tags.append({"label": "AED 근접", "tone": "positive"})

    return tags
```

---

## 2. 백엔드 서버 (backend/)

### 2-1. backend/app/config.py

```python
"""백엔드 설정."""
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    KAKAO_REST_API_KEY:  str = ""
    NAVER_CLIENT_ID:     str = ""
    NAVER_CLIENT_SECRET: str = ""
    GOOGLE_MAPS_API_KEY: str = ""
    AI_SERVER_URL:       str = "http://localhost:8001"

    class Config:
        env_file = "backend/.env"
        env_file_encoding = "utf-8"


settings = Settings()
```

### 2-2. backend/app/main.py

기존 main.py 를 읽고 아래 내용과 합치세요. 라우터가 이미 등록돼 있으면 중복 등록하지 마세요.

```python
"""백엔드 FastAPI 서버 진입점."""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from backend.app.routers import route, place, health

app = FastAPI(title="교통약자 경로추천 백엔드")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router)
app.include_router(place.router,  prefix="/api")
app.include_router(route.router,  prefix="/api")
```

### 2-3. backend/app/routers/health.py

```python
"""헬스체크."""
from fastapi import APIRouter

router = APIRouter()


@router.get("/health")
async def health():
    return {"status": "ok", "service": "backend"}
```

### 2-4. backend/app/routers/place.py

```python
"""장소 검색 — 카카오 로컬 API 연동."""
import httpx
from fastapi import APIRouter, Query, HTTPException
from backend.app.config import settings

router = APIRouter(tags=["place"])


@router.get("/places/search")
async def search_place(query: str = Query(..., description="검색어")):
    """카카오 로컬 키워드 검색. 출발지·도착지 자동완성에 사용."""
    if not settings.KAKAO_REST_API_KEY:
        raise HTTPException(status_code=503, detail="KAKAO_REST_API_KEY 미설정")

    async with httpx.AsyncClient() as client:
        resp = await client.get(
            "https://dapi.kakao.com/v2/local/search/keyword.json",
            params={"query": query, "size": 5},
            headers={"Authorization": f"KakaoAK {settings.KAKAO_REST_API_KEY}"},
            timeout=5.0,
        )

    if resp.status_code != 200:
        raise HTTPException(status_code=502, detail="카카오 API 오류")

    places = []
    for doc in resp.json().get("documents", []):
        places.append({
            "place_name": doc["place_name"],
            "address":    doc["address_name"],
            "lat":        float(doc["y"]),
            "lng":        float(doc["x"]),
        })

    return {"places": places}


@router.get("/places/coord")
async def get_coord(address: str = Query(..., description="주소")):
    """주소 → 좌표 변환 (카카오 로컬 주소 검색)."""
    if not settings.KAKAO_REST_API_KEY:
        raise HTTPException(status_code=503, detail="KAKAO_REST_API_KEY 미설정")

    async with httpx.AsyncClient() as client:
        resp = await client.get(
            "https://dapi.kakao.com/v2/local/search/address.json",
            params={"query": address, "size": 1},
            headers={"Authorization": f"KakaoAK {settings.KAKAO_REST_API_KEY}"},
            timeout=5.0,
        )

    docs = resp.json().get("documents", [])
    if not docs:
        raise HTTPException(status_code=404, detail=f"주소를 찾을 수 없음: {address}")

    doc = docs[0]
    return {
        "address": doc["address_name"],
        "lat":     float(doc["y"]),
        "lng":     float(doc["x"]),
    }
```

### 2-5. backend/app/routers/route.py

```python
"""경로 추천 — AI 서버 중계."""
import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from backend.app.config import settings

router = APIRouter(tags=["route"])


class RouteRequest(BaseModel):
    origin_lat:      float
    origin_lng:      float
    origin_name:     str
    dest_lat:        float
    dest_lng:        float
    dest_name:       str
    profile:         str
    weather:         str  = "normal"
    prioritize_weather_safety: bool = False


@router.post("/routes/recommend")
async def recommend_routes(req: RouteRequest):
    """
    AI 서버에 경로 추천을 요청하고 결과를 반환한다.
    백엔드는 얇은 중계 레이어 역할만 담당.
    """
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"{settings.AI_SERVER_URL}/recommend",
                json=req.dict(),
            )
    except httpx.ConnectError:
        raise HTTPException(status_code=503, detail="AI 서버에 연결할 수 없습니다")
    except httpx.TimeoutException:
        raise HTTPException(status_code=504, detail="AI 서버 응답 시간 초과")

    if resp.status_code != 200:
        raise HTTPException(status_code=502, detail=f"AI 서버 오류: {resp.status_code}")

    return resp.json()


@router.get("/routes/health")
async def route_health():
    """AI 서버 연결 상태 확인."""
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"{settings.AI_SERVER_URL}/health")
        return {"backend": "ok", "ai_server": resp.json()}
    except Exception as e:
        return {"backend": "ok", "ai_server": "unavailable", "error": str(e)}
```

### 2-6. backend/requirements.txt

```
fastapi==0.115.0
uvicorn[standard]==0.30.0
pydantic==2.9.0
pydantic-settings==2.5.0
httpx==0.27.0
python-dotenv==1.0.1
```

---

## 3. Docker Compose

### 3-1. docker-compose.yml

기존 파일이 있으면 읽고 내용을 합치세요. 없으면 아래 내용으로 새로 생성.

```yaml
version: "3.9"

services:
  backend:
    build:
      context: .
      dockerfile: backend/Dockerfile
    ports:
      - "8000:8000"
    env_file:
      - backend/.env
    depends_on:
      - ai
    volumes:
      - ./backend:/app/backend
      - ./data:/app/data
    command: uvicorn backend.app.main:app --host 0.0.0.0 --port 8000 --reload

  ai:
    build:
      context: .
      dockerfile: ai/Dockerfile
    ports:
      - "8001:8001"
    env_file:
      - ai/.env
    volumes:
      - ./ai:/app/ai
      - ./data:/app/data
    command: uvicorn ai.main:app --host 0.0.0.0 --port 8001 --reload

  frontend:
    build:
      context: frontend
      dockerfile: Dockerfile
    ports:
      - "5173:5173"
    env_file:
      - frontend/.env
    volumes:
      - ./frontend:/app
      - /app/node_modules
    command: pnpm dev --host
```

### 3-2. backend/Dockerfile

```dockerfile
FROM python:3.11-slim
WORKDIR /app

RUN apt-get update && apt-get install -y \
    libgeos-dev libgdal-dev gcc g++ \
    && rm -rf /var/lib/apt/lists/*

COPY backend/requirements.txt backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt

COPY backend/ backend/
COPY data/ data/

EXPOSE 8000
```

### 3-3. ai/Dockerfile

```dockerfile
FROM python:3.11-slim
WORKDIR /app

RUN apt-get update && apt-get install -y \
    libgeos-dev libgdal-dev gcc g++ \
    && rm -rf /var/lib/apt/lists/*

COPY ai/requirements.txt ai/requirements.txt
RUN pip install --no-cache-dir -r ai/requirements.txt

COPY ai/ ai/
COPY data/ data/

EXPOSE 8001
```

---

## 4. 실제 동작 확인

### 4-1. 로컬 실행 (Docker 없이)

```bash
# 터미널 1 — AI 서버
cd <레포 루트>
pip install -r ai/requirements.txt
uvicorn ai.main:app --host 0.0.0.0 --port 8001 --reload

# 터미널 2 — 백엔드
pip install -r backend/requirements.txt
uvicorn backend.app.main:app --host 0.0.0.0 --port 8000 --reload

# 터미널 3 — 프론트엔드
cd frontend && pnpm install && pnpm dev
```

### 4-2. 엔드 투 엔드 테스트

```bash
# 헬스체크
curl http://localhost:8000/health
curl http://localhost:8001/health

# 장소 검색
curl "http://localhost:8000/api/places/search?query=부산진구청"

# 경로 추천 (핵심)
curl -X POST http://localhost:8000/api/routes/recommend \
  -H "Content-Type: application/json" \
  -d '{
    "origin_lat": 35.1626,
    "origin_lng": 129.0530,
    "origin_name": "부산진구청",
    "dest_lat": 35.1578,
    "dest_lng": 129.0594,
    "dest_name": "서면역",
    "profile": "elderly",
    "weather": "normal",
    "prioritize_weather_safety": false
  }'
```

### 4-3. 예상 응답 형식

```json
{
  "routes": [
    {
      "rank": 1,
      "sources": ["odsay"],
      "path": [
        {"lat": 35.1626, "lng": 129.0530},
        {"lat": 35.1578, "lng": 129.0594}
      ],
      "duration_min": 14,
      "distance_m": 980,
      "final_score": 87.3,
      "probability": 0.612,
      "features": {
        "stair_count": 0,
        "avg_slope_percent": 2.1,
        "elevator_ratio": 0.8,
        "transfer_count": 0,
        "walk_distance_m": 320,
        "is_low_floor_bus": 0,
        "shelter_nearby": 1,
        "crosswalk_count": 3,
        "crosswalk_signal_ratio": 0.67
      },
      "reasons": [
        "승강기로 이동할 수 있어 계단을 피할 수 있어요",
        "환승 없이 한 번에 이동해요",
        "경로 근처에 쉼터가 있어요"
      ],
      "tags": [
        {"label": "버스 미이용", "tone": "neutral"},
        {"label": "승강기 양호", "tone": "positive"},
        {"label": "날씨 위험 낮음", "tone": "positive"}
      ]
    }
  ],
  "metadata": {
    "sources_attempted": ["odsay", "tmap", "osmnx"],
    "sources_succeeded": ["odsay", "osmnx"],
    "sources_failed": ["tmap"],
    "profile": "elderly",
    "weather": "normal"
  }
}
```

---

## 5. 프론트엔드 연동 포인트

| 엔드포인트 | 메서드 | 용도 |
|---|---|---|
| `/health` | GET | 백엔드 헬스체크 |
| `/api/places/search?query=` | GET | 출발지·도착지 검색창 자동완성 |
| `/api/places/coord?address=` | GET | 주소 → 좌표 변환 |
| `/api/routes/recommend` | POST | 경로 추천 핵심 요청 |
| `/api/routes/health` | GET | AI 서버 연결 상태 |

**경로 추천 요청 타입 (TypeScript)**

```typescript
interface RouteRequest {
  origin_lat:   number
  origin_lng:   number
  origin_name:  string
  dest_lat:     number
  dest_lng:     number
  dest_name:    string
  profile:      "general" | "elderly" | "child" | "disabled"
  weather:      "normal" | "heatwave" | "coldwave" | "rain" | "bad_air"
  prioritize_weather_safety: boolean
}
```

**응답에서 카카오맵 폴리라인 그리기**

```typescript
const path = routes[0].path.map(p =>
  new kakao.maps.LatLng(p.lat, p.lng)
)
const polyline = new kakao.maps.Polyline({
  path,
  strokeWeight: 5,
  strokeColor: "#3B82F6",
  strokeOpacity: 0.9,
})
polyline.setMap(map)
```

---

## 6. 작업 순서

1. **ai/config.py** 생성
2. **ai/merger/route_merger.py** 구현
3. **ai/api/router.py** 구현
4. **ai/main.py** 구현 (기존 있으면 합치기)
5. **backend/app/config.py** 생성
6. **backend/app/routers/health.py** 구현
7. **backend/app/routers/place.py** 구현
8. **backend/app/routers/route.py** 구현
9. **backend/app/main.py** 구현 (기존 있으면 합치기)
10. **backend/Dockerfile**, **ai/Dockerfile** 생성
11. **docker-compose.yml** 생성 (기존 있으면 합치기)
12. **로컬 실행 후 curl 테스트**
13. **프론트엔드 연동 확인**

---

## 7. 최종 확인 체크리스트

- [ ] `curl http://localhost:8000/health` → `{"status":"ok","service":"backend"}`
- [ ] `curl http://localhost:8001/health` → `{"status":"ok","service":"ai"}`
- [ ] `GET /api/places/search?query=부산진구청` → 좌표 포함 장소 목록
- [ ] `POST /api/routes/recommend` → routes 배열 최소 1개 이상 포함
- [ ] routes[i].path 에 위경도 좌표 2개 이상 포함
- [ ] routes[i].reasons 비어있지 않음
- [ ] routes[i].tags 비어있지 않음
- [ ] ODSAY_API_KEY 없어도 OSMnx fallback으로 경로 1개 이상 반환
- [ ] 프로필 "disabled" 요청 시 stair_count 높은 경로가 낮은 순위로 배치
- [ ] CORS 설정으로 localhost:5173 → localhost:8000 요청 성공
- [ ] Docker Compose `docker compose up --build` 로 전체 서비스 정상 실행
