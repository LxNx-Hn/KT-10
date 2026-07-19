"""AI 서버 FastAPI 라우터 — 경로 추천 엔드포인트."""
import asyncio

import pandas as pd
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from collectors.base import Coordinate
from collectors.odsay_collector import OdsayRouteCollector
from collectors.tmap_collector import TmapRouteCollector
from collectors.osmnx_collector import OsmnxRouteCollector
from merger.route_merger import merge_route_candidates
from preprocessing.load_layers import load_all_layers
from features.extractor import extract_route_features
from scoring.train import load_rankers, FEATURE_COLS
from scoring.predict import predict_and_rank
from scoring.explain import generate_reasons

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


class RecommendRequest(BaseModel):
    origin_lat: float
    origin_lng: float
    origin_name: str
    dest_lat: float
    dest_lng: float
    dest_name: str
    profile: str
    weather: str = "normal"
    prioritize_weather_safety: bool = False


@router.post("/recommend")
async def recommend(req: RecommendRequest):
    """
    출발지·도착지·프로필·날씨를 받아 추천 경로 Top-3를 반환한다.

    흐름:
      경로 수집 → 병합 → 피처 추출 → XGB 스코어링
      → 로짓 패널티 → Softmax → SHAP 추천 이유 → 응답 반환
    """
    if req.profile not in ("general", "elderly", "child", "disabled"):
        raise HTTPException(status_code=400, detail=f"지원하지 않는 프로필: {req.profile}")

    origin = Coordinate(lat=req.origin_lat, lng=req.origin_lng)
    dest = Coordinate(lat=req.dest_lat, lng=req.dest_lng)

    # 1. 경로 후보 수집 (병렬 호출)
    collectors = [OdsayRouteCollector(), TmapRouteCollector(), OsmnxRouteCollector()]
    src_names = ["odsay", "tmap", "osmnx"]

    results = await asyncio.gather(
        *[c.collect(origin, dest) for c in collectors],
        return_exceptions=True,
    )

    all_candidates = []
    sources_succeeded = []
    sources_failed = []

    for i, result in enumerate(results):
        src = src_names[i]
        if isinstance(result, Exception) or not result:
            sources_failed.append(src)
        else:
            sources_succeeded.append(src)
            all_candidates.extend(result)

    if not all_candidates:
        raise HTTPException(status_code=503, detail="경로 수집 실패 — 모든 소스 응답 없음")

    # 2. 중복 병합
    merged = merge_route_candidates(all_candidates)

    # 3. 날씨 위험도
    weather_risk = _calc_weather_risk(req.weather, req.prioritize_weather_safety)

    # 4. 피처 추출
    layers = _get_layers()
    route_features_list = []

    for candidate in merged:
        coords = [(c.lat, c.lng) for c in candidate.path]
        spatial_feats = extract_route_features(coords, layers)
        api_feats = _parse_api_features(candidate)
        env_feats = {
            "crowd_level": _estimate_crowd_level(req.weather),
            "weather_risk": weather_risk,
        }

        all_feats = {**api_feats, **spatial_feats, **env_feats}

        # 메타 정보 (스코어링 후 응답 조립에 사용)
        all_feats["_sources"] = candidate.sources
        all_feats["_duration_min"] = candidate.duration_min
        all_feats["_distance_m"] = candidate.distance_m
        all_feats["_path"] = [{"lat": c.lat, "lng": c.lng} for c in candidate.path]

        route_features_list.append(all_feats)

    # 5. XGB 스코어링 → 로짓 패널티 → Softmax
    rankers = _get_rankers()
    ranked = predict_and_rank(rankers, route_features_list, req.profile, top_k=3)

    # 6. 응답 조립
    routes = []
    for rank_info in ranked:
        idx = rank_info["route_index"]
        feat = route_features_list[idx]

        X_route = pd.DataFrame([{col: feat.get(col, 0) for col in FEATURE_COLS}])
        reasons = generate_reasons(rankers[req.profile], X_route)
        tags = _generate_tags(feat, weather_risk)

        routes.append({
            "rank": rank_info["rank"],
            "sources": feat["_sources"],
            "path": feat["_path"],
            "duration_min": feat["_duration_min"],
            "distance_m": feat["_distance_m"],
            "final_score": round(rank_info["adjusted_score"] * 100, 1),
            "probability": rank_info["probability"],
            "features": {
                "stair_count": feat.get("stair_count", 0),
                "avg_slope_percent": feat.get("avg_slope_percent", 0),
                "max_slope_percent": feat.get("max_slope_percent", 0),
                "elevator_ratio": feat.get("elevator_ratio", 0),
                "transfer_count": feat.get("transfer_count", 0),
                "walk_distance_m": feat.get("walk_distance_m", 0),
                "is_low_floor_bus": feat.get("is_low_floor_bus", 0),
                "shelter_nearby": feat.get("shelter_nearby", 0),
                "aed_nearby": feat.get("aed_nearby", 0),
                "crosswalk_count": feat.get("crosswalk_count", 0),
                "crosswalk_signal_ratio": feat.get("crosswalk_signal_ratio", 1.0),
                "weather_risk": feat.get("weather_risk", 0),
                "crowd_level": feat.get("crowd_level", 0),
            },
            "reasons": reasons,
            "tags": tags,
        })

    return {
        "routes": routes,
        "metadata": {
            "sources_attempted": src_names,
            "sources_succeeded": sources_succeeded,
            "sources_failed": sources_failed,
            "profile": req.profile,
            "weather": req.weather,
        },
    }


# ─────────────────────────────────────────
# 내부 헬퍼 함수
# ─────────────────────────────────────────

def _parse_api_features(candidate) -> dict:
    """
    ODsay / TMAP raw_response에서 접근성 피처를 파싱한다.
    응답이 없거나 파싱 불가 시 기본값(0)으로 채운다.
    """
    raw = candidate.raw_response or {}

    stair_count = 0
    is_low_floor = 0

    # ODsay 응답 파싱
    info = raw.get("info", {})
    transfer_count = info.get("transferCount", 0)
    walk_distance_m = info.get("totalWalk", 0)

    sub_paths = raw.get("subPath", [])
    elevator_segments = 0
    total_segments = max(len(sub_paths), 1)

    for sub in sub_paths:
        if sub.get("trafficType") == 2:
            lanes = sub.get("lane", [{}])
            for lane in lanes:
                if "저상" in str(lane.get("busNo", "")):
                    is_low_floor = 1
        if sub.get("trafficType") == 3:
            if sub.get("stairInfo", {}).get("elevatorYN") == "Y":
                elevator_segments += 1

    elevator_ratio = elevator_segments / total_segments

    # TMAP 응답 파싱 (facilityType으로 계단 카운트)
    for feat in raw.get("features", []):
        props = feat.get("properties", {})
        facility = str(props.get("facilityType", ""))
        if "계단" in facility:
            stair_count += 1

    return {
        "avg_slope_percent": 0.0,   # TODO: DEM 데이터 연동 후 채움
        "max_slope_percent": 0.0,
        "min_slope_percent": 0.0,
        "slope_iqr": 0.0,
        "stair_count": stair_count,
        "elevator_ratio": elevator_ratio,
        "transfer_count": transfer_count,
        "walk_distance_m": walk_distance_m,
        "total_duration_min": candidate.duration_min,
        "is_low_floor_bus": is_low_floor,
    }


def _calc_weather_risk(weather: str, prioritize: bool) -> float:
    """날씨 조건 → 위험도 점수 (0~30)."""
    base = {"normal": 0, "heatwave": 20, "coldwave": 20, "rain": 15, "bad_air": 10}
    risk = float(base.get(weather, 0))
    return risk * 1.5 if prioritize else risk


def _estimate_crowd_level(weather: str) -> float:
    """날씨 조건으로 혼잡도 추정 (0~1). 실제 KT 교통카드 데이터 수신 후 교체."""
    return {"heatwave": 0.3, "coldwave": 0.3, "rain": 0.6}.get(weather, 0.5)


def _generate_tags(feat: dict, weather_risk: float) -> list:
    """경로 특성 태그 생성."""
    tags = []

    if feat.get("is_low_floor_bus"):
        tags.append({"label": "저상버스 확인", "tone": "positive"})
    elif feat.get("transfer_count", 0) == 0 and feat.get("walk_distance_m", 0) < 200:
        tags.append({"label": "버스 미이용", "tone": "neutral"})
    else:
        tags.append({"label": "일반버스(저상 아님)", "tone": "negative"})

    if feat.get("elevator_ratio", 0) > 0.5:
        tags.append({"label": "승강기 양호", "tone": "positive"})

    if weather_risk < 10:
        tags.append({"label": "날씨 위험 낮음", "tone": "positive"})
    elif weather_risk >= 20:
        tags.append({"label": "날씨 위험 높음", "tone": "negative"})

    if feat.get("shelter_nearby"):
        tags.append({"label": "쉼터 근접", "tone": "positive"})

    if feat.get("aed_nearby"):
        tags.append({"label": "AED 근접", "tone": "positive"})

    return tags
