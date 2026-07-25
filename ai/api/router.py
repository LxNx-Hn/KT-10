"""경로 수집·피처 추출·학습 모델 순위화를 제공하는 AI API."""
from __future__ import annotations

import asyncio
import hashlib
import json
import math
import re
from datetime import UTC, datetime
from threading import Lock
from typing import Any, Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from collectors.base import Coordinate
from collectors.odsay_collector import OdsayRouteCollector
from collectors.tmap_collector import TmapRouteCollector
from config import settings
from features.extractor import (
    extract_route_features_for_parts,
    prepare_spatial_layers,
)
from features.elevation import extract_elevation_features_for_parts
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

router = APIRouter()

_layers = None
_rankers = None
_layers_lock = Lock()


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
    max_walk_distance_m: int | None = Field(default=None, ge=100, le=10000)
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
                "features": {key: value for key, value in feature.items() if not key.startswith("_")},
                "feature_snapshot": snapshot_by_route[route_id],
                "trait_labels": traits_by_route[route_id],
            }
            for feature in route_features
        ],
        "metadata": {**collection_metadata, "weather": req.weather},
    }


async def _collect_featured_routes(req: RecommendRequest) -> tuple[list[dict], dict]:
    origin = Coordinate(lat=req.origin_lat, lng=req.origin_lng)
    destination = Coordinate(lat=req.dest_lat, lng=req.dest_lng)
    # Opt-in OSMnx is used only inside ODsay to recover walking geometry. It has
    # no authoritative travel-time value and therefore must not become a
    # scored standalone route candidate.
    collectors = [OdsayRouteCollector(), TmapRouteCollector()]
    source_names = [collector.source_name for collector in collectors]
    results = await asyncio.gather(
        *(collector.collect(origin, destination) for collector in collectors),
        return_exceptions=True,
    )

    candidates = []
    succeeded: list[str] = []
    failed: list[str] = []
    source_errors: dict[str, str] = {}
    for source, result in zip(source_names, results):
        if isinstance(result, Exception):
            failed.append(source)
            source_errors[source] = type(result).__name__
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

    layers = _get_layers()
    merged_candidates = merge_route_candidates(candidates)
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
        feature = {
            **_parse_api_features(candidate),
            **extract_route_features_for_parts(parts, layers),
            **elevation,
            # 건물 그늘은 현재 백엔드의 검증된 building provider가 계산한다.
            # AI 후보 단계에서 확인할 수 없는 값은 0으로 추정하지 않는다.
            "shade_ratio": None,
            "shaded_walk_m": None,
            "shade_building_height_coverage": None,
            # 교통카드 시간대 데이터가 연결되기 전에는 혼잡을 추정하지 않는다.
            "crowd_level": None,
            **_weather_features(req),
            "_sources": candidate.sources,
            "_duration_min": candidate.duration_min,
            "_distance_m": candidate.distance_m,
            "_path": [{"lat": point.lat, "lng": point.lng} for point in candidate.path],
            "_segments": _enrich_subway_elevator_accessibility(
                _public_segments(candidate),
                layers,
            ),
            "_geometry_quality": candidate.geometry_quality,
        }
        feature.update(_context_features(feature, req))
        route_features.append(feature)

    return route_features, {
        "captured_at": datetime.now(UTC).isoformat(),
        "sources_attempted": source_names,
        "sources_succeeded": succeeded,
        "sources_failed": failed,
        "source_errors": source_errors,
    }


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
        candidate.source == "tmap"
        and set(candidate.sources) == {"tmap"}
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


def _route_id(feature: dict) -> str:
    path = [
        Coordinate(lat=float(point["lat"]), lng=float(point["lng"]))
        for point in feature["_path"]
    ]
    sampled_path = sample_path_by_distance(path, n=41) or path
    fingerprint = {
        "sources": sorted(feature["_sources"]),
        "path": [
            [round(point.lat, 5), round(point.lng, 5)]
            for point in sampled_path
        ],
        "segments": [
            [segment.get("mode"), segment.get("bus_route_name"), segment.get("station_name")]
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
    return text or None


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
        facility_type = str(properties.get("facilityType") or "")
        if "계단" in facility_type:
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


def _subway_elevator_lookup(layers: dict) -> dict[str, bool]:
    """역명별 엘리베이터 접근성. 중복 역명의 충돌 값은 제외한다."""
    subway = layers.get("subway")
    if subway is None:
        return {}
    seen: dict[str, set[bool]] = {}
    for _, row in subway.iterrows():
        name = _station_name_key(row.get("역명"))
        value = row.get("elevator_accessible")
        if name is None or value not in (0, 1, False, True):
            continue
        seen.setdefault(name, set()).add(bool(value))
    return {
        name: next(iter(values))
        for name, values in seen.items()
        if len(values) == 1
    }


def _enrich_subway_elevator_accessibility(
    segments: list[dict],
    layers: dict,
) -> list[dict]:
    """확인된 역사 접근성만 도시철도 구간에 추가한다.

    역에 엘리베이터가 있다는 사실은 해당 환승 동선이 반드시 수직이동을
    한다는 뜻이 아니므로 ``needs_vertical_move``은 여기서 추정하지 않는다.
    """
    lookup = _subway_elevator_lookup(layers)
    if not lookup:
        return segments
    for segment in segments:
        if segment.get("mode") != "subway" or segment.get("has_elevator") is not None:
            continue
        value = lookup.get(_station_name_key(segment.get("station_name")) or "")
        if value is not None:
            segment["has_elevator"] = value
    return segments


def _public_segments(candidate) -> list[dict]:
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
        observations.append({
            "item": item,
            "raw": raw,
            "mode": mode,
            "stairs": stairs,
            "elevator": elevator,
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
        needs_vertical_move = (
            True
            if (
                (stairs is not None and stairs > 0)
                or elevator is True
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
            "bus_route_name": str(name) if mode == "bus" and name else None,
            "is_low_floor_bus": low_floor if mode == "bus" else None,
            "station_name": start_name if mode == "subway" else None,
            "has_elevator": elevator,
            "needs_vertical_move": needs_vertical_move,
            "path": [{"lat": point.lat, "lng": point.lng} for point in item.get("path") or []] or None,
            "geometry_quality": item.get("geometry_quality"),
        })
    if segments:
        return segments
    # OSMnx/TMAP 단일 보행 후보는 실제 geometry와 공급자 거리를 보유한다.
    if candidate.source in {"osmnx", "tmap"}:
        stairs = (
            _tmap_stair_feature_count(_mapping(candidate.raw_response))
            if candidate.source == "tmap"
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
            "has_stairs": True if stairs is not None else None,
            "stairs_count": stairs,
            "needs_vertical_move": True if stairs is not None else None,
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
