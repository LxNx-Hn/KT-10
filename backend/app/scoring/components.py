"""
8개 하위 점수 계산 함수 (기획서 §7). 순수 함수, 0~100 "좋음 점수" 반환.
프론트엔드 scoring/components.ts 와 동일한 산식.
"""
from __future__ import annotations

from ..models import RouteCandidate, RouteSegment, WeatherCondition
from .utils import avg, clamp


def _walk_segs(r: RouteCandidate) -> list[RouteSegment]:
    return [s for s in r.segments if s.mode == "walk"]


def _bus_segs(r: RouteCandidate) -> list[RouteSegment]:
    return [s for s in r.segments if s.mode == "bus"]


def _vertical_segs(r: RouteCandidate) -> list[RouteSegment]:
    return [s for s in r.segments if s.needs_vertical_move]


def _stair_count(s: RouteSegment) -> int:
    if s.stairs_count is not None:
        return s.stairs_count
    return 20 if s.has_stairs else 0


def score_accessibility(r: RouteCandidate) -> float:
    penalty = 0.0
    for s in r.segments:
        if _stair_count(s) > 0:
            if s.has_elevator is True:
                penalty += 3
            elif s.has_elevator is False:
                penalty += 18
            else:
                penalty += 11
        if s.has_slope:
            penalty += 8
        if s.mode == "bus":
            if s.is_low_floor_bus is False:
                penalty += 8
            elif s.is_low_floor_bus is None:
                penalty += 4
    return clamp(100 - penalty)


def score_walk_comfort(r: RouteCandidate) -> float:
    dist_penalty = clamp(r.total_walk_m / 25, 0, 50)
    walk_min = sum(s.duration_min for s in _walk_segs(r))
    time_penalty = clamp(walk_min * 0.8, 0, 20)
    stairs = sum(_stair_count(s) for s in r.segments)
    stair_penalty = clamp(stairs * 0.6, 0, 25)
    slope_penalty = clamp(sum(1 for s in r.segments if s.has_slope) * 6, 0, 18)
    transfer_penalty = clamp(r.transfer_count * 4, 0, 16)
    return clamp(
        100 - dist_penalty - time_penalty - stair_penalty - slope_penalty - transfer_penalty
    )


def score_elevator(r: RouteCandidate) -> float:
    vs = _vertical_segs(r)
    if not vs:
        return 85.0
    per = []
    for s in vs:
        if s.has_elevator is True:
            per.append(100)
        elif s.has_elevator is False:
            per.append(25)
        else:
            per.append(50)
    return clamp(avg(per, 85))


def score_low_floor_bus(r: RouteCandidate) -> float:
    bs = _bus_segs(r)
    if not bs:
        return 80.0
    per = []
    for s in bs:
        if s.is_low_floor_bus is True:
            per.append(100)
        elif s.is_low_floor_bus is False:
            per.append(35)
        else:
            per.append(55)
    mean = avg(per, 80)
    worst = min(per)
    return clamp(mean * 0.5 + worst * 0.5)


def score_weather_safety(r: RouteCandidate, w: WeatherCondition) -> float:
    outdoor_walk = [s for s in _walk_segs(r) if s.outdoor]
    outdoor_walk_min = sum(s.duration_min for s in outdoor_walk)
    wait_min = sum((s.wait_min or 0) for s in _bus_segs(r))
    has_stairs_or_slope = any(s.has_stairs or s.has_slope for s in r.segments)

    risk = 0.0
    if w.is_heatwave or w.feels_like_c >= 33:
        risk += clamp(outdoor_walk_min * 1.5, 0, 35) + (10 if w.is_heatwave else 0)
    if w.is_coldwave or w.feels_like_c <= -5:
        risk += clamp(wait_min * 2, 0, 25) + clamp(outdoor_walk_min * 0.5, 0, 10)
    if w.precipitation_mm > 0 or w.sky in ("rain", "snow"):
        risk += 10 + (15 if has_stairs_or_slope else 0) + clamp(outdoor_walk_min * 0.5, 0, 10)
    if w.air == "bad":
        risk += clamp(outdoor_walk_min * 1.0, 0, 20)
    if w.air == "very_bad":
        risk += clamp(outdoor_walk_min * 1.0, 0, 20) + 10
    if w.wind_ms >= 9:
        risk += 8
    return clamp(100 - risk)


def score_safety(r: RouteCandidate) -> float:
    crosswalks = sum((s.crosswalk_count or 0) for s in r.segments)
    penalty = clamp(crosswalks * 5, 0, 30)
    penalty += clamp(r.transfer_count * 2, 0, 10)
    return clamp(100 - penalty)


def score_data_reliability(r: RouteCandidate) -> float:
    known = 0
    total = 0
    for s in r.segments:
        if s.mode == "bus":
            total += 1
            if s.is_low_floor_bus is not None:
                known += 1
        if s.needs_vertical_move:
            total += 1
            if s.has_elevator is not None:
                known += 1
    if total == 0:
        return 90.0
    return clamp(40 + (known / total) * 60)


def score_time_efficiency(duration_min: float, fastest_min: float) -> float:
    extra = max(0.0, duration_min - fastest_min)
    return clamp(100 - extra * 2.5, 40, 100)
