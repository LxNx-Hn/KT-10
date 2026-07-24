"""경로 수집·피처 추출·학습 모델 순위화를 제공하는 AI API."""
from __future__ import annotations

import asyncio
import hashlib
import json
import math
from datetime import UTC, datetime
from typing import Any, Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from collectors.base import Coordinate
from collectors.odsay_collector import OdsayRouteCollector
from collectors.tmap_collector import TmapRouteCollector
from config import settings
from features.extractor import extract_route_features
from features.elevation import extract_elevation_features
from labeling.route_traits import generate_route_traits
from merger.route_merger import merge_route_candidates
from preprocessing.load_layers import load_all_layers
from scoring.judge_baseline import (
    load_judge_baseline_metadata,
    load_judge_baseline_rankers,
)
from scoring.predict import predict_and_rank
from scoring.snapshots import build_live_feature_snapshot
from scoring.train import FEATURE_COLS, ModelNotReady, load_model_metadata, load_rankers

router = APIRouter()

_layers = None
_rankers = None


def _get_layers():
    global _layers
    if _layers is None:
        _layers = load_all_layers(use_cache=True)
    return _layers


def _get_rankers():
    global _rankers
    if _rankers is None:
        _rankers = (
            load_judge_baseline_rankers()
            if settings.RANKER_TIER == "judge_baseline"
            else load_rankers()
        )
    return _rankers


def _get_model_metadata() -> dict:
    return (
        load_judge_baseline_metadata()
        if settings.RANKER_TIER == "judge_baseline"
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
    geometry_quality: str | None = None
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
    row: dict[str, float | int | bool | None] = {}
    for name in FEATURE_COLS:
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
            _validated_feature_row(candidate.route_id, candidate.features),
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
    elevation_features = await asyncio.gather(*(
        extract_elevation_features([(point.lat, point.lng) for point in candidate.path])
        for candidate in merged_candidates
    ))
    route_features: list[dict] = []
    for candidate, elevation in zip(merged_candidates, elevation_features):
        if candidate.duration_min is None or candidate.duration_min <= 0:
            raise HTTPException(
                status_code=502,
                detail=f"{candidate.source} 경로에 검증 가능한 소요시간이 없습니다.",
            )
        coordinates = [(point.lat, point.lng) for point in candidate.path]
        feature = {
            **_parse_api_features(candidate),
            **extract_route_features(coordinates, layers),
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
            "_segments": _public_segments(candidate),
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
    fingerprint = {
        "sources": sorted(feature["_sources"]),
        "path": [
            [round(point["lat"], 5), round(point["lng"], 5)]
            for point in feature["_path"][::max(1, len(feature["_path"]) // 40)]
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


def _parse_api_features(candidate) -> dict:
    """외부 응답에서 확인 가능한 값만 추출하며 결측을 0으로 바꾸지 않는다."""
    raw = candidate.raw_response or {}
    info = raw.get("info") or {}
    sub_paths = raw.get("subPath") or []

    transfer_count = info.get("transferCount")
    if transfer_count is None and any(key in info for key in ("busTransitCount", "subwayTransitCount")):
        transfer_count = int(info.get("busTransitCount") or 0) + int(info.get("subwayTransitCount") or 0)
    if transfer_count is None and candidate.source == "tmap":
        transfer_count = 0
    walk_distance = info.get("totalWalk")
    if walk_distance is None and candidate.source == "tmap":
        walk_distance = candidate.distance_m

    stairs = 0
    stairs_observed = False
    elevator_values: list[bool] = []
    low_floor_values: list[bool] = []
    for sub_path in sub_paths:
        if sub_path.get("trafficType") == 2:
            for lane in sub_path.get("lane") or []:
                marker = _explicit_bool(lane.get("lowFloorYn", lane.get("isLowFloor")))
                if marker is not None:
                    low_floor_values.append(marker)
        if sub_path.get("trafficType") == 3:
            stair_info = sub_path.get("stairInfo") or {}
            if "stairCount" in stair_info:
                stairs_observed = True
                stairs += int(stair_info.get("stairCount") or 0)
            marker = _explicit_bool(stair_info.get("elevatorYN"))
            if marker is not None:
                elevator_values.append(marker)

    for item in raw.get("features") or []:
        facility_type = str((item.get("properties") or {}).get("facilityType") or "")
        if "계단" in facility_type:
            stairs_observed = True
            stairs += 1

    low_floor = None
    if low_floor_values:
        low_floor = True if all(low_floor_values) else False if not any(low_floor_values) else None
    elevator_ratio = sum(elevator_values) / len(elevator_values) if elevator_values else None
    return {
        "avg_slope_percent": None,
        "max_slope_percent": None,
        "min_slope_percent": None,
        "slope_iqr": None,
        "stair_count": stairs if stairs_observed else None,
        "elevator_ratio": elevator_ratio,
        "transfer_count": transfer_count,
        "walk_distance_m": walk_distance,
        "total_duration_min": candidate.duration_min,
        "is_low_floor_bus": low_floor,
    }


def _public_segments(candidate) -> list[dict]:
    segments = []
    for index, item in enumerate(candidate.segments):
        raw = item.get("raw") or {}
        mode = item.get("mode", "transfer")
        lane = (raw.get("lane") or [{}])[0]
        start_name = raw.get("startName")
        end_name = raw.get("endName")
        name = lane.get("busNo") or lane.get("name")
        description = " → ".join(value for value in (start_name, end_name) if value)
        if name:
            description = f"{name} · {description}" if description else str(name)
        stair_info = raw.get("stairInfo") or {}
        stairs = int(stair_info.get("stairCount") or 0) if "stairCount" in stair_info else None
        elevator = _explicit_bool(stair_info.get("elevatorYN"))
        low_floor_values = [
            marker for lane_item in (raw.get("lane") or [])
            if (marker := _explicit_bool(lane_item.get("lowFloorYn", lane_item.get("isLowFloor")))) is not None
        ]
        low_floor = None if not low_floor_values else all(low_floor_values)
        segments.append({
            "id": f"{candidate.source}-{index}",
            "mode": mode,
            "description": description or {"walk": "보행 이동", "bus": "버스 이동", "subway": "도시철도 이동"}.get(mode, "환승 이동"),
            "duration_min": item["duration_min"],
            "distance_m": item.get("distance_m"),
            "outdoor": True if mode == "walk" else None,
            "has_stairs": None if stairs is None else stairs > 0,
            "stairs_count": stairs,
            "bus_route_name": str(name) if mode == "bus" and name else None,
            "is_low_floor_bus": low_floor if mode == "bus" else None,
            "station_name": start_name if mode == "subway" else None,
            "has_elevator": elevator,
            "needs_vertical_move": elevator is not None or stairs is not None,
            "path": [{"lat": point.lat, "lng": point.lng} for point in item.get("path") or []] or None,
            "geometry_quality": item.get("geometry_quality"),
        })
    if segments:
        return segments
    # OSMnx/TMAP 단일 보행 후보는 실제 geometry와 공급자 거리를 보유한다.
    if candidate.source in {"osmnx", "tmap"}:
        return [{
            "id": f"{candidate.source}-0",
            "mode": "walk",
            "description": "보행 경로",
            "duration_min": candidate.duration_min,
            "distance_m": candidate.distance_m,
            "outdoor": True,
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
