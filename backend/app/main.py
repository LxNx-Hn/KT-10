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
from threading import Lock
from datetime import datetime, timedelta
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
from .correlation import (
    CORRELATION_HEADER,
    correlation_id,
    normalize as normalize_correlation_id,
)
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
    RouteExplanationRequest,
    RouteExplanationResponse,
    RouteCandidate,
    RouteSetRescoreRequest,
    ScoredRoute,
    ShadeRefreshRequest,
    TransitArrivalsRequest,
    TransitArrivalsResponse,
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
from .providers.nim import NimExplanationError, explain_route
from .providers.transit_arrivals import get_route_transit_arrivals
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
from .wheelchair import effective_scoring_options, filter_known_stair_candidates

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
    version="2.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["*"],
    expose_headers=["X-Place-Search-Source", CORRELATION_HEADER],
)

@app.middleware("http")
async def attach_correlation_id(request, call_next):
    """요청 하나에서 발생한 Backend·AI·공급자 호출을 같은 ID로 묶는다."""
    value = normalize_correlation_id(request.headers.get(CORRELATION_HEADER))
    token = correlation_id.set(value)
    try:
        response = await call_next(request)
    finally:
        correlation_id.reset(token)
    response.headers[CORRELATION_HEADER] = value
    return response


app.include_router(auth_router)
app.include_router(feedback_router)


@app.post("/api/routes/explain", response_model=RouteExplanationResponse)
async def explain_selected_route(request: RouteExplanationRequest) -> RouteExplanationResponse:
    cached = route_set_cache.get(request.route_set_token)
    if cached is None:
        raise HTTPException(status_code=409, detail="경로 계산 정보가 만료되었습니다. 경로를 다시 검색해 주세요.")
    candidate = next((item for item in cached.candidates if item.id == request.route_id), None)
    if candidate is None:
        raise HTTPException(status_code=404, detail="선택한 경로를 찾을 수 없습니다.")
    try:
        explanation = await explain_route(candidate)
    except NimExplanationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return RouteExplanationResponse(route_id=candidate.id, explanation=explanation, provider="nvidia_nim")


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
    """건물 그늘 기하는 날씨·기온으로 차단하지 않는다.

    태양 고도, exact 보행 선형, 건물 데이터 가용성은
    ``calculate_shade``가 공개 상태와 함께 판정한다. 날씨는 열 스코어에만
    사용하고 건물 그늘 표시 가용성을 막지 않는다.
    """
    _ = weather, effective_at
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
    # 날씨는 추천 스코어에 사용하지만 건물 그늘 기하의
    # 가용성을 차단하지 않는다. 인자는 기존 API 계약으로 유지한다.
    _ = weather
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
    if total_buildings > 0 and known_heights <= 0:
        # 높이가 확인된 건물이 하나도 없으면 만들 그림자도 없다.
        # calculate_shade가 coverage gate에서 그림자 계산 없이
        # unavailable을 반환한다. 일부만 결측이면 확인된 건물로
        # lower_bound 그림자를 만든다.
        prepared_context = None
    else:
        prepared_context = await asyncio.to_thread(
            prepare_shade_context,
            pending,
            effective_at,
            buildings,
        )
    # Shapely union은 후보당 대규모 임시 geometry를 만든다. 5개
    # 후보를 동시 계산하면 ECS 메모리 피크가 후보 수만큼
    # 중첩되므로, 공유 전처리 context는 재사용하되 union은 직렬화한다.
    for candidate in pending:
        candidate.shade = await asyncio.to_thread(
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
    return assign_characteristics(candidates)



#: API 모델이 허용하고 공개 응답에 남길 수 있는 그늘 상태.
_DISPLAYABLE_SHADE_STATUSES = frozenset({
    "estimated_public",
    "estimated_demo",
    "not_daylight",
    "unavailable",
})


def _normalize_shade_for_response(
    candidates: list[RouteCandidate],
) -> list[RouteCandidate]:
    """알 수 없는 상태만 제거하고 계산 불가 사유는 공개 응답에 보존한다.

    ``unavailable``은 0%가 아니라 미계산 상태이며 ``calculationNote``로
    이유를 설명한다. 점수 계산은 기존처럼 확인된 estimated 상태만 사용한다.
    """
    for candidate in candidates:
        shade = candidate.shade
        if shade is not None and shade.status not in _DISPLAYABLE_SHADE_STATUSES:
            candidate.shade = None
    return candidates


def _create_cached_route_set(
    scored: list[ScoredRoute],
    candidates: list[RouteCandidate],
    weather: WeatherCondition,
    *,
    metadata: dict | None = None,
) -> list[ScoredRoute]:
    """새 검색에서만 새 route-set token을 발급한다."""
    route_set_token = route_set_cache.put(
        candidates,
        weather,
        metadata=metadata,
    )
    for item in scored:
        item.route_set_token = route_set_token
    _normalize_shade_for_response([item.route for item in scored])
    return scored


def _replace_cached_route_set(
    scored: list[ScoredRoute],
    candidates: list[RouteCandidate],
    weather: WeatherCondition,
    *,
    token: str,
    expected_revision: int | None = None,
) -> list[ScoredRoute]:
    """기존 route-set을 갱신한다. 실패를 새 token 발급으로 위장하지 않는다.

    만료되었거나 다른 갱신이 앞선 경우 409로 새 검색이 필요함을 알린다.
    """
    try:
        replaced = route_set_cache.replace(
            token,
            candidates,
            weather,
            expected_revision=expected_revision,
        )
    except StaleRouteSetRevision as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if not replaced:
        raise HTTPException(
            status_code=409,
            detail="경로 계산 정보가 만료되었습니다. 경로를 다시 검색해 주세요.",
        )
    for item in scored:
        item.route_set_token = token
    _normalize_shade_for_response([item.route for item in scored])
    return scored


#: 오류 분류별 재시도 대기시간(초). 영구 실패는 route-set 수명 동안 금지.
_REFINEMENT_COOLDOWN_SECONDS = {
    "timeout": 60,
    "network_error": 30,
    "upstream_5xx": 60,
}
_PERMANENT_REFINEMENT_FAILURES = frozenset({
    "auth_failed",
    "quota_exceeded",
    "invalid_response",
    "empty_geometry",
    "not_configured",
})


def _record_refinement_failure(
    candidate: RouteCandidate,
    exc: AIProviderError,
) -> None:
    """실패 분류와 재시도 가능 시각을 후보에 기록한다."""
    code = getattr(exc, "code", "provider_error")
    permanent = code in _PERMANENT_REFINEMENT_FAILURES or not getattr(
        exc, "retryable", True
    )
    now = datetime.now(KST)
    candidate.transit_refinement_state = "failed"
    candidate.transit_refinement_failure_code = code
    candidate.transit_refinement_failed_at = now
    candidate.transit_refinement_failure_permanent = permanent
    candidate.transit_refinement_failure_count += 1
    candidate.transit_refinement_retry_after = (
        None
        if permanent
        else now
        + timedelta(seconds=_REFINEMENT_COOLDOWN_SECONDS.get(code, 60))
    )


def _refinement_cooldown_response(candidate: RouteCandidate) -> None:
    """cooldown·영구 실패 상태면 외부 호출 없이 명시적 오류를 낸다."""
    if candidate.transit_refinement_state != "failed":
        return
    if candidate.transit_refinement_failure_permanent:
        raise HTTPException(
            status_code=409,
            detail=(
                "이 후보의 대중교통 정밀화는 현재 경로 정보로는 다시 "
                "시도할 수 없습니다. 경로를 다시 검색해 주세요."
            ),
        )
    retry_after = candidate.transit_refinement_retry_after
    if retry_after is None:
        return
    remaining = (retry_after - datetime.now(KST)).total_seconds()
    if remaining <= 0:
        return
    raise HTTPException(
        status_code=429,
        detail="대중교통 정밀화를 잠시 후 다시 시도할 수 있습니다.",
        headers={"Retry-After": str(max(1, int(remaining)))},
    )


_refinement_flights: dict[str, asyncio.Task] = {}
_refinement_flights_guard = Lock()


def _validated_refinement_candidate(cached, route_id: str) -> RouteCandidate:
    candidate = next(
        (item for item in cached.candidates if item.id == route_id),
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
    return candidate


def _refinement_response(candidate: RouteCandidate) -> TransitRefinementResponse:
    return TransitRefinementResponse(
        route_id=candidate.id,
        path=list(candidate.path or []),
        segments=list(candidate.segments),
        geometry_quality=candidate.geometry_quality or "mixed",
        refined_at=candidate.transit_refined_at,
    )


def _refinement_patch(refined: RouteCandidate):
    def _apply(target: RouteCandidate) -> None:
        target.path = refined.path
        target.segments = refined.segments
        target.geometry_quality = refined.geometry_quality
        target.transit_refinement_state = refined.transit_refinement_state
        target.transit_refined_at = refined.transit_refined_at
        # 성공하면 이전 실패 metadata를 지운다.
        target.transit_refinement_failure_code = None
        target.transit_refinement_failed_at = None
        target.transit_refinement_retry_after = None
        target.transit_refinement_failure_permanent = False
        target.transit_refinement_failure_count = 0

    return _apply


def _failure_patch(failed: RouteCandidate):
    def _mark_failed(target: RouteCandidate) -> None:
        target.transit_refinement_state = "failed"
        target.transit_refinement_failure_code = (
            failed.transit_refinement_failure_code
        )
        target.transit_refinement_failed_at = (
            failed.transit_refinement_failed_at
        )
        target.transit_refinement_retry_after = (
            failed.transit_refinement_retry_after
        )
        target.transit_refinement_failure_permanent = (
            failed.transit_refinement_failure_permanent
        )
        target.transit_refinement_failure_count = (
            failed.transit_refinement_failure_count
        )

    return _mark_failed


async def _single_flight_refinement(
    token: str,
    route_id: str,
    candidate: RouteCandidate,
) -> RouteCandidate:
    """같은 후보의 동시 정밀화 요청을 하나의 외부 호출로 합친다."""
    key = f"{token}\u001f{route_id}"

    async def _run() -> RouteCandidate:
        try:
            await refine_candidate_transit(candidate)
        except AIProviderError as exc:
            _record_refinement_failure(candidate, exc)
            route_set_cache.update_candidate(
                token,
                route_id,
                _failure_patch(candidate),
            )
            raise HTTPException(
                status_code=exc.status_code,
                detail=str(exc),
            ) from exc
        return candidate

    with _refinement_flights_guard:
        task = _refinement_flights.get(key)
        if task is None:
            task = asyncio.get_running_loop().create_task(_run())
            _refinement_flights[key] = task
            task.add_done_callback(
                lambda finished, flight_key=key: (
                    _refinement_flights.pop(flight_key, None)
                    if _refinement_flights.get(flight_key) is finished
                    else None
                )
            )
    return await asyncio.shield(task)


async def _rescore_cached_route_set(
    req: ShadeRefreshRequest,
    user: User | None,
    *,
    allow_vworld_cache_fill: bool,
) -> list[ScoredRoute]:
    """저장된 route-set만으로 그늘·순위를 다시 계산한다.

    같은 route-set의 refinement·다른 갱신과 토큰 잠금으로 직렬화해 서로의
    결과를 덮어쓰지 않는다. 새 ODsay·TMAP·고도 조회는 수행하지 않는다.
    출발 시각을 명시적으로 갱신하는 요청만 VWorld 건물 캐시 미스 회랑을
    채우며, 일반 프로필·조건 재채점은 기존 건물 캐시만 사용한다.
    """
    async with route_set_cache.lock_existing(req.route_set_token) as cached:
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
        rescore_weather = cached.weather
        if (
            isinstance(req, RouteSetRescoreRequest)
            and req.weather_scenario is not None
            and not settings.live_weather
        ):
            # 고정 시나리오는 공급자 호출 없이 바꿀 수 있다. live weather는
            # route-set 생성 시 저장한 실제 관측을 그대로 재사용한다.
            rescore_weather = WEATHER_SCENARIOS[
                req.weather_scenario
            ].model_copy(deep=True)
        user_preference = user.preference if user and user.preference else None
        effective_options = effective_scoring_options(req.options, user_preference)
        candidates = _filter_wheelchair_candidates(
            candidates,
            user,
            effective_options.uses_wheelchair,
        )
        try:
            candidates = await _add_configured_shade(
                candidates,
                req.options.departure_at,
                weather=rescore_weather,
                wait_for_buildings=allow_vworld_cache_fill,
                cache_only_buildings=not allow_vworld_cache_fill,
            )
            if settings.route_mode == "ai":
                rank_kwargs = {
                    "top_n": effective_top_n,
                    "personalization_state": (
                        user_preference.personalization_state
                        if user_preference
                        else None
                    ),
                }
                if user_preference is not None:
                    rank_kwargs["user_preference"] = user_preference
                scored = await rank_ai_pipeline_candidates(
                    candidates,
                    req.profile,
                    effective_options,
                    **rank_kwargs,
                )
                return _replace_cached_route_set(
                    scored,
                    candidates,
                    rescore_weather,
                    token=req.route_set_token,
                    expected_revision=cached.revision,
                )

            if settings.route_mode == "live":
                if user_preference is None:
                    await enrich_ai_pipeline_candidates(
                        candidates,
                        effective_options,
                    )
                else:
                    await enrich_ai_pipeline_candidates(
                        candidates,
                        effective_options,
                        user_preference,
                    )
            scored = recommend_routes(
                candidates,
                rescore_weather,
                req.profile,
                effective_options,
                top_n=len(candidates),
            )
            selected = select_representative_routes(scored, effective_top_n)
            personalized = personalize_and_sign(
                selected,
                req.profile,
                user.preference.personalization_state if user and user.preference else None,
                effective_options,
            )
            return _replace_cached_route_set(
                personalized,
                candidates,
                rescore_weather,
                token=req.route_set_token,
                expected_revision=cached.revision,
            )
        except StaleRouteSetRevision as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except AIProviderError as exc:
            raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc


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


# 정류장 사이가 이 거리를 넘는 대중교통 구간은 노선이 굽어 있고 경유
# 정류장도 여럿이라 좌표 2개로 표현될 수 없다.
_PLACEHOLDER_TRANSIT_MIN_DISTANCE_M = 1000.0
# 도로·선로를 따라가야 하는 모드만 검사한다. 항공·해상 구간은 두 점을 잇는
# 직선이 실제 경로이므로 정점이 2개인 것이 정상이다.
_NETWORK_BOUND_TRANSIT_MODES = frozenset(
    {"bus", "subway", "train", "express_bus"}
)


def _has_placeholder_transit_geometry(candidate: RouteCandidate) -> bool:
    """공급자가 양 끝점만으로 만들어낸 대중교통 구간이 있는지 본다."""
    for segment in candidate.segments:
        if segment.mode not in _NETWORK_BOUND_TRANSIT_MODES:
            continue
        if segment.path is not None and len(segment.path) > 2:
            continue
        distance = segment.distance_m or 0.0
        if distance > _PLACEHOLDER_TRANSIT_MIN_DISTANCE_M:
            return True
    return False


def _filter_placeholder_transit_candidates(
    candidates: list[RouteCandidate],
) -> list[RouteCandidate]:
    """자리표시자 대중교통 구간을 포함한 후보를 제외한다.

    공급자는 노선을 모르는 구간에도 출발·도착 좌표만으로 후보를 만든다.
    그 구간은 선형이 지형을 가로지르는 직선이고 거리·소요시간도 직선 기준
    이라 실제보다 짧게 보고된다. 같은 노선이 정상 선형으로 들어온 후보가
    따로 있으므로 이런 후보를 빼도 실제 이동 수단을 잃지 않는다.

    도보 상한·계단 필터와 달리 전부 걸러져도 오류로 만들지 않는다. 이건
    이용자 조건을 못 맞춘 것이 아니라 공급자 데이터 품질 문제이므로,
    남는 후보가 없으면 표시 품질 표기에 맡기고 원본을 그대로 둔다.
    """
    filtered = [
        candidate
        for candidate in candidates
        if not _has_placeholder_transit_geometry(candidate)
    ]
    if candidates and not filtered:
        log.warning(
            "모든 후보에 자리표시자 대중교통 선형이 있어 제외를 건너뜁니다."
        )
        return candidates
    return filtered


def _filter_wheelchair_candidates(
    candidates: list[RouteCandidate],
    user: User | None,
    request_uses_wheelchair: bool = False,
) -> list[RouteCandidate]:
    """계단과 휠체어 통행 제약이 검증된 후보만 제시한다."""
    preference = user.preference if user and user.preference else None
    filtered = filter_known_stair_candidates(
        candidates,
        preference,
        request_uses_wheelchair,
    )
    if candidates and not filtered:
        raise HTTPException(
            status_code=422,
            detail=(
                "휠체어 설정에서 계단·노면·폭·턱·경사 등 휠체어 통행 제약을 "
                "확인한 보행 경로를 수집하지 못했습니다."
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
        return _normalize_shade_for_response(
            await _add_configured_shade(
                _filter_viable_candidates(
                    _filter_placeholder_transit_candidates(candidates)
                ),
                wait_for_buildings=True,
            )
        )
    if settings.route_mode == "ai":
        raise HTTPException(
            status_code=503,
            detail="AI mode exposes ranked routes through /api/routes/recommend.",
        )
    candidates = get_route_candidates(req.origin, req.destination)
    return _normalize_shade_for_response(
        await _add_configured_shade(
            _filter_viable_candidates(
                _filter_placeholder_transit_candidates(candidates)
            )
        )
    )


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
    user_preference = user.preference if user and user.preference else None
    effective_options = effective_scoring_options(req.options, user_preference)
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
                effective_options,
                user_preference=user_preference,
                weather_condition=current_weather,
                candidate_limit=effective_top_n,
            )
            candidates = _filter_wheelchair_candidates(
                _filter_viable_candidates(
                    _filter_placeholder_transit_candidates(candidates)
                ),
                user,
                effective_options.uses_wheelchair,
            )
            candidates = await _add_configured_shade(
                candidates,
                effective_options.departure_at,
                weather=current_weather,
                # 새 회랑의 VWorld WFS 다운로드는 ALB 응답 제한보다 길 수
                # 있다. 초기 추천은 검증된 캐시만 즉시 결합하고 누락 회랑을
                # 비동기 예열한다. 프론트엔드는 route-set 생성 직후
                # refresh-shade를 호출해 같은 후보에 완성된 그늘을 반영한다.
                wait_for_buildings=False,
            )
            scored = await rank_ai_pipeline_candidates(
                candidates,
                req.profile,
                effective_options,
                top_n=effective_top_n,
                personalization_state=(
                    user.preference.personalization_state
                    if user and user.preference
                    else None
                ),
                user_preference=user_preference,
            )
            # 초기 추천은 선택된 대중교통 공급자의 후보 조회 한 번으로 끝낸다.
            # 선택 후보의 표시 선형과 NIM 자연어 설명은 각각 기존 지연
            # endpoint에서 요청하며, 여기서는 사실 기반 규칙 요약을 즉시 반환한다.
            return _create_cached_route_set(
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
                effective_options,
                user_preference=user_preference,
                weather_condition=current_weather,
                candidate_limit=effective_top_n,
            )
            candidates = _filter_wheelchair_candidates(
                _filter_viable_candidates(
                    _filter_placeholder_transit_candidates(candidates)
                ),
                user,
                effective_options.uses_wheelchair,
            )
        except AIProviderError as exc:
            raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    else:
        candidates = _filter_wheelchair_candidates(
            get_route_candidates(req.origin, req.destination),
            user,
            effective_options.uses_wheelchair,
        )
        if not candidates:
            raise HTTPException(status_code=503, detail="고정 데모 OD 외 경로는 AI live pipeline이 필요합니다.")
    candidates = await _add_configured_shade(
        candidates,
        effective_options.departure_at,
        weather=weather,
        # 초기 추천의 사용자 응답은 건물 회랑 콜드 다운로드에 묶지 않는다.
        # refresh-shade가 동일 route-set에서 누락 회랑만 동기 완성한다.
        wait_for_buildings=False,
    )
    if settings.route_mode == "live":
        try:
            await enrich_ai_pipeline_candidates(
                candidates,
                effective_options,
                user_preference,
            )
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
        candidates, weather, req.profile, effective_options, top_n=len(candidates)
    )
    # 대표 특성은 배지로만 보존하고 결과 순서는 프로필·이번 이동 조건의
    # 비교 적합 점수순으로 유지한다.
    selected = select_representative_routes(scored, effective_top_n)
    try:
        personalized = personalize_and_sign(
            selected,
            req.profile,
            user_preference.personalization_state if user_preference else None,
            effective_options,
        )
        # 초기 추천의 외부 경로 호출을 ODsay search 한 번으로 제한한다.
        # 선택 후보 정밀화와 NIM 설명은 지연 endpoint가 담당한다.
        return _create_cached_route_set(
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
    결과를 덮어쓰지 않는다. 새 ODsay·TMAP·고도 조회는 수행하지 않는다.
    VWorld 건물 회랑은 캐시를 우선 사용하고, 누락된 회랑만 동기 조회한다.
    """
    return await _rescore_cached_route_set(
        req,
        user,
        allow_vworld_cache_fill=True,
    )


@app.post(
    "/api/routes/rescore",
    response_model=list[ScoredRoute],
    response_model_exclude_none=True,
)
async def routes_rescore(
    req: RouteSetRescoreRequest,
    user: User | None = Depends(optional_current_user),
) -> list[ScoredRoute]:
    """프로필·이동 조건 변경을 기존 route-set 재순위화로 처리한다.

    후보 재수집 없이 저장된 후보 metadata·exact 보행 geometry·terrain·
    이미 정밀화된 대중교통 선형을 그대로 재사용한다. 대중교통 검색·정밀화
    공급자(TMAP 포함)와 고도 공급자 호출은 발생하지 않으며 route-set
    token도 바뀌지 않는다.

    새 추천 판단이므로 score·rank·model snapshot·feedback token·카드
    순서는 달라질 수 있다. 날씨는 route-set 생성 시점의 관측값을
    재사용하며 새 OpenWeather 호출을 만들지 않는다.
    """
    return await _rescore_cached_route_set(
        req,
        user,
        allow_vworld_cache_fill=False,
    )


@app.post(
    "/api/routes/transit-arrivals",
    response_model=TransitArrivalsResponse,
    response_model_exclude_none=True,
)
async def routes_transit_arrivals(
    req: TransitArrivalsRequest,
) -> TransitArrivalsResponse:
    """선택 후보의 도착정보만 지연 조회한다.

    초기 추천·재채점·출발시각 변경에는 호출되지 않는다. route-set 잠금은
    후보 복사까지만 유지하고 외부 BIMS/ODsay 시간표 요청은 잠금 밖에서
    수행한다. 공급자 모듈의 정류장·역 단위 TTL 캐시와 single-flight가
    동일 상세 요청의 중복 네트워크 호출을 합친다.
    """
    async with route_set_cache.lock_existing(req.route_set_token) as cached:
        if cached is None:
            raise HTTPException(
                status_code=409,
                detail="경로 계산 정보가 만료되었습니다. 경로를 다시 검색해 주세요.",
            )
        candidate = next(
            (item for item in cached.candidates if item.id == req.route_id),
            None,
        )
        if candidate is None:
            raise HTTPException(
                status_code=422,
                detail="요청한 경로가 이 route-set에 속하지 않습니다.",
            )
        segments = [segment.model_copy(deep=True) for segment in candidate.segments]

    return TransitArrivalsResponse(
        route_id=req.route_id,
        arrivals=await get_route_transit_arrivals(segments),
    )


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

    외부 공급자 호출은 route-set 전체 잠금 밖에서 수행한다. 서로 다른
    후보의 정밀화가 불필요하게 직렬화되지 않고, 같은 후보의 동시 요청만
    single-flight로 합쳐진다.
    """
    # 1) 짧은 잠금: 존재·소속·상태·cooldown 확인과 revision 캡처
    async with route_set_cache.lock_existing(req.route_set_token) as cached:
        if cached is None:
            raise HTTPException(
                status_code=409,
                detail="경로 계산 정보가 만료되었습니다. 경로를 다시 검색해 주세요.",
            )
        candidate = _validated_refinement_candidate(cached, req.route_id)
        if candidate.transit_refinement_state == "exact":
            return _refinement_response(candidate)
        _refinement_cooldown_response(candidate)
        pending = candidate.model_copy(deep=True)

    # 2) 잠금 밖에서 외부 호출. 같은 후보 동시 요청은 하나로 합친다.
    refined = await _single_flight_refinement(
        req.route_set_token,
        req.route_id,
        pending,
    )

    # 3) 짧은 잠금: 해당 후보만 원자적으로 patch
    updated = route_set_cache.update_candidate(
        req.route_set_token,
        req.route_id,
        _refinement_patch(refined),
    )
    if updated is None:
        # 응답이 늦게 도착했고 route-set이 이미 만료됐다면 결과를 버린다.
        raise HTTPException(
            status_code=409,
            detail="경로 계산 정보가 만료되었습니다. 경로를 다시 검색해 주세요.",
        )
    return _refinement_response(refined)


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
