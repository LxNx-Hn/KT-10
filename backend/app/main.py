"""
FastAPI 앱. 장소/경로/버스/날씨 데이터를 REST 로 제공하고 서버측 점수화(recommend)도 제공한다.

키가 없는 개발 모드는 명시적 데모 픽스처를 사용한다. 설정된 실공급자 실패는 오류로 반환한다.
실행: uvicorn app.main:app --reload --port 8000   ·   문서: /docs
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from .api.auth import optional_current_user, router as auth_router
from .api.feedback import router as feedback_router
from .config import DISTRICT
from .database import init_database
from .database import User
from .data.bus_arrivals import BUS_STOP_LIST, get_arrivals
from .data.routes import get_route_candidates
from .data.weather import WEATHER_SCENARIOS
from .models import (
    BusStopArrivals,
    CandidatesRequest,
    Place,
    RecommendRequest,
    RouteCandidate,
    ScoredRoute,
    WeatherCondition,
)
from .providers import (
    get_ai_pipeline_routes,
    get_current_weather,
    get_bus_arrivals,
    get_public_transit_candidates,
    search_bus_stops,
    search_places,
)
from .providers.ai_pipeline import AIProviderError
from .scoring import recommend_routes
from .settings import settings

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("app")


@asynccontextmanager
async def lifespan(_: FastAPI):
    if settings.database_configured:
        init_database()
    log.info("데이터 소스: %s", settings.active_sources())
    yield


app = FastAPI(
    title="교통약자 접근성 경로 추천 API",
    description="부산 전역 서비스 · 부산역 권역 MVP · 실제 후보와 사람 라벨 기반 접근성 순위화",
    version="0.3.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.origins,
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

app.include_router(auth_router)
app.include_router(feedback_router)


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok", "district": DISTRICT["name"], "sources": settings.active_sources()}


@app.get("/api/places/search", response_model=list[Place])
async def places_search(q: str = Query("", description="장소 이름/주소 검색")) -> list[Place]:
    try:
        return await search_places(q)
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.get("/api/weather", response_model=WeatherCondition, response_model_exclude_none=True)
async def weather(scenario: str = Query("normal")) -> WeatherCondition:
    # mock 폴백 시 알 수 없는 시나리오는 400 (라이브에서는 scenario 무시하고 실측 반환)
    if not settings.live_weather and scenario not in WEATHER_SCENARIOS:
        raise HTTPException(status_code=400, detail=f"unknown scenario: {scenario}")
    try:
        return await get_current_weather(scenario)
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.get("/api/bus/stops", response_model=list[BusStopArrivals], response_model_exclude_none=True)
async def bus_stops(q: str = Query("", description="정류소명 또는 5자리 ARS 번호")) -> list[BusStopArrivals]:
    if settings.live_bus:
        try:
            return await search_bus_stops(q)
        except RuntimeError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
    return BUS_STOP_LIST


@app.get(
    "/api/bus/arrivals/{stop_id}",
    response_model=BusStopArrivals,
    response_model_exclude_none=True,
)
async def bus_arrivals(stop_id: str) -> BusStopArrivals:
    if settings.live_bus:
        try:
            return await get_bus_arrivals(stop_id)
        except RuntimeError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
    stop = get_arrivals(stop_id)
    if stop is None:
        raise HTTPException(status_code=404, detail="stop not found")
    return stop


@app.post(
    "/api/routes/candidates",
    response_model=list[RouteCandidate],
    response_model_exclude_none=True,
)
async def routes_candidates(req: CandidatesRequest) -> list[RouteCandidate]:
    """ODsay 키가 있으면 실제 대중교통 후보, 없으면 명시적인 데모 후보를 제공한다."""
    if settings.live_routes:
        try:
            return await get_public_transit_candidates(req.origin, req.destination)
        except RuntimeError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
    return get_route_candidates(req.origin, req.destination)


@app.post(
    "/api/routes/recommend",
    response_model=list[ScoredRoute],
    response_model_exclude_none=True,
)
async def routes_recommend(
    req: RecommendRequest,
    user: User | None = Depends(optional_current_user),
) -> list[ScoredRoute]:
    """
    상위 N 추천(이유/주의/음성요약 포함) 반환.
    AI_SERVER_URL 설정 시 실제 경로 수집+XGB 순위화 서버로 위임한다.
    미설정 시에만 기존 회귀검증용 데모 엔진을 사용한다.
    """
    if settings.live_ai_pipeline:
        try:
            current_weather = await get_current_weather(req.weather_scenario)
            return await get_ai_pipeline_routes(
                req.origin, req.destination, req.profile,
                req.weather_scenario, req.options, top_n=req.top_n,
                personalization_state=(user.preference.personalization_state if user and user.preference else None),
                user_preference=(user.preference if user else None),
                weather_condition=current_weather,
            )
        except AIProviderError as exc:
            raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    if settings.live_routes:
        try:
            candidates = await get_public_transit_candidates(req.origin, req.destination)
        except RuntimeError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
    else:
        candidates = get_route_candidates(req.origin, req.destination)
        if not candidates:
            raise HTTPException(status_code=503, detail="고정 데모 OD 외 경로는 AI live pipeline이 필요합니다.")
    try:
        weather = await get_current_weather(req.weather_scenario)
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return recommend_routes(candidates, weather, req.profile, req.options, top_n=req.top_n)
