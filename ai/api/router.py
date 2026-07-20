"""경로 수집·피처 추출·학습 모델 순위화를 제공하는 AI API."""
from __future__ import annotations

import asyncio
import hashlib
import json
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from collectors.base import Coordinate
from collectors.odsay_collector import OdsayRouteCollector
from collectors.tmap_collector import TmapRouteCollector
from features.extractor import extract_route_features
from features.elevation import extract_elevation_features
from merger.route_merger import merge_route_candidates
from preprocessing.load_layers import load_all_layers
from scoring.predict import predict_and_rank
from scoring.train import ModelNotReady, load_model_metadata, load_rankers

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
        _rankers = load_rankers()
    return _rankers


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


@router.get("/model/status")
def model_status() -> dict:
    """키나 라벨 내용을 노출하지 않고 운영 모델 준비 상태만 반환한다."""
    try:
        profiles = sorted(_get_rankers())
        metadata = load_model_metadata()
    except ModelNotReady as exc:
        return {"ready": False, "profiles": [], "detail": str(exc)}
    return {"ready": True, "profiles": profiles, **metadata}


@router.post("/recommend")
async def recommend(req: RecommendRequest):
    """부산 OD에 대한 실제 후보를 수집하고 검증된 프로필 모델로 순위를 정한다."""
    try:
        rankers = _get_rankers()
    except ModelNotReady as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    if req.profile not in rankers:
        raise HTTPException(status_code=503, detail=f"{req.profile} 프로필의 검증된 모델이 없습니다.")

    route_features, collection_metadata = await _collect_featured_routes(req)
    ranked = predict_and_rank(rankers, route_features, req.profile, top_k=min(10, len(route_features)))
    model_version = load_model_metadata().get("model_version") or "xgboost-human"
    group_id = _group_id(req)
    routes = []
    for rank_info in ranked:
        feature = route_features[rank_info["route_index"]]
        route_id = _route_id(feature)
        routes.append({
            "rank": rank_info["rank"],
            "model_version": model_version,
            "group_id": group_id,
            "route_id": route_id,
            "sources": feature["_sources"],
            "path": feature["_path"],
            "segments": feature["_segments"],
            "geometry_quality": feature["_geometry_quality"],
            "duration_min": feature["_duration_min"],
            "distance_m": feature["_distance_m"],
            # 내부 정렬 진단값이다. 사용자 품질 점수로 표시하지 않는다.
            "model_score": rank_info["xgb_score"],
            "selection_probability": rank_info["probability"],
            "features": {key: value for key, value in feature.items() if not key.startswith("_")},
            "reasons": _factual_reasons(feature),
            "tags": _generate_tags(feature),
        })
    return {
        "routes": routes,
        "metadata": {**collection_metadata, "profile": req.profile, "weather": req.weather},
    }


@router.post("/labeling/candidates")
async def labeling_candidates(req: RecommendRequest):
    """초기 라벨링용 후보와 당시 피처를 생성한다. 모델 준비 전에도 호출할 수 있다."""
    route_features, collection_metadata = await _collect_featured_routes(req)
    return {
        "group_id": _group_id(req),
        "candidates": [
            {
                "route_id": _route_id(feature),
                "summary": _summary(feature),
                "duration_min": feature["_duration_min"],
                "distance_m": feature["_distance_m"],
                "sources": feature["_sources"],
                "geometry_quality": feature["_geometry_quality"],
                "path": feature["_path"],
                "segments": feature["_segments"],
                "features": {key: value for key, value in feature.items() if not key.startswith("_")},
            }
            for feature in route_features
        ],
        "metadata": {**collection_metadata, "weather": req.weather},
    }


async def _collect_featured_routes(req: RecommendRequest) -> tuple[list[dict], dict]:
    origin = Coordinate(lat=req.origin_lat, lng=req.origin_lng)
    destination = Coordinate(lat=req.dest_lat, lng=req.dest_lng)
    # OSMnx is used only inside ODsay to recover walking geometry. It has no
    # authoritative travel-time value and therefore must not become a scored
    # standalone route candidate.
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
        "sources_attempted": source_names,
        "sources_succeeded": succeeded,
        "sources_failed": failed,
        "source_errors": source_errors,
    }


def _group_id(req: RecommendRequest) -> str:
    return hashlib.sha256(
        (
            f"{req.origin_lat:.5f},{req.origin_lng:.5f}->{req.dest_lat:.5f},{req.dest_lng:.5f}"
            f"|{req.weather}|luggage={int(req.carry_luggage)}|stairs={int(req.avoid_stairs)}"
            f"|lowfloor={int(req.low_floor_priority)}|wheelchair={int(req.uses_wheelchair)}"
            f"|aid={int(req.uses_walking_aid)}|maxwalk={req.max_walk_distance_m}"
            f"|weatherpriority={int(req.prioritize_weather_safety)}"
            f"|temp={req.temp_c}|feels={req.feels_like_c}|rain={req.precipitation_mm}"
            f"|wind={req.wind_ms}|pm10={req.pm10}"
        ).encode("utf-8")
    ).hexdigest()[:20]


def _context_features(feature: dict, req: RecommendRequest) -> dict:
    """사용자 조건과 경로 관측값의 상호작용만 만들며 계수는 학습 모델이 결정한다."""
    stairs = feature.get("stair_count")
    walk = feature.get("walk_distance_m")
    elevator = feature.get("elevator_ratio")
    low_floor = feature.get("is_low_floor_bus")
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


def _factual_reasons(feature: dict) -> list[str]:
    reasons = []
    if feature.get("stair_count") == 0:
        reasons.append("확인된 구간에는 계단이 없습니다.")
    if feature.get("elevator_ratio") is not None and feature["elevator_ratio"] > 0:
        reasons.append("승강기 이용 가능 구간이 확인되었습니다.")
    if feature.get("is_low_floor_bus") is True:
        reasons.append("저상버스 운행 정보가 확인되었습니다.")
    if feature.get("transfer_count") == 0:
        reasons.append("환승 없이 이동하는 경로입니다.")
    if feature.get("shelter_nearby"):
        reasons.append("경로 200m 이내에 쉼터가 확인되었습니다.")
    return reasons[:4]


def _generate_tags(feature: dict) -> list[dict]:
    tags = []
    low_floor = feature.get("is_low_floor_bus")
    if low_floor is True:
        tags.append({"label": "저상버스 확인", "tone": "positive"})
    elif low_floor is False:
        tags.append({"label": "일반버스(저상 아님) 확인", "tone": "negative"})
    else:
        tags.append({"label": "저상버스 여부 미확인", "tone": "neutral"})
    elevator = feature.get("elevator_ratio")
    if elevator is not None:
        tags.append({
            "label": "승강기 이용 확인" if elevator > 0 else "승강기 이용 불가 확인",
            "tone": "positive" if elevator > 0 else "negative",
        })
    precipitation = feature.get("precipitation_mm")
    if feature.get("weather_rain") or (precipitation is not None and precipitation > 0):
        tags.append({"label": "강수 중 실외 보행 주의", "tone": "negative"})
    if feature.get("weather_bad_air"):
        tags.append({"label": "대기질 주의 시나리오", "tone": "negative"})
    if feature.get("shelter_nearby"):
        tags.append({"label": "쉼터 근접", "tone": "positive"})
    if feature.get("aed_nearby"):
        tags.append({"label": "AED 근접", "tone": "positive"})
    return tags
