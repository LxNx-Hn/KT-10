"""중복 경로 병합 모듈."""
from dataclasses import dataclass, field
from math import radians, cos, sin, asin, sqrt

from collectors.base import Coordinate

# 30m → 50m 상향
# 이유: TMAP과 OSMnx가 같은 도로를 살짝 다른 좌표로 표현해
#       30m 이내 기준으로 병합이 안 되는 케이스가 발생.
MERGE_THRESHOLD_M = 50.0


@dataclass
class MergedRoute:
    sources:      list
    path:         list
    duration_min: float
    distance_m:   float
    raw_response: dict = field(default_factory=dict)
    source:       str = ""


def _haversine(c1: Coordinate, c2: Coordinate) -> float:
    """두 좌표 간 거리(m) 계산."""
    R = 6371000
    lat1, lon1 = radians(c1.lat), radians(c1.lng)
    lat2, lon2 = radians(c2.lat), radians(c2.lng)
    dlat, dlon = lat2 - lat1, lon2 - lon1
    a = sin(dlat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(dlon / 2) ** 2
    return R * 2 * asin(sqrt(a))


def _sample_path(path: list, n=10) -> list:
    """경로를 n개 좌표로 균등 샘플링."""
    if len(path) <= n:
        return path
    step = len(path) / n
    return [path[int(i * step)] for i in range(n)]


def _path_similarity(a: list, b: list) -> float:
    """두 경로의 샘플링 좌표 간 평균 거리(m)를 반환. 값이 작을수록 유사."""
    sa, sb = _sample_path(a), _sample_path(b)
    if not sa or not sb:
        return float("inf")
    return sum(_haversine(p1, p2) for p1, p2 in zip(sa, sb)) / len(sa)


def merge_route_candidates(candidates: list) -> list:
    """
    경로 후보 리스트를 받아 중복을 병합한 MergedRoute 리스트를 반환한다.
    병합 기준: 샘플링 좌표 간 평균 거리 <= MERGE_THRESHOLD_M
    """
    merged: list[MergedRoute] = []

    for cand in candidates:
        matched = False
        for m in merged:
            if _path_similarity(cand.path, m.path) <= MERGE_THRESHOLD_M:
                if cand.source not in m.sources:
                    m.sources.append(cand.source)
                if cand.raw_response and not m.raw_response:
                    m.raw_response = cand.raw_response
                matched = True
                break

        if not matched:
            merged.append(MergedRoute(
                sources=[cand.source],
                source=cand.source,
                path=cand.path,
                duration_min=cand.duration_min,
                distance_m=cand.distance_m,
                raw_response=cand.raw_response or {},
            ))

    return merged
