"""
ai/ 파이프라인 서버 연동 — 경로 추천을 서버간 REST 호출로 위임한다.

기존 scoring/engine.py 는 세그먼트 단위 상세 정보(계단·엘리베이터·저상버스 여부)를
전제로 8개 세부점수를 계산하지만, ai/ 서버 응답은 경로 전체 집계값
(stair_count, elevator_ratio 등)만 제공한다. 따라서 세그먼트는 경로 전체를
나타내는 가상 세그먼트 1개로 압축하고, 세부점수도 집계값 기반의 간단한 산식으로
근사한다 (기존 scoring/components.py 산식과는 무관 — 정밀도가 낮은 근사치).
"""
from __future__ import annotations

import logging

import httpx

from ..models import (
    LowFloorStatus,
    Place,
    RouteCandidate,
    RouteScore,
    RouteSegment,
    ScoreComponents,
    ScoreDisplay,
    ScoredRoute,
    ScoringOptions,
)
from ..scoring.components import score_time_efficiency
from ..scoring.utils import clamp, round1
from ..settings import settings

log = logging.getLogger("providers.ai_pipeline")

# ai/ 서버는 weather="dust"를 모르므로 매핑한다 (WeatherScenarioId와 ai 서버 enum이 다름).
_WEATHER_TO_AI = {
    "normal": "normal", "heatwave": "heatwave", "coldwave": "coldwave",
    "rain": "rain", "dust": "bad_air",
}


async def get_ai_pipeline_routes(
    origin: Place,
    destination: Place,
    profile: str,
    weather_scenario: str,
    options: ScoringOptions,
    top_n: int = 3,
) -> list[ScoredRoute]:
    """ai/ 서버 /recommend 호출 후 ScoredRoute 리스트로 변환해 반환한다."""
    payload = {
        "origin_lat": origin.lat, "origin_lng": origin.lng, "origin_name": origin.name,
        "dest_lat": destination.lat, "dest_lng": destination.lng, "dest_name": destination.name,
        "profile": profile,
        "weather": _WEATHER_TO_AI.get(weather_scenario, "normal"),
        "prioritize_weather_safety": options.weather_avoid,
    }
    try:
        async with httpx.AsyncClient(timeout=settings.request_timeout * 5) as client:
            response = await client.post(f"{settings.ai_server_url}/recommend", json=payload)
            response.raise_for_status()
        data = response.json()
    except Exception as exc:
        log.warning("ai/ 파이프라인 서버 호출 실패 (%s)", type(exc).__name__)
        raise RuntimeError("ai pipeline server request failed") from exc

    routes = data.get("routes") or []
    if not routes:
        raise RuntimeError("ai pipeline server returned no routes")

    fastest_min = min(r["duration_min"] for r in routes) or 1.0
    scored = [
        _to_scored_route(r, origin, destination, fastest_min)
        for r in routes
    ]
    return scored[:top_n]


def _to_scored_route(r: dict, origin: Place, destination: Place, fastest_min: float) -> ScoredRoute:
    feat = r["features"]
    tags = r.get("tags", [])
    reasons = r.get("reasons", [])
    rank = r["rank"]

    transfer_count = int(feat.get("transfer_count", 0))
    mode = "transfer" if transfer_count > 0 else "walk"
    is_low_floor = feat.get("is_low_floor_bus")

    segment = RouteSegment(
        id=f"ai-{rank}-0",
        mode=mode,
        description=f"AI 추천 경로 ({'+'.join(r.get('sources', []))})",
        duration_min=r["duration_min"],
        distance_m=r["distance_m"],
        outdoor=True,
        has_stairs=feat.get("stair_count", 0) > 0,
        stairs_count=int(feat.get("stair_count", 0)),
        has_slope=feat.get("avg_slope_percent", 0) > 5,
        crosswalk_count=int(feat.get("crosswalk_count", 0)),
        is_low_floor_bus=bool(is_low_floor) if is_low_floor is not None else None,
        needs_vertical_move=feat.get("stair_count", 0) > 0 or feat.get("elevator_ratio", 0) > 0,
        has_elevator=(
            True if feat.get("elevator_ratio", 0) >= 0.5
            else (False if feat.get("elevator_ratio", 0) == 0 else None)
        ),
    )

    route = RouteCandidate(
        id=f"ai-{rank}",
        summary=f"{origin.name} → {destination.name}",
        origin=origin.name,
        destination=destination.name,
        segments=[segment],
        total_duration_min=r["duration_min"],
        total_walk_m=feat.get("walk_distance_m", 0) or r["distance_m"],
        transfer_count=transfer_count,
        path=[{"lat": p["lat"], "lng": p["lng"]} for p in r.get("path", [])] or None,
    )

    components = _approximate_components(feat, r, fastest_min)
    low_floor_status = _derive_low_floor_status(mode, is_low_floor)
    cautions = [t["label"] for t in tags if t.get("tone") == "negative"]
    voice_summary = (
        f"{rank}순위 추천 경로입니다. 총 {round(r['duration_min'])}분, "
        f"{round(r['distance_m'])}미터 이동합니다."
        + (f" {reasons[0]}" if reasons else "")
    )

    score = RouteScore(
        route_id=route.id,
        components=components,
        display=ScoreDisplay(
            walk_burden=round1(100 - components.walk_comfort),
            weather_risk=round1(100 - components.weather_safety),
        ),
        # ai 서버의 raw final_score(adjusted_score*100)는 합성 데이터로 학습된
        # XGBRanker의 비정규화 로짓 값이라 프로필에 따라 크게 음수로 튈 수 있다
        # (예: general 프로필에서 -133 관측). Softmax로 정규화된 probability(0~1)
        # 기반으로 0~100 표시 점수를 산출해 항상 안정적으로 구간 내에 들어오게 한다.
        final_score=round1(clamp(r.get("probability", 0) * 100)),
        low_floor_status=low_floor_status,
        reasons=reasons,
        cautions=cautions,
        voice_summary=voice_summary,
    )
    return ScoredRoute(route=route, score=score)


def _approximate_components(feat: dict, r: dict, fastest_min: float) -> ScoreComponents:
    """
    ai/ 서버의 경로 전체 집계 피처로부터 8개 세부점수를 근사한다.
    기존 scoring/components.py(세그먼트 단위 정밀 계산)와는 무관한 단순 산식이다.
    """
    stair_count = feat.get("stair_count", 0)
    elevator_ratio = feat.get("elevator_ratio", 0)
    transfer_count = feat.get("transfer_count", 0)
    crosswalk_count = feat.get("crosswalk_count", 0)
    crosswalk_signal_ratio = feat.get("crosswalk_signal_ratio", 1.0)
    walk_distance_m = feat.get("walk_distance_m", 0) or r["distance_m"]
    weather_risk = feat.get("weather_risk", 0)
    is_low_floor = feat.get("is_low_floor_bus")

    return ScoreComponents(
        accessibility=clamp(100 - stair_count * 8 - (1 - elevator_ratio) * 15),
        walk_comfort=clamp(100 - walk_distance_m / 25 - stair_count * 5 - transfer_count * 4),
        elevator=clamp(elevator_ratio * 100, 0, 100) if stair_count > 0 or elevator_ratio > 0 else 85.0,
        low_floor_bus=100.0 if is_low_floor else (35.0 if is_low_floor is False else 80.0),
        weather_safety=clamp(100 - weather_risk * 2),
        safety=clamp(70 + crosswalk_signal_ratio * 30 - crosswalk_count * 3),
        data_reliability=70.0,  # ai 파이프라인은 세그먼트 단위 raw 데이터를 주지 않아 고정값 사용
        time_efficiency=score_time_efficiency(r["duration_min"], fastest_min),
    )


def _derive_low_floor_status(mode: str, is_low_floor) -> LowFloorStatus:
    if mode == "walk":
        return "none"
    if is_low_floor is True:
        return "confirmed"
    if is_low_floor is False:
        return "regular"
    return "unknown"
