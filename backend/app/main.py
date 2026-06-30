"""
FastAPI 앱. 프론트엔드가 mock 으로 쓰던 데이터(장소/경로/버스/날씨)를 REST API 로 제공하고,
서버측 점수화(recommend)도 함께 제공한다.

실행: uvicorn app.main:app --reload --port 8000
문서: http://localhost:8000/docs
"""
from __future__ import annotations

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from .config import ALLOWED_ORIGINS, DISTRICT
from .data.bus_arrivals import BUS_STOP_LIST, get_arrivals
from .data.places import search_places_by_name
from .data.routes import get_route_candidates
from .data.weather import WEATHER_SCENARIOS, get_weather
from .models import (
    BusStopArrivals,
    CandidatesRequest,
    Place,
    RecommendRequest,
    RouteCandidate,
    ScoredRoute,
    WeatherCondition,
)
from .scoring import recommend_routes

app = FastAPI(
    title="교통약자 접근성 경로 추천 API",
    description="부산진구 데모 · 보행/대중교통/저상버스/날씨 기반 자체 점수화",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok", "district": DISTRICT["name"]}


@app.get("/api/places/search", response_model=list[Place])
def places_search(q: str = Query("", description="장소 이름/주소 부분 검색")) -> list[Place]:
    return search_places_by_name(q)


@app.get("/api/weather", response_model=WeatherCondition)
def weather(scenario: str = Query("normal")) -> WeatherCondition:
    if scenario not in WEATHER_SCENARIOS:
        raise HTTPException(status_code=400, detail=f"unknown scenario: {scenario}")
    return get_weather(scenario)


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
def routes_candidates(req: CandidatesRequest) -> list[RouteCandidate]:
    """경로 후보 생성(점수화 전). 프론트엔드가 자체 점수화할 때 사용."""
    return get_route_candidates(req.origin, req.destination)


@app.post(
    "/api/routes/recommend",
    response_model=list[ScoredRoute],
    response_model_exclude_none=True,
)
def routes_recommend(req: RecommendRequest) -> list[ScoredRoute]:
    """서버측 점수화 + 상위 N 추천(이유/주의/음성요약 포함)."""
    candidates = get_route_candidates(req.origin, req.destination)
    weather = get_weather(req.weather_scenario)
    return recommend_routes(
        candidates, weather, req.profile, req.options, top_n=req.top_n
    )
