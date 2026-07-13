"""
FastAPI 앱. 장소/경로/버스/날씨 데이터를 REST 로 제공하고 서버측 점수화(recommend)도 제공한다.

데이터 소스: API 키가 있으면 라이브(Kakao 장소검색 / OpenWeather), 없으면 mock 자동 폴백.
실행: uvicorn app.main:app --reload --port 8000   ·   문서: /docs
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from .api.auth import router as auth_router
from .api.feedback import router as feedback_router
from .config import DISTRICT
from .database import init_database
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
from .providers import get_current_weather, get_public_transit_candidates, search_places
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
    description="부산진구 데모 · 보행/대중교통/저상버스/날씨 기반 자체 점수화",
    version="0.2.0",
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
    return await search_places(q)


@app.get("/api/weather", response_model=WeatherCondition)
async def weather(scenario: str = Query("normal")) -> WeatherCondition:
    # mock 폴백 시 알 수 없는 시나리오는 400 (라이브에서는 scenario 무시하고 실측 반환)
    if not settings.live_weather and scenario not in WEATHER_SCENARIOS:
        raise HTTPException(status_code=400, detail=f"unknown scenario: {scenario}")
    return await get_current_weather(scenario)


@app.get("/api/bus/stops", response_model=list[BusStopArrivals], response_model_exclude_none=True)
def bus_stops() -> list[BusStopArrivals]:
    return BUS_STOP_LIST


@app.get(
    "/api/bus/arrivals/{stop_id}",
    response_model=BusStopArrivals,
    response_model_exclude_none=True,
)
def bus_arrivals(stop_id: str) -> BusStopArrivals:
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
async def routes_recommend(req: RecommendRequest) -> list[ScoredRoute]:
    """서버측 점수화 + 상위 N 추천(이유/주의/음성요약 포함)."""
    if settings.live_routes:
        try:
            candidates = await get_public_transit_candidates(req.origin, req.destination)
        except RuntimeError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
    else:
        candidates = get_route_candidates(req.origin, req.destination)
    weather = await get_current_weather(req.weather_scenario)
    return recommend_routes(candidates, weather, req.profile, req.options, top_n=req.top_n)
