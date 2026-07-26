"""
FastAPI 앱. 장소/경로/버스/날씨 데이터를 REST 로 제공하고 서버측 점수화(recommend)도 제공한다.

키가 없는 개발 모드는 명시적 데모 픽스처를 사용한다. 설정된 실공급자 실패는 오류로 반환한다.
실행: uvicorn app.main:app --reload --port 8000   ·   문서: /docs
"""
from __future__ import annotations

import asyncio
import hmac
import logging
from contextlib import asynccontextmanager
from datetime import datetime
from functools import partial

from fastapi import (
    Depends,
    FastAPI,
    Header,
    HTTPException,
    Path as ApiPath,
    Query,
    Response,
)
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
    ShadeRefreshRequest,
    TransitRefineRequest,
    TransitRefinementResponse,
    WeatherCondition,
)
from .providers import (
    enrich_ai_pipeline_candidates,
    get_ai_pipeline_candidates,
    rank_ai_pipeline_candidates,
    refine_candidate_transit,
    get_current_weather,
    get_bus_arrivals,
    search_bus_stops,
    search_places,
)
from .providers.ai_pipeline import AIProviderError
from .providers.vworld_buildings import get_vworld_buildings
from .rule_demo import personalize_and_sign, select_representative_routes
from .route_set_cache import StaleRouteSetRevision, route_set_cache
from .shade_cache import get_or_compute as get_or_compute_shade
from .shade_cache import read as read_shade_cache
from .scoring import recommend_routes
from .shade import (
    DEMO_BUILDING_DATA,
    KST,
    VWORLD_SHADE_SOURCE,
    add_demo_shade,
    assign_characteristics,
    building_height_counts,
    calculate_shade,
    prepare_shade_context,
    resolve_shade_without_buildings,
)
from .settings import settings

logging.basicConfig(level=logging.INFO)
# httpx의 INFO 요청 로그에는 공급자 키가 포함된 query string이 기록될 수 있다.
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
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
    expose_headers=["X-Place-Search-Source"],
)

app.include_router(auth_router)
app.include_router(feedback_router)


def _effective_departure(departure_at=None):
    effective_at = departure_at or datetime.now(KST)
    if effective_at.tzinfo is None:
        return effective_at.replace(tzinfo=KST)
    return effective_at.astimezone(KST)


def _effective_top_n(requested: int | None) -> int:
    """요청 topN이 없을 때만 서버 운영 기본값을 적용한다."""
    return requested if requested is not None else settings.route_default_top_n


def _shade_gate_reason(
    weather: WeatherCondition | None,
    effective_at: datetime,
) -> str | None:
    """VWorld 조회 전에 저비용으로 그늘 계산 필요성을 판정한다.

    None을 반환하면 계산을 진행하고, 사유 문자열을 반환하면 건물 조회와
    그림자 계산 없이 그늘을 생략(None)한다. 태양 고도와 exact 보행
    geometry는 이후 단계에서 검증한다.
    """
    if not 10 <= effective_at.hour < 18:
        return "departure-outside-10-18-kst"
    if weather is None:
        return "no-weather-context"
    observed_at = weather.observed_at
    air_observed_at = weather.air_quality_observed_at
    if (
        observed_at is None
        or observed_at.tzinfo is None
        or air_observed_at is None
        or air_observed_at.tzinfo is None
    ):
        return "invalid-weather-observation"
    ttl_seconds = settings.weather_cache_ttl_seconds
    if ttl_seconds <= 0:
        # 관측 유효기간을 정의할 수 없으면 현재 관측을 임의로 유효하다고
        # 가정하지 않는다.
        return "weather-validity-window-disabled"
    now = datetime.now(KST)
    observation_age = (now - observed_at.astimezone(KST)).total_seconds()
    if observation_age > ttl_seconds:
        return "weather-observation-expired"
    departure_offset = (
        effective_at - observed_at.astimezone(KST)
    ).total_seconds()
    if departure_offset > ttl_seconds:
        # 현재 관측값을 미래 예보처럼 사용하지 않는다.
        return "departure-beyond-observation-validity"
    if weather.feels_like_c is None or weather.feels_like_c < 25:
        return "feels-like-below-25"
    return None


def _has_reusable_shade(
    candidate: RouteCandidate,
    effective_at,
    *,
    data_quality: str,
) -> bool:
    shade = candidate.shade
    if (
        shade is None
        or shade.status not in {"estimated_public", "estimated_demo", "not_daylight"}
        or shade.data_quality != data_quality
    ):
        return False
    evaluated_at = shade.evaluated_at
    if evaluated_at.tzinfo is None:
        evaluated_at = evaluated_at.replace(tzinfo=KST)
    else:
        evaluated_at = evaluated_at.astimezone(KST)
    return evaluated_at == effective_at


async def _add_configured_shade(
    candidates: list[RouteCandidate],
    departure_at=None,
    *,
    weather: WeatherCondition | None = None,
    wait_for_buildings: bool = False,
    cache_only_buildings: bool = False,
) -> list[RouteCandidate]:
    if not candidates:
        return candidates
    # 한 후보군의 시간별 그늘은 정확히 같은 시각을 사용해야 학습·후기
    # 스냅샷이 경로마다 몇 마이크로초씩 달라지지 않는다.
    effective_at = _effective_departure(departure_at)
    if settings.building_source == "demo":
        pending = [
            candidate
            for candidate in candidates
            if not _has_reusable_shade(
                candidate,
                effective_at,
                data_quality="demo",
            )
        ]
        if not pending:
            return assign_characteristics(candidates)
        if resolve_shade_without_buildings(
            pending,
            effective_at,
            source=str(DEMO_BUILDING_DATA["source"]),
            data_quality="demo",
        ):
            log.info("야간 또는 계산 불가 경로: 데모 건물 조회·그림자 계산 생략")
            return assign_characteristics(candidates)
        add_demo_shade(pending, effective_at)
        return assign_characteristics(candidates)
    if not settings.live_buildings:
        raise HTTPException(
            status_code=503,
            detail="BUILDING_SOURCE=vworld requires VWORLD_API_KEY.",
        )
    gate_reason = _shade_gate_reason(weather, effective_at)
    if gate_reason is not None:
        # 그늘 없음은 0%가 아니라 미계산 상태다. VWorld 조회·그림자 생성·
        # 경로 교차 계산을 모두 생략하고 응답에서 shade를 생략한다.
        for candidate in candidates:
            candidate.shade = None
        log.info("그늘 계산 생략 (%s): VWorld 호출 0회", gate_reason)
        return assign_characteristics(candidates)
    cached_summaries = await asyncio.gather(*(
        asyncio.to_thread(
            read_shade_cache,
            candidate.id,
            effective_at,
        )
        for candidate in candidates
    ))
    for candidate, cached_summary in zip(
        candidates,
        cached_summaries,
        strict=True,
    ):
        if cached_summary is not None:
            candidate.shade = cached_summary
    pending = [
        candidate
        for candidate in candidates
        if not _has_reusable_shade(
            candidate,
            effective_at,
            data_quality="public",
        )
    ]
    if not pending:
        return assign_characteristics(candidates)
    if resolve_shade_without_buildings(
        pending,
        effective_at,
        source=VWORLD_SHADE_SOURCE,
        data_quality="public",
    ):
        log.info("야간 또는 계산 불가 경로: VWorld 건물 조회·그림자 계산 생략")
        return assign_characteristics(candidates)
    try:
        buildings = await get_vworld_buildings(
            pending,
            wait_for_complete=wait_for_buildings,
            cache_only=cache_only_buildings,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    known_heights, total_buildings = building_height_counts(buildings)
    if total_buildings > 0 and known_heights < total_buildings:
        # 관련 건물 높이가 불완전하면 그림자 폴리곤을 만들지 않는다.
        # calculate_shade가 coverage gate에서 그림자 계산 없이
        # unavailable을 반환한다.
        prepared_context = None
    else:
        prepared_context = await asyncio.to_thread(
            prepare_shade_context,
            pending,
            effective_at,
            buildings,
        )
    summaries = await asyncio.gather(*(
        asyncio.to_thread(
            get_or_compute_shade,
            candidate.id,
            effective_at,
            partial(
                calculate_shade,
                candidate,
                effective_at,
                buildings,
                prepared_context=prepared_context,
            ),
        )
        for candidate in pending
    ))
    for candidate, summary in zip(
        pending,
        summaries,
        strict=True,
    ):
        candidate.shade = summary
    return assign_characteristics(candidates)


def _cache_scored_routes(
    scored: list[ScoredRoute],
    candidates: list[RouteCandidate],
    weather: WeatherCondition,
    *,
    token: str | None = None,
    expected_revision: int | None = None,
    metadata: dict | None = None,
) -> list[ScoredRoute]:
    if token is not None and route_set_cache.replace(
        token,
        candidates,
        weather,
        expected_revision=expected_revision,
    ):
        route_set_token = token
    else:
        route_set_token = route_set_cache.put(
            candidates,
            weather,
            metadata=metadata,
        )
    for item in scored:
        item.route_set_token = route_set_token
    return scored


def _route_set_metadata(
    *,
    requested_top_n: int | None,
    effective_top_n: int,
    candidates: list[RouteCandidate],
) -> dict:
    return {
        "originalRequestedTopN": requested_top_n,
        "effectiveTopN": effective_top_n,
        "collectedCandidateCount": len(candidates),
        "routeDefaultTopNAtCreation": settings.route_default_top_n,
    }


async def _refine_top_ranked_transit(scored: list[ScoredRoute]) -> None:
    """최종 1위 후보의 대중교통 표시 선형만 최초 1회 정밀화한다.

    실패 정책 B: 기존 UI가 estimated geometry를 점선과 품질 라벨로 구분해
    표시하므로, 1위 정밀화 실패는 estimated 상태의 부분 성공으로 반환하고
    오류는 로그·계측에만 기록한다. 가짜 exact geometry는 만들지 않는다.
    """
    if not scored:
        return
    top = scored[0].route
    if top.transit_refinement_state == "exact":
        return
    try:
        await refine_candidate_transit(top)
    except AIProviderError as exc:
        top.transit_refinement_state = "failed"
        log.warning(
            "최초 1위 대중교통 정밀화 실패(HTTP %s): estimated 선형으로 응답",
            exc.status_code,
        )


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
async def places_search(
    response: Response,
    q: str = Query(
        "",
        max_length=100,
        description="장소 이름/주소 검색",
    ),
) -> list[Place]:
    response.headers["X-Place-Search-Source"] = (
        "kakao-rest" if settings.live_places else "demo"
    )
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
async def bus_stops(
    q: str = Query(
        "",
        max_length=100,
        description="정류소명 또는 5자리 ARS 번호",
    ),
) -> list[BusStopArrivals]:
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
async def bus_arrivals(
    stop_id: str = ApiPath(min_length=1, max_length=64),
) -> BusStopArrivals:
    if settings.live_bus:
        try:
            return await get_bus_arrivals(stop_id)
        except RuntimeError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
    stop = get_arrivals(stop_id)
    if stop is None:
        raise HTTPException(status_code=404, detail="stop not found")
    return stop


def _filter_viable_candidates(candidates: list[RouteCandidate]) -> list[RouteCandidate]:
    """총 도보거리 상한을 모든 경로 유형에 동일하게 적용한다."""
    filtered = [
        candidate
        for candidate in candidates
        if candidate.total_walk_m <= settings.max_supported_total_walk_m
    ]
    if candidates and not filtered:
        raise HTTPException(
            status_code=422,
            detail=(
                "지원하는 총 도보거리 "
                f"{settings.max_supported_total_walk_m}m 이내의 경로가 없습니다."
            ),
        )
    return filtered


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
        return await _add_configured_shade(
            _filter_viable_candidates(candidates),
            wait_for_buildings=True,
        )
    if settings.route_mode == "ai":
        raise HTTPException(
            status_code=503,
            detail="AI mode exposes ranked routes through /api/routes/recommend.",
        )
    candidates = get_route_candidates(req.origin, req.destination)
    return await _add_configured_shade(_filter_viable_candidates(candidates))


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
    requested_top_n = req.top_n
    effective_top_n = _effective_top_n(requested_top_n)
    if settings.route_mode == "ai":
        if not settings.live_ai_pipeline:
            raise HTTPException(status_code=503, detail="ROUTE_MODE=ai requires AI_SERVER_URL.")
        try:
            current_weather = await get_current_weather(req.weather_scenario)
            candidates = await get_ai_pipeline_candidates(
                req.origin,
                req.destination,
                req.profile,
                req.weather_scenario,
                req.options,
                user_preference=(user.preference if user else None),
                weather_condition=current_weather,
                candidate_limit=effective_top_n,
            )
            candidates = _filter_viable_candidates(candidates)
            candidates = await _add_configured_shade(
                candidates,
                req.options.departure_at,
                weather=current_weather,
                wait_for_buildings=True,
            )
            scored = await rank_ai_pipeline_candidates(
                candidates,
                req.profile,
                req.options,
                top_n=effective_top_n,
                personalization_state=(
                    user.preference.personalization_state
                    if user and user.preference
                    else None
                ),
            )
            # 순위·score·snapshot 확정 후 최종 1위 표시 선형만 정밀화한다.
            await _refine_top_ranked_transit(scored)
            return _cache_scored_routes(
                scored,
                candidates,
                current_weather,
                metadata=_route_set_metadata(
                    requested_top_n=requested_top_n,
                    effective_top_n=effective_top_n,
                    candidates=candidates,
                ),
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
                candidate_limit=effective_top_n,
            )
            candidates = _filter_viable_candidates(candidates)
        except AIProviderError as exc:
            raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    else:
        candidates = get_route_candidates(req.origin, req.destination)
        if not candidates:
            raise HTTPException(status_code=503, detail="고정 데모 OD 외 경로는 AI live pipeline이 필요합니다.")
    candidates = await _add_configured_shade(
        candidates,
        req.options.departure_at,
        weather=weather,
        wait_for_buildings=(settings.route_mode == "live"),
    )
    if settings.route_mode == "live":
        try:
            await enrich_ai_pipeline_candidates(candidates, req.options)
        except AIProviderError as exc:
            raise HTTPException(
                status_code=exc.status_code,
                detail=str(exc),
            ) from exc
    if weather is None:
        try:
            weather = await get_current_weather(req.weather_scenario)
        except RuntimeError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
    scored = recommend_routes(
        candidates, weather, req.profile, req.options, top_n=len(candidates)
    )
    # 대표 특성은 배지로만 보존하고 결과 순서는 프로필·이번 이동 조건의
    # 비교 적합 점수순으로 유지한다.
    selected = select_representative_routes(scored, effective_top_n)
    try:
        personalized = personalize_and_sign(
            selected,
            req.profile,
            user.preference.personalization_state if user and user.preference else None,
            req.options,
        )
        if settings.route_mode == "live":
            await _refine_top_ranked_transit(personalized)
        return _cache_scored_routes(
            personalized,
            candidates,
            weather,
            metadata=_route_set_metadata(
                requested_top_n=requested_top_n,
                effective_top_n=effective_top_n,
                candidates=candidates,
            ),
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.post(
    "/api/routes/refresh-shade",
    response_model=list[ScoredRoute],
    response_model_exclude_none=True,
)
async def routes_refresh_shade(
    req: ShadeRefreshRequest,
    user: User | None = Depends(optional_current_user),
) -> list[ScoredRoute]:
    """기존 서버 후보로 시각별 그늘만 갱신하고 동일 후보군을 재순위화한다.

    같은 route-set의 refinement·다른 갱신과 토큰 잠금으로 직렬화해 서로의
    결과를 덮어쓰지 않는다. 새 ODsay·TMAP·VWorld corridor·고도 조회는
    수행하지 않는다.
    """
    async with route_set_cache.token_lock(req.route_set_token):
        cached = route_set_cache.get(req.route_set_token)
        if cached is None:
            raise HTTPException(
                status_code=409,
                detail="경로 계산 정보가 만료되었습니다. 경로를 다시 검색해 주세요.",
            )
        stored_effective = cached.metadata.get("effectiveTopN")
        effective_top_n = (
            req.top_n
            if req.top_n is not None
            else stored_effective
            if isinstance(stored_effective, int)
            else settings.route_default_top_n
        )
        if effective_top_n > len(cached.candidates):
            # 기존 route-set이 수집한 후보 수를 넘는 topN은 새 후보를
            # 조용히 만들지 않고 새 검색을 명시적으로 요구한다.
            raise HTTPException(
                status_code=409,
                detail=(
                    f"이 route-set은 후보 {len(cached.candidates)}개로 "
                    f"생성되었습니다. 후보 {effective_top_n}개가 필요하면 "
                    "경로를 다시 검색해 주세요."
                ),
            )

        candidates = cached.candidates
        try:
            candidates = await _add_configured_shade(
                candidates,
                req.options.departure_at,
                weather=cached.weather,
                cache_only_buildings=True,
            )
            if settings.route_mode == "ai":
                scored = await rank_ai_pipeline_candidates(
                    candidates,
                    req.profile,
                    req.options,
                    top_n=effective_top_n,
                    personalization_state=(
                        user.preference.personalization_state
                        if user and user.preference
                        else None
                    ),
                )
                return _cache_scored_routes(
                    scored,
                    candidates,
                    cached.weather,
                    token=req.route_set_token,
                    expected_revision=cached.revision,
                )

            if settings.route_mode == "live":
                await enrich_ai_pipeline_candidates(candidates, req.options)
            scored = recommend_routes(
                candidates,
                cached.weather,
                req.profile,
                req.options,
                top_n=len(candidates),
            )
            selected = select_representative_routes(scored, effective_top_n)
            personalized = personalize_and_sign(
                selected,
                req.profile,
                user.preference.personalization_state if user and user.preference else None,
                req.options,
            )
            return _cache_scored_routes(
                personalized,
                candidates,
                cached.weather,
                token=req.route_set_token,
                expected_revision=cached.revision,
            )
        except StaleRouteSetRevision as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except AIProviderError as exc:
            raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.post(
    "/api/routes/refine-transit",
    response_model=TransitRefinementResponse,
    response_model_exclude_none=True,
)
async def routes_refine_transit(
    req: TransitRefineRequest,
) -> TransitRefinementResponse:
    """기존 추천 카드에서 선택한 후보의 대중교통 표시 선형만 정밀화한다.

    ODsay search·전체 recommend·score 재계산은 수행하지 않으며, route ID·
    카드 순서·model snapshot·feedback token은 변경하지 않는다. 이미
    정밀화된 후보 재선택은 캐시를 재사용해 외부 호출을 만들지 않는다.
    """
    async with route_set_cache.token_lock(req.route_set_token):
        cached = route_set_cache.get(req.route_set_token)
        if cached is None:
            raise HTTPException(
                status_code=409,
                detail="경로 계산 정보가 만료되었습니다. 경로를 다시 검색해 주세요.",
            )
        candidate = next(
            (
                item
                for item in cached.candidates
                if item.id == req.route_id
            ),
            None,
        )
        if candidate is None:
            raise HTTPException(
                status_code=422,
                detail="요청한 경로가 이 route-set에 속하지 않습니다.",
            )
        if candidate.path is None or len(candidate.path) < 2:
            raise HTTPException(
                status_code=409,
                detail="이 후보는 대중교통 정밀화를 지원하지 않습니다.",
            )
        if candidate.transit_refinement_state != "exact":
            try:
                await refine_candidate_transit(candidate)
            except AIProviderError as exc:
                route_set_cache.update_candidate(
                    req.route_set_token,
                    req.route_id,
                    lambda target: setattr(
                        target, "transit_refinement_state", "failed"
                    ),
                )
                raise HTTPException(
                    status_code=exc.status_code,
                    detail=str(exc),
                ) from exc
            refined = candidate.model_copy(deep=True)

            def _apply(target: RouteCandidate) -> None:
                target.path = refined.path
                target.segments = refined.segments
                target.geometry_quality = refined.geometry_quality
                target.transit_refinement_state = (
                    refined.transit_refinement_state
                )
                target.transit_refined_at = refined.transit_refined_at

            updated = route_set_cache.update_candidate(
                req.route_set_token,
                req.route_id,
                _apply,
            )
            if updated is None:
                raise HTTPException(
                    status_code=409,
                    detail="경로 계산 정보가 만료되었습니다. 경로를 다시 검색해 주세요.",
                )
        return TransitRefinementResponse(
            route_id=candidate.id,
            path=list(candidate.path or []),
            segments=list(candidate.segments),
            geometry_quality=candidate.geometry_quality or "mixed",
            refined_at=candidate.transit_refined_at,
        )


@app.post("/api/routes/labeling-candidates")
async def routes_labeling_candidates(
    req: RecommendRequest,
    labeling_token: str | None = Header(
        default=None,
        alias="X-Labeling-Token",
    ),
) -> dict:
    """추천과 동일한 수집·그늘 결합 경로로 학습용 고정 후보를 만든다."""
    if (
        len(settings.labeling_api_token) < 32
        or labeling_token is None
        or not hmac.compare_digest(labeling_token, settings.labeling_api_token)
    ):
        raise HTTPException(
            status_code=403,
            detail="Valid labeling batch credentials are required.",
        )
    if not settings.live_ai_pipeline:
        raise HTTPException(
            status_code=503,
            detail="ROUTE_MODE=ai and AI_SERVER_URL are required for labeling candidates.",
        )
    try:
        current_weather = await get_current_weather(req.weather_scenario)
        candidates = await get_ai_pipeline_candidates(
            req.origin,
            req.destination,
            req.profile,
            req.weather_scenario,
            req.options,
            weather_condition=current_weather,
            candidate_limit=_effective_top_n(req.top_n),
        )
        candidates = await _add_configured_shade(
            candidates,
            req.options.departure_at,
            weather=current_weather,
            wait_for_buildings=True,
        )
        bundle = await enrich_ai_pipeline_candidates(candidates, req.options)
    except AIProviderError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    rows = []
    for route in candidates:
        segment_distances = [segment.distance_m for segment in route.segments]
        total_distance_m = (
            sum(float(value) for value in segment_distances)
            if segment_distances and all(value is not None for value in segment_distances)
            else None
        )
        rows.append({
            "route_id": route.id,
            "summary": route.summary,
            "duration_min": route.total_duration_min,
            "distance_m": total_distance_m,
            "sources": bundle.snapshots[route.id]["sources"],
            "geometry_quality": route.geometry_quality,
            "path": [
                point.model_dump(mode="json", by_alias=False)
                for point in (route.path or [])
            ],
            "segments": [
                segment.model_dump(
                    mode="json",
                    by_alias=False,
                    exclude_none=True,
                )
                for segment in route.segments
            ],
            "features": route.model_features,
            "feature_snapshot": bundle.snapshots[route.id],
            "trait_labels": bundle.traits[route.id],
        })
    return {
        "group_id": bundle.group_id,
        "candidates": rows,
        "metadata": {
            "captured_at": bundle.captured_at,
            "shade_evaluated_at": bundle.shade_evaluated_at,
            "weather": req.weather_scenario,
            "building_source": settings.building_source,
        },
    }
