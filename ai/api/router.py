"""경로 수집·피처 추출·학습 모델 순위화를 제공하는 AI API."""
from __future__ import annotations

import asyncio
import copy
import hashlib
import json
import logging
import math
import re
from datetime import UTC, datetime
from threading import Lock
from typing import Any, Literal

import hmac
from pyproj import Transformer

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field

from collectors.base import (
    CollectorError,
    CollectorNotConfigured,
    Coordinate,
)
from collectors.odsay_collector import OdsayRouteCollector
from collectors.ors_collector import OrsWheelchairRouteCollector
from collectors.odsay_instrumentation import (
    adopt_correlation_id,
    log_rank,
    provider_candidate_index,
    route_id_hash,
)
from collectors.tmap_collector import TmapRouteCollector
from config import settings
from features.extractor import (
    extract_route_features_for_parts,
    prepare_spatial_layers,
)
from features.elevation import extract_elevation_features_for_parts
from features.route_feature_cache import (
    cache_identity as route_feature_cache_identity,
    read as read_route_feature_cache,
    request_lock as route_feature_request_lock,
    write as write_route_feature_cache,
)
from labeling.route_traits import generate_route_traits
from merger.route_merger import merge_route_candidates, sample_path_by_distance
from preprocessing.load_layers import load_all_layers
from scoring.bootstrap_baseline import (
    load_bootstrap_baseline_metadata,
    load_bootstrap_baseline_rankers,
)
from scoring.predict import predict_and_rank
from scoring.schema import AUXILIARY_FEATURE_COLS, validate_feature_values
from scoring.snapshots import build_live_feature_snapshot
from scoring.train import FEATURE_COLS, ModelNotReady, load_model_metadata, load_rankers

INTERNAL_TOKEN_HEADER = "X-KT10-Internal-Token"
CORRELATION_HEADER = "X-Correlation-ID"


async def adopt_request_correlation_id(
    value: str | None = Header(default=None, alias=CORRELATION_HEADER),
) -> str:
    """Backend 요청의 correlation ID를 AI 호출 계측에 이어붙인다.

    ContextVar를 endpoint와 같은 실행 컨텍스트에서 설정해야 하므로
    동기 함수(threadpool 실행)로 두지 않는다.
    """
    return adopt_correlation_id(value)


def require_internal_token(
    internal_token: str | None = Header(default=None, alias=INTERNAL_TOKEN_HEADER),
) -> None:
    """Backend 전용 endpoint를 내부 토큰으로 보호한다.

    토큰 값은 로그·응답 어디에도 남기지 않는다. production에서 토큰이
    설정되지 않았다면 열린 상태로 두지 않고 명시적으로 거부한다.
    """
    expected = settings.AI_INTERNAL_SERVICE_TOKEN.strip()
    if not expected:
        if settings.APP_ENV == "production":
            raise HTTPException(
                status_code=503,
                detail="AI_INTERNAL_SERVICE_TOKEN is not configured.",
            )
        # 개발·테스트 환경은 토큰 없이 동작할 수 있다.
        return
    if internal_token is None or not hmac.compare_digest(
        internal_token,
        expected,
    ):
        raise HTTPException(
            status_code=403,
            detail="Valid internal service credentials are required.",
        )


router = APIRouter(dependencies=[
    Depends(require_internal_token),
    Depends(adopt_request_correlation_id),
])

_layers = None
_rankers = None
_layers_lock = Lock()
log = logging.getLogger("api.router")
_WGS84_TO_METRIC = Transformer.from_crs(
    "EPSG:4326",
    "EPSG:5179",
    always_xy=True,
)


def _get_layers():
    global _layers
    if _layers is None:
        with _layers_lock:
            if _layers is None:
                _layers = prepare_spatial_layers(
                    load_all_layers(use_cache=True)
                )
    return _layers


def _get_rankers():
    global _rankers
    if _rankers is None:
        _rankers = (
            load_bootstrap_baseline_rankers()
            if settings.RANKER_TIER == "bootstrap_baseline"
            else load_rankers()
        )
    return _rankers


def _get_model_metadata() -> dict:
    return (
        load_bootstrap_baseline_metadata()
        if settings.RANKER_TIER == "bootstrap_baseline"
        else load_model_metadata()
    )


Profile = Literal["general", "elderly", "child", "youth", "disabled", "pregnant"]
Weather = Literal["normal", "heatwave", "coldwave", "rain", "bad_air"]


class RecommendRequest(BaseModel):
    origin_lat: float = Field(ge=34.8, le=35.5)
    origin_lng: float = Field(ge=128.7, le=129.4)
    origin_name: str = Field(min_length=1, max_length=200)
    dest_lat: float = Field(ge=34.8, le=35.5)
    dest_lng: float = Field(ge=128.7, le=129.4)
    dest_name: str = Field(min_length=1, max_length=200)
    profile: Profile
    weather: Weather = "normal"
    prioritize_weather_safety: bool = False
    carry_luggage: bool = False
    stroller: bool = False
    shade_priority: bool = False
    minimize_transfers: bool = False
    avoid_stairs: bool = False
    low_floor_priority: bool = False
    uses_wheelchair: bool = False
    uses_walking_aid: bool = False
    max_walk_distance_m: int | None = Field(default=None, ge=100, le=15000)
    candidate_limit: int = Field(default=5, ge=1, le=10)
    temp_c: float | None = Field(default=None, ge=-60, le=60)
    feels_like_c: float | None = Field(default=None, ge=-80, le=80)
    precipitation_mm: float | None = Field(default=None, ge=0)
    wind_ms: float | None = Field(default=None, ge=0)
    pm10: float | None = Field(default=None, ge=0)


class RankCandidate(BaseModel):
    route_id: str = Field(min_length=1, max_length=200)
    features: dict[str, Any]


class RankCandidatesRequest(BaseModel):
    profile: Profile
    candidates: list[RankCandidate] = Field(min_length=1, max_length=50)


class EnrichedSnapshotCandidate(BaseModel):
    route_id: str = Field(min_length=1, max_length=200)
    base_snapshot_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    sources: list[str] = Field(min_length=1)
    geometry_quality: Literal["exact", "mixed", "estimated"]
    features: dict[str, Any]


class EnrichedSnapshotsRequest(BaseModel):
    base_group_id: str = Field(min_length=1, max_length=200)
    holdout_group_id: str = Field(min_length=1, max_length=200)
    captured_at: datetime
    shade_evaluated_at: datetime
    candidates: list[EnrichedSnapshotCandidate] = Field(min_length=1, max_length=50)


def _validated_feature_row(
    route_id: str,
    features: dict[str, Any],
    *,
    include_auxiliary: bool = False,
) -> dict[str, float | int | bool | None]:
    missing = [name for name in FEATURE_COLS if name not in features]
    if missing:
        raise HTTPException(
            status_code=422,
            detail={
                "message": "순위화 피처가 누락되었습니다.",
                "route_id": route_id,
                "missing": missing,
            },
        )
    columns = [
        *FEATURE_COLS,
        *(
            name
            for name in AUXILIARY_FEATURE_COLS
            if include_auxiliary and name in features
        ),
    ]
    row: dict[str, float | int | bool | None] = {}
    for name in columns:
        value = features[name]
        if value is not None and (
            isinstance(value, str)
            or not isinstance(value, (int, float, bool))
            or (
                isinstance(value, (int, float))
                and not isinstance(value, bool)
                and not math.isfinite(float(value))
            )
        ):
            raise HTTPException(
                status_code=422,
                detail=f"{route_id}: {name}은 유한한 숫자, boolean 또는 null이어야 합니다.",
            )
        row[name] = value
    try:
        validate_feature_values(row, columns)
    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail=f"{route_id}: {exc}",
        ) from exc
    return row


@router.post("/labeling/enriched-snapshots")
def enriched_snapshots(req: EnrichedSnapshotsRequest) -> dict:
    """건물 그늘이 결합된 피처의 고정 스냅샷과 사실 라벨을 만든다."""
    if req.captured_at.tzinfo is None or req.shade_evaluated_at.tzinfo is None:
        raise HTTPException(
            status_code=422,
            detail="captured_at과 shade_evaluated_at에는 UTC 오프셋이 필요합니다.",
        )
    route_ids = [candidate.route_id for candidate in req.candidates]
    if len(set(route_ids)) != len(route_ids):
        raise HTTPException(status_code=422, detail="route_id는 후보군에서 고유해야 합니다.")

    fixed_captured_at = req.captured_at.astimezone(UTC).isoformat()
    fixed_shade_at = req.shade_evaluated_at.astimezone(UTC).isoformat()
    validated: list[
        tuple[EnrichedSnapshotCandidate, dict[str, float | int | bool | None]]
    ] = []
    for candidate in req.candidates:
        if any(not source.strip() for source in candidate.sources):
            raise HTTPException(
                status_code=422,
                detail=f"{candidate.route_id}: sources에는 빈 문자열을 넣을 수 없습니다.",
            )
        validated.append((
            candidate,
            _validated_feature_row(
                candidate.route_id,
                candidate.features,
                include_auxiliary=True,
            ),
        ))

    context = {
        "base_group_id": req.base_group_id,
        "holdout_group_id": req.holdout_group_id,
        "captured_at": fixed_captured_at,
        "shade_evaluated_at": fixed_shade_at,
        "candidates": [
            {
                "route_id": candidate.route_id,
                "base_snapshot_hash": candidate.base_snapshot_hash,
                "sources": sorted(set(candidate.sources)),
                "geometry_quality": candidate.geometry_quality,
                "features": features,
            }
            for candidate, features in sorted(
                validated,
                key=lambda item: item[0].route_id,
            )
        ],
    }
    digest = hashlib.sha256(
        json.dumps(
            context,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()
    group_id = f"enriched-{digest[:20]}"
    snapshots = [
        build_live_feature_snapshot(
            group_id=group_id,
            route_id=candidate.route_id,
            features=features,
            sources=list(dict.fromkeys(candidate.sources)),
            geometry_quality=candidate.geometry_quality,
            captured_at=fixed_captured_at,
            holdout_group_id=req.holdout_group_id,
            shade_evaluated_at=fixed_shade_at,
        )
        for candidate, features in validated
    ]
    traits = generate_route_traits(snapshots)
    return {
        "group_id": group_id,
        "captured_at": fixed_captured_at,
        "shade_evaluated_at": fixed_shade_at,
        "candidates": [
            {
                "route_id": snapshot["route_id"],
                "feature_snapshot": snapshot,
                "trait_labels": traits[str(snapshot["route_id"])],
            }
            for snapshot in snapshots
        ],
    }


@router.get("/model/status")
def model_status() -> dict:
    """키나 라벨 내용을 노출하지 않고 명시적으로 선택한 모델 준비 상태만 반환한다."""
    try:
        profiles = sorted(_get_rankers())
        metadata = _get_model_metadata()
    except ModelNotReady as exc:
        return {
            "ready": False,
            "configured_tier": settings.RANKER_TIER,
            "profiles": [],
            "detail": str(exc),
        }
    return {
        "ready": True,
        "configured_tier": settings.RANKER_TIER,
        "profiles": profiles,
        **metadata,
    }


@router.post("/rank/candidates")
def rank_candidates(req: RankCandidatesRequest) -> dict:
    """백엔드가 건물 그늘까지 결합한 고정 후보 피처만 순위화한다."""
    try:
        rankers = _get_rankers()
        metadata = _get_model_metadata()
    except ModelNotReady as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    if req.profile not in rankers:
        raise HTTPException(
            status_code=503,
            detail=f"{req.profile} 프로필의 선택된 모델이 없습니다.",
        )
    route_ids = [candidate.route_id for candidate in req.candidates]
    if len(set(route_ids)) != len(route_ids):
        raise HTTPException(status_code=422, detail="route_id는 후보군에서 고유해야 합니다.")

    feature_rows = [
        _validated_feature_row(candidate.route_id, candidate.features)
        for candidate in req.candidates
    ]

    ranked = predict_and_rank(
        rankers,
        feature_rows,
        req.profile,
        top_k=len(feature_rows),
    )
    for item in ranked:
        log_rank(
            route_ids[item["route_index"]],
            int(item["rank"]),
        )
    return {
        "ranked": [
            {
                "route_id": route_ids[item["route_index"]],
                "rank": item["rank"],
                "model_score": item["xgb_score"],
                "relative_fit_score": item["relative_fit_score"],
                # 운영 진단용이며 UI에는 노출하지 않는다.
                "selection_probability": item["probability"],
            }
            for item in ranked
        ],
        "metadata": {
            "model_tier": metadata.get("model_tier"),
            "model_version": metadata.get("model_version"),
            "label_origin": metadata.get("label_origin"),
        },
    }


class RefineTransitRequest(BaseModel):
    """백엔드 내부 refinement 서술자. 프론트엔드에 노출되지 않는다."""

    origin_lat: float = Field(ge=34.8, le=35.5)
    origin_lng: float = Field(ge=128.7, le=129.4)
    dest_lat: float = Field(ge=34.8, le=35.5)
    dest_lng: float = Field(ge=128.7, le=129.4)
    map_object: str = Field(min_length=1, max_length=8000)
    route_id: str | None = Field(default=None, min_length=1, max_length=200)
    provider_candidate_index: int | None = Field(default=None, ge=1)


@router.post("/routes/refine-transit")
async def refine_transit(req: RefineTransitRequest) -> dict:
    """선택된 후보 하나의 대중교통 정밀 선형(loadLane)만 조회한다.

    검색·후보 재수집·순위화를 다시 실행하지 않으며, 실패는 정상 geometry로
    위장하지 않고 명시적 오류로 반환한다.
    """
    collector = OdsayRouteCollector()
    route_token = route_id_hash.set(
        hashlib.sha256(req.route_id.encode("utf-8")).hexdigest()[:12]
        if req.route_id
        else ""
    )
    index_token = provider_candidate_index.set(
        req.provider_candidate_index
    )
    try:
        try:
            lane_paths = await collector.refine_transit(
                req.map_object,
                Coordinate(lat=req.origin_lat, lng=req.origin_lng),
                Coordinate(lat=req.dest_lat, lng=req.dest_lng),
            )
        except CollectorNotConfigured as exc:
            raise HTTPException(
                status_code=503,
                detail={
                    "message": str(exc),
                    "code": exc.code,
                    "retryable": False,
                },
            ) from exc
        except CollectorError as exc:
            # 오류 분류를 문자열이 아닌 구조로 전달해 Backend가 재시도 정책을
            # 문자열 검색 없이 결정할 수 있게 한다.
            raise HTTPException(
                status_code=502,
                detail={
                    "message": str(exc),
                    "code": getattr(exc, "code", "provider_error"),
                    "retryable": bool(getattr(exc, "retryable", True)),
                },
            ) from exc
    finally:
        provider_candidate_index.reset(index_token)
        route_id_hash.reset(route_token)
    return {
        "geometry_quality": "exact",
        "refined_at": datetime.now(UTC).isoformat(),
        "lane_paths": [
            [{"lat": point.lat, "lng": point.lng} for point in path]
            for path in lane_paths
        ],
    }


@router.post("/recommend")
async def recommend(req: RecommendRequest):
    """그늘 보강을 우회하는 이전 직접 추천 경로는 사용하지 않는다."""
    raise HTTPException(
        status_code=409,
        detail=(
            "Direct AI recommendation is disabled. Use backend "
            "/api/routes/recommend so collection, building shade, enriched "
            "snapshots, and ranking share one canonical flow."
        ),
    )


@router.post("/labeling/candidates")
async def labeling_candidates(req: RecommendRequest):
    """초기 라벨링용 후보와 당시 피처를 생성한다. 모델 준비 전에도 호출할 수 있다."""
    if req.candidate_limit > settings.ODSAY_MAX_CANDIDATES:
        # 요청보다 적게 수집한 결과를 정상 응답처럼 보이지 않게 한다.
        raise HTTPException(
            status_code=422,
            detail=(
                f"요청한 후보 수 {req.candidate_limit}개가 서버 상한 "
                f"{settings.ODSAY_MAX_CANDIDATES}개를 초과합니다. "
                "후보 수를 줄여 다시 요청해 주세요."
            ),
        )
    route_features, collection_metadata = await _collect_featured_routes(req)
    group_id = _group_id(req)
    snapshots = _route_snapshots(
        group_id,
        route_features,
        collection_metadata.get("captured_at"),
        _holdout_group_id(req),
    )
    snapshot_by_route = {snapshot["route_id"]: snapshot for snapshot in snapshots}
    if len(snapshot_by_route) != len(snapshots):
        raise HTTPException(status_code=502, detail="경로 후보 식별자가 중복되었습니다.")
    traits_by_route = generate_route_traits(snapshots)
    return {
        "group_id": group_id,
        "candidates": [
            {
                "route_id": (route_id := _route_id(feature)),
                "summary": _summary(feature),
                "duration_min": feature["_duration_min"],
                "distance_m": feature["_distance_m"],
                "sources": feature["_sources"],
                "geometry_quality": feature["_geometry_quality"],
                "path": feature["_path"],
                "segments": feature["_segments"],
                "slope_segments": feature.get("_slope_segments", []),
                "transit_refinement": feature.get("_transit_refinement"),
                "features": {key: value for key, value in feature.items() if not key.startswith("_")},
                "feature_snapshot": snapshot_by_route[route_id],
                "trait_labels": traits_by_route[route_id],
            }
            for feature in route_features
        ],
        "metadata": {**collection_metadata, "weather": req.weather},
    }


async def _collect_static_featured_routes(
    req: RecommendRequest,
) -> tuple[list[dict], dict]:
    origin = Coordinate(lat=req.origin_lat, lng=req.origin_lng)
    destination = Coordinate(lat=req.dest_lat, lng=req.dest_lng)
    # Opt-in OSMnx is used only inside ODsay to recover walking geometry. It has
    # no authoritative travel-time value and therefore must not become a
    # scored standalone route candidate.
    avoid_stairs = req.uses_wheelchair or req.avoid_stairs
    odsay_collector = OdsayRouteCollector(
        avoid_stairs=avoid_stairs,
        uses_wheelchair=req.uses_wheelchair,
    )
    tmap_collector = TmapRouteCollector(avoid_stairs=avoid_stairs)
    collectors = [odsay_collector, tmap_collector]
    if req.uses_wheelchair:
        collectors.append(OrsWheelchairRouteCollector())
    source_names = [collector.source_name for collector in collectors]
    tasks = [
        odsay_collector.collect(
            origin, destination, max_candidates=req.candidate_limit
        ),
        tmap_collector.collect(origin, destination),
    ]
    if req.uses_wheelchair:
        tasks.append(collectors[-1].collect(origin, destination))
    results = await asyncio.gather(
        *tasks,
        return_exceptions=True,
    )

    candidates = []
    succeeded: list[str] = []
    failed: list[str] = []
    source_errors: dict[str, str] = {}
    for source, result in zip(source_names, results):
        if isinstance(result, Exception):
            failed.append(source)
            source_errors[source] = f"{type(result).__name__}: {result}"
        elif not result:
            failed.append(source)
            source_errors[source] = "NoRoutes"
        else:
            succeeded.append(source)
            candidates.extend(result)
    if not candidates:
        raise HTTPException(
            status_code=503,
            detail={"message": "유효한 실제 경로 후보를 수집하지 못했습니다.", "sources": source_errors},
        )

    if req.uses_wheelchair and "ors" not in succeeded:
        raise HTTPException(
            status_code=503,
            detail={
                "message": (
                    "휠체어 경로의 노면·폭·턱·경사·계단 제약을 "
                    "검증할 수 없습니다."
                ),
                "required_source": "openrouteservice wheelchair",
                "sources": source_errors,
            },
        )

    layers = _get_layers()
    merged_candidates = merge_route_candidates(candidates)
    if req.uses_wheelchair:
        merged_candidates = [
            candidate
            for candidate in merged_candidates
            if _wheelchair_candidate_constrained(candidate)
        ]
        if not merged_candidates:
            raise HTTPException(
                status_code=503,
                detail={
                    "message": (
                        "모든 실제 보행 구간에 휠체어 통행 제약이 적용된 "
                        "경로가 없습니다."
                    ),
                    "required_source": "openrouteservice wheelchair",
                },
            )
    analysis_parts = [
        _analysis_route_parts(candidate)
        for candidate in merged_candidates
    ]
    elevation_features = await asyncio.gather(*(
        extract_elevation_features_for_parts(parts)
        for parts in analysis_parts
    ))
    route_features: list[dict] = []
    for candidate, parts, elevation in zip(
        merged_candidates,
        analysis_parts,
        elevation_features,
    ):
        if candidate.duration_min is None or candidate.duration_min <= 0:
            raise HTTPException(
                status_code=502,
                detail=f"{candidate.source} 경로에 검증 가능한 소요시간이 없습니다.",
            )
        slope_segments = elevation.get("slope_segments", [])
        elevation_summary = {
            key: value
            for key, value in elevation.items()
            if key != "slope_segments"
        }
        feature = {
            **_parse_api_features(candidate),
            **extract_route_features_for_parts(parts, layers),
            **elevation_summary,
            # 건물 그늘은 현재 백엔드의 검증된 building provider가 계산한다.
            # AI 후보 단계에서 확인할 수 없는 값은 0으로 추정하지 않는다.
            "shade_ratio": None,
            "shaded_walk_m": None,
            "shade_building_height_coverage": None,
            # 교통카드 시간대 데이터가 연결되기 전에는 혼잡을 추정하지 않는다.
            "crowd_level": None,
            "_sources": candidate.sources,
            "_duration_min": candidate.duration_min,
            "_distance_m": candidate.distance_m,
            "_path": [{"lat": point.lat, "lng": point.lng} for point in candidate.path],
            "_segments": _enrich_subway_elevator_accessibility(
                _public_segments(candidate, layers),
                layers,
            ),
            "_slope_segments": slope_segments,
            "_geometry_quality": candidate.geometry_quality,
            # 백엔드 내부 전용 대중교통 정밀화 서술자. 사용자 응답으로
            # 전달되지 않도록 백엔드에서 직렬화 제외 필드에 보관한다.
            "_transit_refinement": candidate.transit_refinement,
        }
        route_features.append(feature)

    return route_features, {
        "captured_at": datetime.now(UTC).isoformat(),
        "sources_attempted": source_names,
        "sources_succeeded": succeeded,
        "sources_failed": failed,
        "source_errors": source_errors,
    }


def _wheelchair_evidence_constrained(value: object) -> bool:
    evidence = _mapping(value)
    response_keys = evidence.get("verified_extra_response_keys")
    return (
        evidence.get("wheelchair_constraints_applied") is True
        and evidence.get("stairs_excluded_by_provider") is True
        and isinstance(evidence.get("wheelchair_restrictions"), dict)
        and bool(evidence["wheelchair_restrictions"])
        and isinstance(evidence.get("wheelchair_data_limitations"), list)
        and bool(evidence["wheelchair_data_limitations"])
        and isinstance(
            evidence.get("wheelchair_constraint_categories"),
            list,
        )
        and bool(evidence["wheelchair_constraint_categories"])
        and evidence.get("extra_info_full_route_coverage") is True
        and isinstance(response_keys, dict)
        and set(response_keys) == {
            "steepness",
            "suitability",
            "surface",
            "waytype",
            "osmid",
        }
        and all(
            isinstance(key, str) and bool(key)
            for key in response_keys.values()
        )
    )


def _wheelchair_candidate_constrained(candidate: object) -> bool:
    """모든 실제 보행 구간에 ORS wheelchair 제약이 적용됐는지 확인한다."""
    segments = getattr(candidate, "segments", None) or []
    walk_segments = [
        segment
        for segment in segments
        if segment.get("mode") in {"walk", "transfer"}
        and (
            segment.get("distance_m") is None
            or segment.get("distance_m") > 0
        )
    ]
    if walk_segments:
        return all(
            _wheelchair_evidence_constrained(
                segment.get("accessibility_evidence")
            )
            for segment in walk_segments
        )
    return _wheelchair_evidence_constrained(
        getattr(candidate, "accessibility_evidence", {})
    )


def _limit_cached_route_features(
    route_features: list[dict],
    candidate_limit: int,
) -> list[dict]:
    """더 큰 사전계산 캐시에서 요청한 ODsay 후보 수만 선택한다."""
    selected: list[dict] = []
    odsay_count = 0
    for feature in route_features:
        sources = feature.get("_sources")
        has_odsay = (
            isinstance(sources, list)
            and "odsay" in sources
        )
        if has_odsay:
            if odsay_count >= candidate_limit:
                continue
            odsay_count += 1
        selected.append(feature)
    return selected


def _apply_request_features(
    route_features: list[dict],
    req: RecommendRequest,
) -> list[dict]:
    scoped = copy.deepcopy(
        _limit_cached_route_features(
            route_features,
            req.candidate_limit,
        )
    )
    for feature in scoped:
        feature.update(_weather_features(req))
        feature.update(_context_features(feature, req))
    return scoped


def _walk_geometry_exact(feature: dict) -> bool:
    """보행·환승 구간 geometry가 모두 exact인지 확인한다."""
    walk_segments = [
        segment
        for segment in feature.get("_segments") or []
        if segment.get("mode") in {"walk", "transfer"}
    ]
    return bool(walk_segments) and all(
        segment.get("geometry_quality") == "exact"
        for segment in walk_segments
    )


def _static_features_cacheable(
    route_features: list[dict],
    collection_metadata: dict,
) -> bool:
    """정확 보행 geometry와 90m 경사가 완성된 후보군을 캐시한다.

    대중교통 표시 선형은 선택 시점에 지연 정밀화되므로 estimated여도
    scoring 피처 캐시 저장을 막지 않는다.
    """
    failed_sources = collection_metadata.get("sources_failed")
    if not isinstance(failed_sources, list) or failed_sources:
        return False
    return bool(route_features) and all(
        (
            feature.get("_geometry_quality") == "exact"
            or _walk_geometry_exact(feature)
        )
        and feature.get("elevation_status") == "estimated_90m"
        and bool(feature.get("_slope_segments"))
        for feature in route_features
    )


async def _collect_featured_routes(
    req: RecommendRequest,
) -> tuple[list[dict], dict]:
    """정적 후보·경사는 OD 캐시에서 읽고 요청별 날씨·조건만 다시 결합한다."""
    identity = route_feature_cache_identity(
        req.origin_lat,
        req.origin_lng,
        req.dest_lat,
        req.dest_lng,
        avoid_stairs=req.uses_wheelchair or req.avoid_stairs,
        uses_wheelchair=req.uses_wheelchair,
    )
    cached = await asyncio.to_thread(
        read_route_feature_cache,
        identity,
        minimum_candidate_limit=req.candidate_limit,
    )
    if cached is None:
        async with route_feature_request_lock(identity):
            cached = await asyncio.to_thread(
                read_route_feature_cache,
                identity,
                minimum_candidate_limit=req.candidate_limit,
            )
            if cached is None:
                route_features, metadata = (
                    await _collect_static_featured_routes(req)
                )
                if _static_features_cacheable(route_features, metadata):
                    try:
                        await asyncio.to_thread(
                            write_route_feature_cache,
                            identity,
                            candidate_limit=req.candidate_limit,
                            route_features=route_features,
                            metadata=metadata,
                        )
                    except OSError as exc:
                        log.warning(
                            "정적 경로 피처 캐시 저장 실패 (%s)",
                            type(exc).__name__,
                        )
                else:
                    log.info(
                        "정확 geometry·90m 경사 완성 전 후보군은 요청 범위에서만 사용"
                    )
                cached = (route_features, metadata)
    route_features, metadata = cached
    return _apply_request_features(route_features, req), metadata


def _analysis_route_parts(candidate) -> list[list[tuple[float, float]]]:
    """표시 geometry와 분리된, 공급자가 확인한 보행 분석 parts."""
    if candidate.source == "odsay":
        walk_segments = [
            segment
            for segment in candidate.segments
            if segment.get("mode") == "walk"
        ]
        parts: list[list[tuple[float, float]]] = []
        for segment in walk_segments:
            if segment.get("geometry_quality") != "exact":
                # 역·정류장 양 끝점을 이은 직선은 표시용 추정선일 뿐 실제
                # 보행 동선이 아니다. 이를 DEM·시설 버퍼에 넣으면 경사와
                # 주변 시설을 실제 관측처럼 만들므로 분석하지 않는다.
                return []
            path = segment.get("path")
            if not isinstance(path, list) or len(path) < 2:
                # 일부만 분석하면 전체 보행 경로의 피처처럼 과장되므로
                # 선언된 보행 part 하나라도 확인 불가하면 모두 미확인 처리한다.
                return []
            coordinates = [
                (float(point.lat), float(point.lng))
                for point in path
            ]
            declared_distance = segment.get("distance_m")
            if (
                not isinstance(declared_distance, bool)
                and isinstance(declared_distance, (int, float))
                and declared_distance == 0
            ):
                # ODsay가 환승 지점에서 0m 보행 구간과 동일 좌표 두 개를
                # 함께 반환하는 경우는 실제 이동이 없으므로 경사 구간에서
                # 제외한다. 0m인데 좌표가 다르면 공급자 불일치로 취급한다.
                if len(set(coordinates)) == 1:
                    continue
                return []
            parts.append(coordinates)
        return parts

    if (
        candidate.source in {"tmap", "ors"}
        and set(candidate.sources).issubset({"tmap", "ors"})
        and candidate.geometry_quality == "exact"
        and len(candidate.path) >= 2
    ):
        return [[
            (float(point.lat), float(point.lng))
            for point in candidate.path
        ]]
    return []


def _route_snapshots(
    group_id: str,
    route_features: list[dict],
    captured_at: str | None,
    holdout_group_id: str,
) -> list[dict]:
    """API 응답·평가 라벨이 같은 고정 피처 해시를 공유하도록 스냅샷을 만든다."""
    fixed_at = captured_at or datetime.now(UTC).isoformat()
    return [
        build_live_feature_snapshot(
            group_id=group_id,
            route_id=_route_id(feature),
            features={
                key: value
                for key, value in feature.items()
                if not key.startswith("_")
            },
            sources=[str(source) for source in feature["_sources"]],
            geometry_quality=feature["_geometry_quality"],
            captured_at=fixed_at,
            holdout_group_id=holdout_group_id,
        )
        for feature in route_features
    ]


def _group_id(req: RecommendRequest) -> str:
    return hashlib.sha256(
        (
            f"{req.origin_lat:.5f},{req.origin_lng:.5f}->{req.dest_lat:.5f},{req.dest_lng:.5f}"
            f"|{req.weather}|luggage={int(req.carry_luggage)}|stairs={int(req.avoid_stairs)}"
            f"|stroller={int(req.stroller)}|shade={int(req.shade_priority)}"
            f"|mintransfers={int(req.minimize_transfers)}"
            f"|lowfloor={int(req.low_floor_priority)}|wheelchair={int(req.uses_wheelchair)}"
            f"|aid={int(req.uses_walking_aid)}|maxwalk={req.max_walk_distance_m}"
            f"|weatherpriority={int(req.prioritize_weather_safety)}"
            f"|temp={req.temp_c}|feels={req.feels_like_c}|rain={req.precipitation_mm}"
            f"|wind={req.wind_ms}|pm10={req.pm10}"
        ).encode("utf-8")
    ).hexdigest()[:20]


def _holdout_group_id(req: RecommendRequest) -> str:
    """시간·옵션이 달라도 같은 방향의 OD는 동일 holdout에 둔다."""
    value = (
        f"{req.origin_lat:.5f},{req.origin_lng:.5f}"
        f"->{req.dest_lat:.5f},{req.dest_lng:.5f}"
    )
    return "od-" + hashlib.sha256(value.encode("utf-8")).hexdigest()[:20]


def _context_features(feature: dict, req: RecommendRequest) -> dict:
    """사용자 조건과 경로 관측값의 상호작용만 만들며 계수는 학습 모델이 결정한다."""
    stairs = feature.get("stair_count")
    walk = feature.get("walk_distance_m")
    elevator = feature.get("elevator_ratio")
    low_floor = feature.get("is_low_floor_bus")
    transfer_count = feature.get("transfer_count")
    shade_ratio = feature.get("shade_ratio")
    shaded_walk_m = feature.get("shaded_walk_m")
    if walk is None or shade_ratio is None:
        unshaded_walk_m = None
    elif shaded_walk_m is not None:
        unshaded_walk_m = max(0.0, float(walk) - float(shaded_walk_m))
    else:
        unshaded_walk_m = max(0.0, float(walk) * (1.0 - float(shade_ratio)))
    return {
        "stair_avoidance_burden": stairs if req.avoid_stairs else 0.0,
        "luggage_walk_burden": walk if req.carry_luggage else 0.0,
        "luggage_stair_burden": stairs if req.carry_luggage else 0.0,
        "low_floor_priority_mismatch": (
            None if req.low_floor_priority and low_floor is None
            else float(req.low_floor_priority and low_floor is False)
        ),
        "wheelchair_stair_burden": stairs if req.uses_wheelchair else 0.0,
        "wheelchair_elevator_gap": (
            None if req.uses_wheelchair and elevator is None
            else (1.0 - float(elevator) if req.uses_wheelchair else 0.0)
        ),
        "walking_aid_walk_burden": walk if req.uses_walking_aid else 0.0,
        "max_walk_excess_m": (
            None if req.max_walk_distance_m is not None and walk is None
            else max(0.0, float(walk) - req.max_walk_distance_m)
            if req.max_walk_distance_m is not None else 0.0
        ),
        "weather_priority_walk_burden": walk if req.prioritize_weather_safety else 0.0,
        "stroller_walk_burden": walk if req.stroller else 0.0,
        "stroller_stair_burden": stairs if req.stroller else 0.0,
        "stroller_elevator_gap": (
            None if req.stroller and elevator is None
            else (1.0 - float(elevator) if req.stroller else 0.0)
        ),
        "shade_priority_unshaded_walk_m": (
            unshaded_walk_m if req.shade_priority else 0.0
        ),
        "minimize_transfers_burden": (
            transfer_count if req.minimize_transfers else 0.0
        ),
    }


def _summary(feature: dict) -> str:
    labels = []
    for segment in feature["_segments"]:
        label = segment.get("bus_route_name") or {
            "subway": "도시철도", "walk": "도보", "transfer": "환승"
        }.get(segment.get("mode"))
        if label and label not in labels:
            labels.append(str(label))
    return " + ".join(labels) or "경로 후보"


def _transit_identity(feature: dict) -> list:
    """정밀화로 변하지 않는 대중교통 노선·승하차 식별자 sequence.

    lane ID·승하차 정류장 ID·wayCode는 ODsay search 응답에 이미 들어 있고
    loadLane 정밀화로 바뀌지 않는다. 표시 문자열만으로는 서로 다른 경로가
    같은 route ID로 충돌할 수 있어 이 값들을 fingerprint에 포함한다.
    mapObj 원문은 route ID·로그·응답 어디에도 넣지 않는다.
    """
    identity: list = []
    for segment in feature.get("_segments") or []:
        mode = segment.get("mode")
        if mode not in {"bus", "subway"}:
            continue
        raw = segment.get("raw")
        raw = raw if isinstance(raw, dict) else {}
        lanes = raw.get("lane")
        lane_ids = [
            _first_known(lane, "busID", "busNo", "subwayCode", "name")
            for lane in (lanes if isinstance(lanes, list) else [])
            if isinstance(lane, dict)
        ]
        identity.append([
            mode,
            [value for value in lane_ids if value],
            _first_known(raw, "startID", "startName"),
            _first_known(raw, "endID", "endName"),
            _first_known(raw, "wayCode", "way"),
        ])
    return identity


def _first_known(mapping: dict, *keys: str) -> str | None:
    for key in keys:
        value = mapping.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return None


def _route_id(feature: dict) -> str:
    """대중교통 정밀화 전후 동일한 semantic 경로 식별자.

    전체 정밀 path 해시는 loadLane 정밀화로 값이 바뀌므로 사용하지 않는다.
    노선·승하차·보행 geometry는 정밀화로 변하지 않는 관측값이다.
    """
    walk_points = [
        Coordinate(lat=float(point["lat"]), lng=float(point["lng"]))
        for segment in feature["_segments"]
        if segment.get("mode") in {"walk", "transfer"}
        for point in segment.get("path") or []
    ]
    if not walk_points:
        walk_points = [
            Coordinate(lat=float(point["lat"]), lng=float(point["lng"]))
            for point in feature["_path"]
        ]
    sampled_walk = sample_path_by_distance(walk_points, n=41) or walk_points
    descriptor = feature.get("_transit_refinement")
    raw_map_object = (
        descriptor.get("map_object")
        if isinstance(descriptor, dict)
        else None
    )
    normalized_map_object_hash = None
    if isinstance(raw_map_object, str) and raw_map_object.strip():
        normalized_map_object = OdsayRouteCollector._load_lane_map_object(
            raw_map_object
        )
        normalized_map_object_hash = hashlib.sha256(
            normalized_map_object.encode("utf-8")
        ).hexdigest()
    fingerprint = {
        "sources": sorted(feature["_sources"]),
        "map_object_hash": normalized_map_object_hash,
        "walk_path": [
            [round(point.lat, 5), round(point.lng, 5)]
            for point in sampled_walk
        ],
        # 표시 문자열이 같아도 실제 노선·승하차가 다르면 서로 다른 경로다.
        "transit": _transit_identity(feature),
        "segments": [
            [
                segment.get("mode"),
                segment.get("bus_route_name"),
                segment.get("station_name"),
                segment.get("description"),
                segment.get("distance_m"),
            ]
            for segment in feature["_segments"]
        ],
    }
    digest = hashlib.sha256(json.dumps(fingerprint, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()
    return f"route-{digest[:20]}"


def _explicit_bool(value) -> bool | None:
    if value in ("Y", "y", True, 1, "1"):
        return True
    if value in ("N", "n", False, 0, "0"):
        return False
    return None


def _nonnegative_int(value) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number) or number < 0 or not number.is_integer():
        return None
    return int(number)


def _nonnegative_float(value) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) and number >= 0 else None


def _mapping(value) -> dict:
    """공급자 중첩 값이 객체가 아니면 빈 객체로 취급한다."""
    return value if isinstance(value, dict) else {}


def _mapping_list(value) -> list[dict] | None:
    """모든 원소가 객체인 배열만 완전히 관측된 배열로 인정한다."""
    if (
        not isinstance(value, list)
        or any(not isinstance(item, dict) for item in value)
    ):
        return None
    return value


def _provider_text(value) -> str | None:
    """설명 필드에는 공급자의 scalar 문자열만 사용한다."""
    if value is None or isinstance(value, (dict, list, tuple, set)):
        return None
    text = str(value).strip()
    if not text or text.casefold() in {"null", "none", "nan", "undefined"}:
        return None
    return text


def _lane_low_floor_status(value) -> bool | None:
    """한 버스 구간의 모든 lane이 명시된 경우에만 저상 여부를 확정한다."""
    lanes = _mapping_list(value)
    if not lanes:
        return None
    markers: list[bool] = []
    for lane in lanes:
        marker = (
            _explicit_bool(lane.get("lowFloorYn"))
            if "lowFloorYn" in lane
            else _explicit_bool(lane.get("isLowFloor"))
        )
        if marker is None:
            return None
        markers.append(marker)
    # 완전 관측 상태에서는 하나라도 일반버스이면 경로 구간은 일반버스다.
    return all(markers)


def _walk_facility_status(sub_path: dict) -> tuple[int | None, bool | None]:
    """한 보행·환승 구간의 계단 수와 승강기 여부를 tri-state로 읽는다."""
    stair_info = sub_path.get("stairInfo")
    if not isinstance(stair_info, dict):
        return None, None
    stairs = (
        _nonnegative_int(stair_info.get("stairCount"))
        if "stairCount" in stair_info
        else None
    )
    elevator = (
        _explicit_bool(stair_info.get("elevatorYN"))
        if "elevatorYN" in stair_info
        else None
    )
    return stairs, elevator


def _tmap_stair_feature_count(raw: dict) -> int | None:
    """완전한 TMAP feature 배열에서 명시된 계단 feature만 센다."""
    features = _mapping_list(raw.get("features"))
    if features is None:
        return None
    count = 0
    for item in features:
        properties = item.get("properties")
        if not isinstance(properties, dict):
            return None
        raw_facility = properties.get("facilityType")
        raw_turn = properties.get("turnType")
        facility_str = str(properties.get("facilityName") or "")
        # TMAP 보행자 API 공식 규격: facilityType=17 또는 turnType=127.
        if (
            raw_facility in (17, "17")
            or raw_turn in (127, "127")
            or "계단" in facility_str
        ):
            count += 1
    # 명시된 계단은 확인 가능하지만, feature 부재만으로 계단 0을 단정하지 않는다.
    return count if count > 0 else None


def _parse_api_features(candidate) -> dict:
    """외부 응답에서 확인 가능한 값만 추출하며 결측을 0으로 바꾸지 않는다."""
    raw = _mapping(candidate.raw_response)
    info = _mapping(raw.get("info"))
    sub_paths = _mapping_list(raw.get("subPath"))

    transfer_count = _nonnegative_int(info.get("transferCount"))
    bus_rides = _nonnegative_int(info.get("busTransitCount"))
    subway_rides = _nonnegative_int(info.get("subwayTransitCount"))
    if transfer_count is None and bus_rides is not None and subway_rides is not None:
        # ODsay의 두 필드는 실제 탑승한 버스·도시철도 수다. 직통 예시도
        # 1을 반환하므로 환승 횟수는 전체 탑승 수에서 최초 탑승을 뺀 값이다.
        transfer_count = max(0, bus_rides + subway_rides - 1)
    if transfer_count is None and candidate.source == "tmap":
        transfer_count = 0
    walk_distance = _nonnegative_float(info.get("totalWalk"))
    if walk_distance is None and candidate.source == "tmap":
        walk_distance = candidate.distance_m

    low_floor = None
    stairs = None
    elevator_ratio = None
    if (
        sub_paths is not None
        and all(
            type(sub_path.get("trafficType")) is int
            and sub_path.get("trafficType") in {1, 2, 3}
            for sub_path in sub_paths
        )
    ):
        bus_paths = [
            sub_path
            for sub_path in sub_paths
            if sub_path.get("trafficType") == 2
        ]
        bus_values = [
            _lane_low_floor_status(sub_path.get("lane"))
            for sub_path in bus_paths
        ]
        if bus_values and all(value is not None for value in bus_values):
            low_floor = all(value is True for value in bus_values)

        walk_paths = [
            sub_path
            for sub_path in sub_paths
            if sub_path.get("trafficType") == 3
        ]
        walk_values = [
            _walk_facility_status(sub_path)
            for sub_path in walk_paths
        ]
        stair_values = [value[0] for value in walk_values]
        elevator_values = [value[1] for value in walk_values]
        if stair_values and all(value is not None for value in stair_values):
            stairs = sum(int(value) for value in stair_values)
        if (
            elevator_values
            and all(value is not None for value in elevator_values)
        ):
            elevator_ratio = (
                sum(value is True for value in elevator_values)
                / len(elevator_values)
            )

    if candidate.source == "tmap":
        stairs = _tmap_stair_feature_count(raw)

    return {
        "avg_slope_percent": None,
        "max_slope_percent": None,
        "min_slope_percent": None,
        "slope_iqr": None,
        "stair_count": stairs,
        "elevator_ratio": elevator_ratio,
        "transfer_count": transfer_count,
        "walk_distance_m": walk_distance,
        "total_duration_min": candidate.duration_min,
        "is_low_floor_bus": low_floor,
    }


def _station_name_key(value: object) -> str | None:
    """공급자·공공데이터의 역명 표기를 보수적으로 맞춘다."""
    if not isinstance(value, str):
        return None
    normalized = re.sub(r"[\s()\[\]·.-]", "", value).removesuffix("역")
    return normalized.casefold() or None


def _subway_line_key(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int) and 1 <= value <= 4:
        return value
    if isinstance(value, str):
        matched = re.search(r"[1-4]", value)
        if matched:
            return int(matched.group())
    return None


def _official_elevator_exits(value: object) -> frozenset[str]:
    if not isinstance(value, str):
        return frozenset()
    return frozenset(re.findall(r"\d+", value))


def _provider_exit_no(value: object) -> str | None:
    text = _provider_text(value)
    if not text:
        return None
    matched = re.search(r"\d+", text)
    return matched.group() if matched else None


def _subway_accessibility_lookup(
    layers: dict,
) -> dict[tuple[int | None, str], dict]:
    """호선·역명별 시설 재고. 충돌 값은 보수적으로 제외한다."""
    subway = layers.get("subway")
    if subway is None:
        return {}
    seen: dict[tuple[int | None, str], set[tuple]] = {}
    for _, row in subway.iterrows():
        name = _station_name_key(row.get("역명"))
        line = _subway_line_key(row.get("station_line"))
        elevator = row.get("elevator_accessible")
        ramp_count = _nonnegative_int(row.get("external_ramp_count"))
        lift_count = _nonnegative_int(row.get("wheelchair_lift_count"))
        if (
            name is None
            or elevator not in (0, 1, False, True)
            or ramp_count is None
            or lift_count is None
        ):
            continue
        route_count = _nonnegative_int(row.get("elevator_route_count"))
        route_source = _provider_text(
            row.get("station_elevator_route_evidence_source")
        )
        route_exits = _official_elevator_exits(
            row.get("accessible_elevator_exits")
        )
        seen.setdefault((line, name), set()).add((
            bool(elevator),
            ramp_count,
            lift_count,
            route_count,
            route_source,
            route_exits,
        ))
    return {
        key: {
            "has_elevator": value[0],
            "station_external_ramp_count": value[1],
            "station_wheelchair_lift_count": value[2],
            "elevator_route_count": value[3],
            "station_elevator_route_evidence_source": value[4],
            "accessible_elevator_exits": value[5],
        }
        for key, values in seen.items()
        if len(values) == 1
        for value in values
    }


def _station_accessibility_value(
    lookup: dict[tuple[int | None, str], dict],
    line: int | None,
    station_name: object,
) -> dict | None:
    name = _station_name_key(station_name)
    if name is None:
        return None
    direct = lookup.get((line, name))
    if direct is not None:
        return direct
    if line is not None:
        # 구형/테스트 레이어처럼 호선 컬럼 자체가 없는 값만 허용한다.
        return lookup.get((None, name))
    # 공급자 호선도 없을 때는 역명 단독 값이 하나인 경우만 사용한다.
    matches = [value for (known_line, key), value in lookup.items() if key == name]
    return matches[0] if len(matches) == 1 else None


def _enrich_subway_elevator_accessibility(
    segments: list[dict],
    layers: dict,
) -> list[dict]:
    """확인된 역사 시설 재고만 도시철도 구간에 추가한다.

    역 단위 시설 재고는 특정 동선을 증명하지 않는다. 출구 일치는 공식
    엘리베이터 이동경로에서 지상 1층부터 승강장까지 연결된 출구와 ODsay의
    출구번호가 정확히 일치할 때만 True로 추가한다.
    """
    lookup = _subway_accessibility_lookup(layers)
    if not lookup:
        return segments
    for segment in segments:
        if segment.get("mode") != "subway":
            continue
        line = _subway_line_key(segment.get("transit_route_id"))
        value = _station_accessibility_value(
            lookup, line, segment.get("station_name")
        )
        if value is not None:
            if segment.get("has_elevator") is None:
                segment["has_elevator"] = value["has_elevator"]
            segment["station_external_ramp_count"] = value[
                "station_external_ramp_count"
            ]
            segment["station_wheelchair_lift_count"] = value[
                "station_wheelchair_lift_count"
            ]
            segment["station_accessibility_evidence_source"] = (
                "부산교통공사 도시철도 편의시설 현황 2025-12-31"
            )
            segment["station_ramp_route_match"] = None
            start_exit = _provider_exit_no(segment.get("start_exit_no"))
            if (
                start_exit is not None
                and value["station_elevator_route_evidence_source"]
                and start_exit in value["accessible_elevator_exits"]
            ):
                segment["start_station_elevator_exit_match"] = True
                segment["station_elevator_route_evidence_source"] = value[
                    "station_elevator_route_evidence_source"
                ]
        end_value = _station_accessibility_value(
            lookup, line, segment.get("end_station_name")
        )
        end_exit = _provider_exit_no(segment.get("end_exit_no"))
        if (
            end_value is not None
            and end_exit is not None
            and end_value["station_elevator_route_evidence_source"]
            and end_exit in end_value["accessible_elevator_exits"]
        ):
            segment["end_station_elevator_exit_match"] = True
            segment["station_elevator_route_evidence_source"] = end_value[
                "station_elevator_route_evidence_source"
            ]
    return segments


def _stop_name_key(value: object) -> str | None:
    text = _provider_text(value)
    if not text:
        return None
    return re.sub(r"(?:버스)?정류장$", "", re.sub(r"\s+", "", text))


def _smart_shelter_for_boarding_stop(raw: dict, layers: dict | None) -> str | None:
    """이름이 같고 좌표가 75m 이내인 탑승 정류장만 스마트쉘터로 확정한다."""
    layer = (layers or {}).get("smart_shelter")
    stop_name = _stop_name_key(raw.get("startName"))
    x = raw.get("startX")
    y = raw.get("startY")
    if (
        layer is None
        or stop_name is None
        or isinstance(x, bool)
        or isinstance(y, bool)
        or not isinstance(x, (int, float))
        or not isinstance(y, (int, float))
        or not math.isfinite(float(x))
        or not math.isfinite(float(y))
        or "정류소명" not in layer
    ):
        return None
    metric_x, metric_y = _WGS84_TO_METRIC.transform(float(x), float(y))
    from shapely.geometry import Point

    point = Point(metric_x, metric_y)
    indexes = layer.sindex.query(point.buffer(75), predicate="intersects")
    matches = [
        row
        for _, row in layer.iloc[indexes].iterrows()
        if _stop_name_key(row.get("정류소명")) == stop_name
        and row.geometry.distance(point) <= 75
    ]
    if not matches:
        return None
    nearest = min(matches, key=lambda row: row.geometry.distance(point))
    return _provider_text(nearest.get("정류소명"))


def _public_wheelchair_evidence(accessibility: dict) -> dict:
    """검증 제약과 OSM 한계를 함께 공개한다. 한쪽만 노출하지 않는다."""
    if not _wheelchair_evidence_constrained(accessibility):
        return {}
    return {
        "wheelchair_constraints_applied": True,
        "wheelchair_constraint_source": (
            "openrouteservice wheelchair profile"
        ),
        "wheelchair_restrictions": dict(
            accessibility["wheelchair_restrictions"]
        ),
        "wheelchair_data_limitations": list(
            accessibility["wheelchair_data_limitations"]
        ),
        "wheelchair_constraint_categories": list(
            accessibility["wheelchair_constraint_categories"]
        ),
        "wheelchair_extra_info_full_route_coverage": True,
        "wheelchair_extra_response_keys": dict(
            accessibility["verified_extra_response_keys"]
        ),
    }


def _public_segments(candidate, layers: dict | None = None) -> list[dict]:
    route_facilities = _parse_api_features(candidate)
    observations = []
    for item in candidate.segments:
        raw = _mapping(item.get("raw"))
        mode = item.get("mode", "transfer")
        stairs, elevator = (
            _walk_facility_status(raw)
            if mode in {"walk", "transfer"}
            else (None, None)
        )
        accessibility = _mapping(item.get("accessibility_evidence"))
        observations.append({
            "item": item,
            "raw": raw,
            "mode": mode,
            "stairs": stairs,
            "elevator": elevator,
            "accessibility": accessibility,
            "low_floor": (
                _lane_low_floor_status(raw.get("lane"))
                if mode == "bus"
                else None
            ),
        })

    bus_values = [
        observation["low_floor"]
        for observation in observations
        if observation["mode"] == "bus"
    ]
    walk_values = [
        observation
        for observation in observations
        if observation["mode"] in {"walk", "transfer"}
    ]
    low_floor_complete = (
        bool(bus_values)
        and all(value is not None for value in bus_values)
        and route_facilities["is_low_floor_bus"] is not None
    )
    stairs_complete = (
        bool(walk_values)
        and all(
            observation["stairs"] is not None
            for observation in walk_values
        )
        and route_facilities["stair_count"] is not None
    )
    elevator_complete = (
        bool(walk_values)
        and all(
            observation["elevator"] is not None
            for observation in walk_values
        )
        and route_facilities["elevator_ratio"] is not None
    )

    segments = []
    for index, observation in enumerate(observations):
        item = observation["item"]
        raw = observation["raw"]
        mode = observation["mode"]
        lanes = _mapping_list(raw.get("lane"))
        lane = lanes[0] if lanes else {}
        start_name = _provider_text(raw.get("startName"))
        end_name = _provider_text(raw.get("endName"))
        name = (
            _provider_text(lane.get("busNo"))
            or _provider_text(lane.get("name"))
        )
        direction_code = raw.get("wayCode")
        if type(direction_code) is not int or direction_code not in {1, 2}:
            direction_code = None
        interval_min = raw.get("intervalTime")
        if (
            type(interval_min) is not int
            or interval_min < 0
        ):
            interval_min = None
        description = " → ".join(value for value in (start_name, end_name) if value)
        if name:
            description = f"{name} · {description}" if description else str(name)
        stairs = (
            observation["stairs"]
            if stairs_complete
            else None
        )
        elevator = (
            observation["elevator"]
            if elevator_complete
            else None
        )
        low_floor = (
            observation["low_floor"]
            if low_floor_complete
            else None
        )
        # ORS/TMAP 접근성 근거는 해당 보행·환승 선형에만 속한다. 후보
        # 조립 중 공급자 근거가 대중교통 item에 남아 있더라도 버스·지하철
        # 구간의 경사로 또는 휠체어 통행 근거로 복제하지 않는다.
        walk_accessibility = (
            observation["accessibility"]
            if mode in {"walk", "transfer"}
            else {}
        )
        ramp_points = walk_accessibility.get("ramp_points")
        if not isinstance(ramp_points, list) or not ramp_points:
            ramp_points = None
        public_ramp_points = (
            [
                {"lat": point["lat"], "lng": point["lng"]}
                for point in ramp_points
                if isinstance(point, dict)
                and isinstance(point.get("lat"), (int, float))
                and not isinstance(point.get("lat"), bool)
                and isinstance(point.get("lng"), (int, float))
                and not isinstance(point.get("lng"), bool)
            ]
            if ramp_points
            else None
        )
        ramp_replaces_stairs = (
            True
            if ramp_points
            and any(
                isinstance(point, dict)
                and point.get("replaces_stairs") is True
                for point in ramp_points
            )
            else None
        )
        needs_vertical_move = (
            True
            if (
                (stairs is not None and stairs > 0)
                or elevator is True
                or bool(public_ramp_points)
            )
            else None
        )
        segments.append({
            "id": f"{candidate.source}-{index}",
            "mode": mode,
            "description": description or {"walk": "보행 이동", "bus": "버스 이동", "subway": "도시철도 이동"}.get(mode, "환승 이동"),
            "duration_min": item["duration_min"],
            "distance_m": item.get("distance_m"),
            # ODsay의 trafficType=3은 보행만 뜻하며 실내·실외를 구분하지 않는다.
            "outdoor": None,
            "has_stairs": None if stairs is None else stairs > 0,
            "stairs_count": stairs,
            "has_slope": True if public_ramp_points else None,
            "ramp_points": public_ramp_points,
            "ramp_replaces_stairs": ramp_replaces_stairs,
            "ramp_evidence_source": (
                "TMAP pedestrian turnType 128/129"
                if public_ramp_points
                else None
            ),
            "stairs_excluded_by_provider": (
                True
                if walk_accessibility.get(
                    "stairs_excluded_by_provider"
                ) is True
                else None
            ),
            **_public_wheelchair_evidence(
                walk_accessibility
            ),
            "bus_route_name": str(name) if mode == "bus" and name else None,
            "is_low_floor_bus": low_floor if mode == "bus" else None,
            "transit_start_id": (
                _first_known(raw, "startLocalStationID", "startID")
                if mode == "bus"
                else _first_known(raw, "startID")
                if mode == "subway"
                else None
            ),
            "transit_end_id": (
                _first_known(raw, "endLocalStationID", "endID")
                if mode == "bus"
                else _first_known(raw, "endID")
                if mode == "subway"
                else None
            ),
            "transit_route_id": (
                _first_known(lane, "busLocalBlID", "busID")
                if mode == "bus"
                else _first_known(lane, "subwayCode")
                if mode == "subway"
                else None
            ),
            "transit_direction": (
                _provider_text(raw.get("way"))
                if mode == "subway"
                else None
            ),
            "transit_direction_code": (
                direction_code if mode == "subway" else None
            ),
            "transit_interval_min": (
                interval_min if mode in {"bus", "subway"} else None
            ),
            "fast_boarding_position": (
                _provider_text(raw.get("door"))
                if mode == "subway"
                else None
            ),
            "start_exit_no": (
                _provider_text(raw.get("startExitNo"))
                if mode == "subway"
                else None
            ),
            "end_exit_no": (
                _provider_text(raw.get("endExitNo"))
                if mode == "subway"
                else None
            ),
            "smart_shelter_name": (
                _smart_shelter_for_boarding_stop(raw, layers)
                if mode == "bus"
                else None
            ),
            "station_name": start_name if mode == "subway" else None,
            "end_station_name": end_name if mode == "subway" else None,
            "has_elevator": elevator,
            "needs_vertical_move": needs_vertical_move,
            "path": [{"lat": point.lat, "lng": point.lng} for point in item.get("path") or []] or None,
            "geometry_quality": item.get("geometry_quality"),
        })
    if segments:
        return segments
    # OSMnx/TMAP 단일 보행 후보는 실제 geometry와 공급자 거리를 보유한다.
    if candidate.source in {"osmnx", "tmap", "ors"}:
        accessibility = _mapping(
            getattr(candidate, "accessibility_evidence", {})
        )
        stairs = (
            _tmap_stair_feature_count(_mapping(candidate.raw_response))
            if candidate.source == "tmap"
            else None
        )
        ramp_points = accessibility.get("ramp_points")
        if not isinstance(ramp_points, list) or not ramp_points:
            ramp_points = None
        public_ramp_points = (
            [
                {"lat": point["lat"], "lng": point["lng"]}
                for point in ramp_points
                if isinstance(point, dict)
                and isinstance(point.get("lat"), (int, float))
                and not isinstance(point.get("lat"), bool)
                and isinstance(point.get("lng"), (int, float))
                and not isinstance(point.get("lng"), bool)
            ]
            if ramp_points
            else None
        )
        return [{
            "id": f"{candidate.source}-0",
            "mode": "walk",
            "description": "보행 경로",
            "duration_min": candidate.duration_min,
            "distance_m": candidate.distance_m,
            # TMAP 보행 geometry만으로 실내·실외 여부를 단정할 수 없다.
            "outdoor": None,
            "has_stairs": None if stairs is None else stairs > 0,
            "stairs_count": stairs,
            "has_slope": True if public_ramp_points else None,
            "ramp_points": public_ramp_points,
            "ramp_replaces_stairs": (
                True
                if ramp_points
                and any(
                    isinstance(point, dict)
                    and point.get("replaces_stairs") is True
                    for point in ramp_points
                )
                else None
            ),
            "ramp_evidence_source": (
                "TMAP pedestrian turnType 128/129"
                if public_ramp_points
                else None
            ),
            "stairs_excluded_by_provider": (
                True
                if accessibility.get("stairs_excluded_by_provider") is True
                else None
            ),
            **_public_wheelchair_evidence(accessibility),
            "needs_vertical_move": (
                True
                if (
                    (stairs is not None and stairs > 0)
                    or bool(public_ramp_points)
                )
                else None
            ),
            "path": [{"lat": point.lat, "lng": point.lng} for point in candidate.path],
            "geometry_quality": candidate.geometry_quality,
        }]
    return []


def _weather_features(req: RecommendRequest) -> dict:
    """실측 원시값과 명시된 라벨링 시나리오를 분리해 기록한다."""
    return {
        "temp_c": req.temp_c,
        "feels_like_c": req.feels_like_c,
        "precipitation_mm": req.precipitation_mm,
        "wind_ms": req.wind_ms,
        "pm10": req.pm10,
        "weather_heatwave": float(req.weather == "heatwave"),
        "weather_coldwave": float(req.weather == "coldwave"),
        "weather_rain": float(req.weather == "rain"),
        "weather_bad_air": float(req.weather == "bad_air"),
    }
