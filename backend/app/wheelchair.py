"""휠체어 사용자 설정에만 적용하는 서버 측 안전 규칙."""
from __future__ import annotations

from .models import RouteCandidate, ScoringOptions


def effective_scoring_options(
    options: ScoringOptions,
    user_preference: object | None,
) -> ScoringOptions:
    """휠체어 사용자는 계단 회피를 해제할 수 없게 한다.

    장애인 프로필 자체와는 분리된 사용자 설정이다. 원본 요청 객체를
    변경하지 않아, 같은 route-set을 다른 사용자 조건으로 재채점해도
    이전 조건이 섞이지 않는다.
    """
    uses_wheelchair = bool(
        user_preference and getattr(user_preference, "uses_wheelchair", False)
    )
    if uses_wheelchair and not options.avoid_stairs:
        return options.model_copy(update={"avoid_stairs": True})
    return options


def filter_known_stair_candidates(
    candidates: list[RouteCandidate],
    user_preference: object | None,
) -> list[RouteCandidate]:
    """휠체어 사용자에게 통행 제약이 확인된 후보만 남긴다.

    계단 정보가 누락된 후보를 통과 가능하다고 추정하지 않는다. 모든 실제
    보행·환승 구간이 계단 제외 옵션으로 탐색됐고, ORS wheelchair profile의
    노면·평탄도·폭·턱·경사 제한도 적용돼야 한다. 경사로는 TMAP 공급자
    안내점이 있을 때만 별도로 노출하며, 지형 경사를 경사로로 대체하지 않는다.
    """
    uses_wheelchair = bool(
        user_preference and getattr(user_preference, "uses_wheelchair", False)
    )
    if not uses_wheelchair:
        return candidates
    filtered: list[RouteCandidate] = []
    for candidate in candidates:
        walk_segments = [
            segment
            for segment in candidate.segments
            if segment.mode in {"walk", "transfer"}
            and (segment.distance_m is None or segment.distance_m > 0)
        ]
        if not walk_segments:
            continue
        if all(
            segment.stairs_excluded_by_provider is True
            and segment.has_stairs is False
            and segment.stairs_count == 0
            and segment.wheelchair_constraints_applied is True
            and segment.wheelchair_constraint_source
            == "openrouteservice wheelchair profile"
            and segment.wheelchair_restrictions is not None
            and bool(segment.wheelchair_data_limitations)
            and bool(segment.wheelchair_constraint_categories)
            for segment in walk_segments
        ):
            filtered.append(candidate)
    return filtered
