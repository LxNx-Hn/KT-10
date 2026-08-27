"""중복 경로 병합 모듈.

경로의 원본 정점 수는 공급자별로 크게 다르다. 따라서 정점 인덱스를 그대로
맞춰 비교하지 않고 실제 누적 거리 기준으로 같은 수의 점을 보간한다.
"""
from dataclasses import dataclass, field
from math import radians, cos, sin, asin, sqrt
from typing import Any

from collectors.base import Coordinate

MERGE_THRESHOLD_M = 30.0
MERGE_MAX_DEVIATION_M = 60.0
PATH_SAMPLE_POINTS = 16
# 접근성 근거는 평행 보도·다른 출입구에 잘못 붙으면 위험하므로 일반 중복
# 제거보다 촘촘하고 엄격하게 같은 선형을 확인한다.
ACCESSIBILITY_MERGE_THRESHOLD_M = 12.0
ACCESSIBILITY_MERGE_MAX_DEVIATION_M = 25.0
ACCESSIBILITY_PATH_SAMPLE_POINTS = 64


@dataclass
class MergedRoute:
    sources:      list
    path:         list
    duration_min: float | None
    distance_m:   float
    raw_response: dict = field(default_factory=dict)
    source:       str = ""
    segments:     list = field(default_factory=list)
    geometry_quality: str = "exact"
    # 대표 후보의 대중교통 지연 정밀화 서술자(서버 내부 전용).
    transit_refinement: dict | None = None
    accessibility_evidence: dict = field(default_factory=dict)


def _haversine(c1: Coordinate, c2: Coordinate) -> float:
    """두 좌표 간 거리(m) 계산."""
    R = 6371000
    lat1, lon1 = radians(c1.lat), radians(c1.lng)
    lat2, lon2 = radians(c2.lat), radians(c2.lng)
    dlat, dlon = lat2 - lat1, lon2 - lon1
    a = sin(dlat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(dlon / 2) ** 2
    return R * 2 * asin(sqrt(a))


def sample_path_by_distance(
    path: list[Coordinate],
    n: int = PATH_SAMPLE_POINTS,
) -> list[Coordinate]:
    """누적 이동거리를 기준으로 시작·끝을 포함해 ``n``개 점을 보간한다."""
    if n < 2 or len(path) < 2:
        return []

    compact = [path[0]]
    for point in path[1:]:
        if _haversine(compact[-1], point) > 1e-6:
            compact.append(point)
    if len(compact) < 2:
        return []

    cumulative = [0.0]
    for start, end in zip(compact, compact[1:]):
        cumulative.append(cumulative[-1] + _haversine(start, end))
    total = cumulative[-1]
    if total <= 0:
        return []

    sampled: list[Coordinate] = []
    segment_index = 0
    for index in range(n):
        target = total * index / (n - 1)
        while (
            segment_index < len(compact) - 2
            and cumulative[segment_index + 1] < target
        ):
            segment_index += 1
        start_distance = cumulative[segment_index]
        end_distance = cumulative[segment_index + 1]
        ratio = (
            (target - start_distance) / (end_distance - start_distance)
            if end_distance > start_distance
            else 0.0
        )
        start = compact[segment_index]
        end = compact[segment_index + 1]
        sampled.append(Coordinate(
            lat=start.lat + (end.lat - start.lat) * ratio,
            lng=start.lng + (end.lng - start.lng) * ratio,
        ))
    return sampled


def _path_deviations(
    a: list,
    b: list,
    n: int = PATH_SAMPLE_POINTS,
) -> list[float]:
    """두 경로의 거리 균등 표본별 이격거리(m)를 반환한다."""
    sa = sample_path_by_distance(a, n)
    sb = sample_path_by_distance(b, n)
    if len(sa) != n or len(sb) != n:
        return []
    return [_haversine(p1, p2) for p1, p2 in zip(sa, sb)]


def _paths_similar(a: list, b: list) -> bool:
    """평균과 국소 최대 이격이 모두 작을 때만 같은 geometry로 본다."""
    deviations = _path_deviations(a, b)
    return bool(
        deviations
        and sum(deviations) / len(deviations) <= MERGE_THRESHOLD_M
        and max(deviations) <= MERGE_MAX_DEVIATION_M
    )


def paths_similar(a: list, b: list) -> bool:
    """공급자 근거를 결합해도 되는 같은 보행 경로인지 확인한다."""
    return _paths_similar(a, b)


def accessibility_paths_similar(a: list, b: list) -> bool:
    """물리 경사로·휠체어 제약을 서로 결합해도 되는 동일 선형인지 확인."""
    deviations = _path_deviations(
        a,
        b,
        ACCESSIBILITY_PATH_SAMPLE_POINTS,
    )
    return bool(
        deviations
        and sum(deviations) / len(deviations)
        <= ACCESSIBILITY_MERGE_THRESHOLD_M
        and max(deviations) <= ACCESSIBILITY_MERGE_MAX_DEVIATION_M
    )


def _has_accessibility_evidence(candidate: Any) -> bool:
    return bool(getattr(candidate, "accessibility_evidence", None))


def _mode_signature(candidate: Any) -> tuple[str, ...]:
    modes = tuple(
        str(segment.get("mode"))
        for segment in (candidate.segments or [])
        if segment.get("mode")
    )
    if modes:
        return modes
    if candidate.source in {"tmap", "osmnx", "ors"}:
        return ("walk",)
    return ()


def _list_values(value: object) -> list:
    return list(value) if isinstance(value, list) else []


def _unique_list(left: object, right: object) -> list:
    values: list = []
    for item in [*_list_values(left), *_list_values(right)]:
        if item not in values:
            values.append(item)
    return values


def merge_accessibility_evidence(left: object, right: object) -> dict:
    """같은 geometry에서 공급자별 접근성 근거를 손실 없이 합친다.

    물리 경사로(TMAP)와 휠체어 통행 제약(ORS)은 서로 대체 관계가 아니다.
    경로 유사성 검사를 통과한 후보에 한해서만 이 함수를 호출한다. 알 수 없는
    충돌 값을 임의로 True/False로 만들지 않고 ``evidence_conflicts``에 남긴다.
    """
    left_map = dict(left) if isinstance(left, dict) else {}
    right_map = dict(right) if isinstance(right, dict) else {}
    result = dict(left_map)

    providers: list[str] = []
    for mapping in (left_map, right_map):
        provider = mapping.get("provider")
        if isinstance(provider, str) and provider and provider not in providers:
            providers.append(provider)
        for item in _list_values(mapping.get("providers")):
            if isinstance(item, str) and item and item not in providers:
                providers.append(item)
    if providers:
        result["providers"] = providers

    list_keys = {
        "ramp_points",
        "avoided_features",
        "verified_extra_info",
        "wheelchair_data_limitations",
        "wheelchair_constraint_categories",
    }
    conflicts: dict[str, list] = {}
    for key, value in right_map.items():
        if key == "providers":
            continue
        if key in list_keys:
            combined = _unique_list(result.get(key), value)
            if combined:
                result[key] = combined
            continue
        if key not in result or result[key] is None:
            result[key] = value
        elif value is None or result[key] == value:
            continue
        else:
            conflicts[key] = [result[key], value]
    if conflicts:
        result["evidence_conflicts"] = conflicts
    return result


def _first_known(mapping: dict, *keys: str) -> str | None:
    for key in keys:
        value = mapping.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return None


def _transit_signature(candidate: Any) -> tuple | None:
    """확인된 노선·승하차 식별자가 모두 있을 때만 대중교통 서명을 만든다."""
    result = []
    for segment in candidate.segments or []:
        mode = segment.get("mode")
        if mode not in {"bus", "subway"}:
            continue
        raw = segment.get("raw")
        if not isinstance(raw, dict):
            return None
        lanes = raw.get("lane")
        if not isinstance(lanes, list) or not lanes:
            return None
        lane_ids = []
        for lane in lanes:
            if not isinstance(lane, dict):
                return None
            lane_id = _first_known(
                lane,
                "busID",
                "busNo",
                "subwayCode",
                "name",
            )
            if lane_id is None:
                return None
            lane_ids.append(lane_id)
        start = _first_known(raw, "startID", "startName")
        end = _first_known(raw, "endID", "endName")
        if start is None or end is None:
            return None
        optional = tuple(
            (key, str(raw[key]).strip())
            for key in ("wayCode", "way")
            if raw.get(key) is not None and str(raw[key]).strip()
        )
        result.append((mode, tuple(lane_ids), start, end, optional))
    return tuple(result) if result else None


def _merge_compatible(left: Any, right: Any) -> bool:
    left_modes = _mode_signature(left)
    right_modes = _mode_signature(right)
    if not left_modes or left_modes != right_modes:
        return False
    if any(mode in {"bus", "subway"} for mode in left_modes):
        left_transit = _transit_signature(left)
        right_transit = _transit_signature(right)
        # 식별자가 없는 두 후보를 같은 노선이라고 추정하지 않는다.
        return (
            left_transit is not None
            and right_transit is not None
            and left_transit == right_transit
        ) or _bims_tmap_semantically_same(left, right)
    return all(mode == "walk" for mode in left_modes)


def _bims_tmap_semantically_same(left: Any, right: Any) -> bool:
    """BIMS 보완 후보와 TMAP 후보가 같은 버스 구간이면 중복으로 본다.

    공급자별 정류소 ID 체계와 표시 geometry가 달라 일반 병합 기준만으로는
    같은 88번 직행이 두 카드로 남을 수 있다. 노선명·승하차 정류소명 또는
    좌표를 함께 확인하며, 다른 노선·방향은 병합하지 않는다.
    """
    sources = {getattr(left, "source", ""), getattr(right, "source", "")}
    if sources != {"bims_transit", "tmap_transit"}:
        return False
    left_segments = [segment for segment in left.segments or [] if segment.get("mode") == "bus"]
    right_segments = [segment for segment in right.segments or [] if segment.get("mode") == "bus"]
    if len(left_segments) != len(right_segments) or not left_segments:
        return False

    def normalize(value: object) -> str:
        return "".join(ch for ch in str(value or "").casefold() if ch.isalnum() or "가" <= ch <= "힣")

    for left_segment, right_segment in zip(left_segments, right_segments):
        left_raw = left_segment.get("raw") or {}
        right_raw = right_segment.get("raw") or {}
        left_lanes = left_raw.get("lane") or []
        right_lanes = right_raw.get("lane") or []
        left_names = {normalize(lane.get("busNo") or lane.get("name")) for lane in left_lanes if isinstance(lane, dict)}
        right_names = {normalize(lane.get("busNo") or lane.get("name")) for lane in right_lanes if isinstance(lane, dict)}
        if not left_names or not left_names & right_names:
            return False
        names_match = (
            normalize(left_raw.get("startName")) == normalize(right_raw.get("startName"))
            and normalize(left_raw.get("endName")) == normalize(right_raw.get("endName"))
        )
        def endpoint_close(x_key: str, y_key: str) -> bool:
            values = (left_raw.get(x_key), left_raw.get(y_key), right_raw.get(x_key), right_raw.get(y_key))
            if not all(isinstance(value, (int, float)) and not isinstance(value, bool) for value in values):
                return False
            return _haversine(
                Coordinate(float(left_raw[x_key]), float(left_raw[y_key])),
                Coordinate(float(right_raw[x_key]), float(right_raw[y_key])),
            ) <= 250.0

        coordinates_match = endpoint_close("startX", "startY") and endpoint_close("endX", "endY")
        if not names_match and not coordinates_match:
            return False
    return True


def merge_route_candidates(candidates: list) -> list:
    """
    경로 후보 리스트를 받아 중복을 병합한 MergedRoute 리스트를 반환한다.
    병합 기준: 샘플링 좌표 간 평균 거리 <= MERGE_THRESHOLD_M
    """
    merged: list[MergedRoute] = []

    for cand in candidates:
        matched = False
        for m in merged:
            if (
                _merge_compatible(cand, m)
                and (
                    _paths_similar(cand.path, m.path)
                    or _bims_tmap_semantically_same(cand, m)
                )
                and (
                    not (
                        _has_accessibility_evidence(cand)
                        or _has_accessibility_evidence(m)
                    )
                    or accessibility_paths_similar(cand.path, m.path)
                )
            ):
                if cand.source not in m.sources:
                    m.sources.append(cand.source)
                quality = {"estimated": 0, "mixed": 1, "exact": 2}
                if quality.get(cand.geometry_quality, 0) > quality.get(m.geometry_quality, 0):
                    m.source = cand.source
                    m.path = cand.path
                    m.duration_min = cand.duration_min
                    m.distance_m = cand.distance_m
                    m.raw_response = cand.raw_response
                    m.segments = cand.segments
                    m.geometry_quality = cand.geometry_quality
                    m.transit_refinement = getattr(
                        cand, "transit_refinement", None
                    )
                    m.accessibility_evidence = merge_accessibility_evidence(
                        m.accessibility_evidence,
                        getattr(cand, "accessibility_evidence", {}),
                    )
                elif cand.raw_response and not m.raw_response:
                    m.raw_response = cand.raw_response
                if m.transit_refinement is None:
                    m.transit_refinement = getattr(
                        cand, "transit_refinement", None
                    )
                m.accessibility_evidence = merge_accessibility_evidence(
                    m.accessibility_evidence,
                    getattr(cand, "accessibility_evidence", {}),
                )
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
                segments=cand.segments,
                geometry_quality=cand.geometry_quality,
                transit_refinement=getattr(cand, "transit_refinement", None),
                accessibility_evidence=dict(
                    getattr(cand, "accessibility_evidence", {})
                ),
            ))

    return merged
