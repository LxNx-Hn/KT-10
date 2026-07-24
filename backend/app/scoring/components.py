"""
11개 하위 점수 계산 함수. 순수 함수, 0~100 "좋음 점수"를 반환한다.
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


def _stair_count(s: RouteSegment) -> int | None:
    if s.stairs_count is not None:
        return s.stairs_count
    if s.has_stairs is True:
        return 20
    if s.has_stairs is False:
        return 0
    return None


def score_accessibility(r: RouteCandidate) -> float | None:
    relevant = [
        segment
        for segment in r.segments
        if segment.mode in ("walk", "transfer") or segment.needs_vertical_move
    ]
    if not relevant:
        return None
    penalty = 0.0
    for s in relevant:
        stairs = _stair_count(s) if s.mode in ("walk", "transfer") else 0
        if stairs is None:
            return None
        if stairs > 0:
            if s.has_elevator is True:
                penalty += 3
            elif s.has_elevator is False:
                penalty += 18
            else:
                return None
        elif s.needs_vertical_move:
            if s.has_elevator is None:
                return None
            if s.has_elevator is False:
                penalty += 18
    return clamp(100 - penalty)


def score_walk_comfort(r: RouteCandidate) -> float:
    dist_penalty = clamp(r.total_walk_m / 25, 0, 50)
    walk_min = sum(s.duration_min for s in _walk_segs(r))
    time_penalty = clamp(walk_min * 0.8, 0, 20)
    transfer_penalty = clamp(r.transfer_count * 4, 0, 16)
    return clamp(
        100 - dist_penalty - time_penalty - transfer_penalty
    )


def score_slope_comfort(r: RouteCandidate) -> float | None:
    """90m 지형 추정이 있을 때만 경사 편의 점수를 계산한다."""
    terrain = r.terrain
    if (
        terrain is None
        or terrain.status != "estimated_90m"
        or terrain.max_slope_percent is None
        or terrain.min_slope_percent is None
    ):
        return None
    worst_grade = max(
        abs(terrain.max_slope_percent),
        abs(terrain.min_slope_percent),
    )
    return clamp(100 - worst_grade * 8)


def score_shade_comfort(r: RouteCandidate) -> float | None:
    """확인 가능한 주간 건물 그늘만 점수화하고 미확인은 None으로 둔다."""
    shade = r.shade
    if (
        shade is None
        or shade.status not in ("estimated_demo", "estimated_public")
        or shade.shade_ratio is None
    ):
        return None
    return clamp(shade.shade_ratio * 100)


def score_transfer_simplicity(r: RouteCandidate) -> float:
    return clamp(100 - r.transfer_count * 25)


def score_elevator(r: RouteCandidate) -> float | None:
    vs = _vertical_segs(r)
    if not vs:
        return None
    if any(s.has_elevator is None for s in vs):
        return None
    per = []
    for s in vs:
        if s.has_elevator is True:
            per.append(100)
        elif s.has_elevator is False:
            per.append(25)
    return clamp(avg(per, 0))


def score_low_floor_bus(r: RouteCandidate) -> float | None:
    bs = _bus_segs(r)
    if not bs:
        return None
    if any(s.is_low_floor_bus is None for s in bs):
        return None
    per = []
    for s in bs:
        if s.is_low_floor_bus is True:
            per.append(100)
        elif s.is_low_floor_bus is False:
            per.append(35)
    mean = avg(per, 0)
    worst = min(per)
    return clamp(mean * 0.5 + worst * 0.5)


def score_weather_safety(r: RouteCandidate, w: WeatherCondition) -> float | None:
    walk_segments = _walk_segs(r)
    if not walk_segments or any(s.outdoor is None for s in walk_segments):
        # 실내·실외 미확인을 실외 0분으로 계산하면 폭염·한파·미세먼지에서
        # 근거 없는 100점이 된다. 노출 여부가 확인될 때만 산정한다.
        return None
    outdoor_walk = [s for s in walk_segments if s.outdoor]
    outdoor_walk_min = sum(s.duration_min for s in outdoor_walk)
    # 검증된 그늘만 노출시간을 감면한다. 미확인 그늘을 0으로 대입하지 않는다.
    heat_exposed_walk_min = outdoor_walk_min
    if (
        r.shade
        and r.shade.status in ("estimated_demo", "estimated_public")
        and r.shade.shade_ratio is not None
    ):
        heat_exposed_walk_min *= 1 - r.shade.shade_ratio
    bus_segments = _bus_segs(r)
    if (
        (w.is_coldwave or w.feels_like_c <= -5)
        and any(s.wait_min is None for s in bus_segments)
    ):
        return None
    wait_min = sum(s.wait_min for s in bus_segments if s.wait_min is not None)
    if (
        (w.precipitation_mm > 0 or w.sky in ("rain", "snow"))
        and any(
            s.has_stairs is None and s.stairs_count is None
            for s in r.segments
            if s.mode in ("walk", "transfer")
        )
    ):
        return None
    has_stairs_or_slope = any(s.has_stairs or s.has_slope for s in r.segments)

    risk = 0.0
    if w.is_heatwave or w.feels_like_c >= 33:
        risk += clamp(heat_exposed_walk_min * 1.5, 0, 35) + (10 if w.is_heatwave else 0)
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


def score_safety(r: RouteCandidate) -> float | None:
    walk_segments = _walk_segs(r)
    if not walk_segments or any(s.crosswalk_count is None for s in walk_segments):
        return None
    crosswalks = sum(s.crosswalk_count for s in walk_segments if s.crosswalk_count is not None)
    penalty = clamp(crosswalks * 5, 0, 30)
    penalty += clamp(r.transfer_count * 2, 0, 10)
    return clamp(100 - penalty)


def score_data_reliability(r: RouteCandidate) -> float:
    known = 0
    total = 0
    for s in r.segments:
        if s.mode in ("walk", "transfer"):
            total += 1
            if s.stairs_count is not None or s.has_stairs is not None:
                known += 1
        if s.mode == "walk":
            total += 1
            if s.crosswalk_count is not None:
                known += 1
        if s.mode == "bus":
            total += 1
            if s.is_low_floor_bus is not None:
                known += 1
        if s.needs_vertical_move:
            total += 1
            if s.has_elevator is not None:
                known += 1
    if total == 0:
        return 100.0
    return clamp(40 + (known / total) * 60)


def score_time_efficiency(duration_min: float, fastest_min: float) -> float:
    extra = max(0.0, duration_min - fastest_min)
    return clamp(100 - extra * 2.5, 40, 100)
