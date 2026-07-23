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
    get_ai_pipeline_candidates,
    get_ai_pipeline_routes,
    get_current_weather,
    get_bus_arrivals,
    search_bus_stops,
    search_places,
)
from .providers.ai_pipeline import AIProviderError
from .providers.vworld_buildings import get_vworld_buildings
from .rule_demo import personalize_and_sign, select_representative_routes
from .scoring import recommend_routes
from .shade import add_demo_shade, add_shade, assign_characteristics
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
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)

app.include_router(auth_router)
app.include_router(feedback_router)


async def _add_configured_shade(
    candidates: list[RouteCandidate],
    departure_at=None,
) -> list[RouteCandidate]:
    if not candidates:
        return candidates
    if settings.building_source == "demo":
        if settings.route_mode != "demo":
            return assign_characteristics(candidates)
        return assign_characteristics(add_demo_shade(candidates, departure_at))
    if not settings.live_buildings:
        raise HTTPException(
            status_code=503,
            detail="BUILDING_SOURCE=vworld requires VWORLD_API_KEY.",
        )
    try:
        buildings = await get_vworld_buildings(candidates)
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return assign_characteristics(add_shade(candidates, departure_at, buildings))


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok", "district": DISTRICT["name"], "sources": settings.active_sources()}


@app.get("/api/readiness")
def readiness() -> dict:
    """운영 필수 설정을 비밀값 없이 진단한다. 각 공급자의 실응답은 배포 스모크에서 검증한다."""
    checks = settings.deployment_readiness()
    missing = [name for name, configured in checks.items() if not configured]
    return {
        "ready": not missing,
        "environment": settings.app_env,
        "checks": checks,
        "missing": missing,
        "sources": settings.active_sources(),
    }


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
    """명시적으로 선택된 공급자만 사용하며 실패 시 다른 데이터로 바꾸지 않는다."""
    if settings.route_mode == "live":
        if not settings.live_routes:
            raise HTTPException(
                status_code=503,
                detail="ROUTE_MODE=live requires AI_SERVER_URL for geometry-rich candidates.",
            )
        try:
            candidates = await get_ai_pipeline_candidates(req.origin, req.destination)
        except AIProviderError as exc:
            raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
        return await _add_configured_shade(candidates)
    if settings.route_mode == "ai":
        raise HTTPException(
            status_code=503,
            detail="AI mode exposes ranked routes through /api/routes/recommend.",
        )
    candidates = get_route_candidates(req.origin, req.destination)
    return await _add_configured_shade(candidates)


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
    ROUTE_MODE에 따라 demo/live/ai 공급자를 명시적으로 선택한다.
    """
    if settings.route_mode == "ai":
        if not settings.live_ai_pipeline:
            raise HTTPException(status_code=503, detail="ROUTE_MODE=ai requires AI_SERVER_URL.")
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

    weather: WeatherCondition | None = None
    if settings.route_mode == "live":
        if not settings.live_routes:
            raise HTTPException(
                status_code=503,
                detail="ROUTE_MODE=live requires AI_SERVER_URL for geometry-rich candidates.",
            )
        try:
            current_weather = await get_current_weather(req.weather_scenario)
            weather = current_weather
            candidates = await get_ai_pipeline_candidates(
                req.origin,
                req.destination,
                req.profile,
                req.weather_scenario,
                req.options,
                user_preference=(user.preference if user else None),
                weather_condition=current_weather,
            )
        except AIProviderError as exc:
            raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    else:
        candidates = get_route_candidates(req.origin, req.destination)
        if not candidates:
            raise HTTPException(status_code=503, detail="고정 데모 OD 외 경로는 AI live pipeline이 필요합니다.")
    candidates = await _add_configured_shade(
        candidates, req.options.departure_at
    )
    if weather is None:
        try:
            weather = await get_current_weather(req.weather_scenario)
        except RuntimeError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
    scored = recommend_routes(
        candidates, weather, req.profile, req.options, top_n=len(candidates)
    )
    # demo와 live 모두 대표 규칙(빠른 길·완만한 길·그늘 많은 길)을 먼저 보장한다.
    # 각 대표 경로 안의 정렬은 같은 검증된 점수 엔진을 사용한다.
    selected = select_representative_routes(scored, req.top_n)
    try:
        return personalize_and_sign(
            selected,
            req.profile,
            user.preference.personalization_state if user and user.preference else None,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
