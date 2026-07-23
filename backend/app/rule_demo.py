"""설명 가능한 데모 경로 비교와 사용자별 온라인 재정렬."""
from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime

from .feedback_tokens import create_feedback_token
from .models import ScoredRoute, ScoringOptions
from .personalization import blended_rank_score, parse_state
from .scoring.explain import build_voice_summary
from .settings import settings

RULE_MODEL_VERSION = "rule-baseline-v2"
SNAPSHOT_SCHEMA_VERSION = "route-feature-snapshot-v2"
LIVE_SNAPSHOT_KIND = "live_route_candidate"
DEMO_SNAPSHOT_KIND = "demo_route_candidate"


def _snapshot_hash(snapshot: dict) -> str:
    canonical = {
        key: value
        for key, value in snapshot.items()
        if key != "feature_snapshot_hash"
    }
    return hashlib.sha256(
        json.dumps(
            canonical,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()


def route_features(
    item: ScoredRoute,
    profile: str,
    options: ScoringOptions | None = None,
) -> dict:
    opts = options or ScoringOptions()
    route = item.route
    terrain = route.terrain
    shade = route.shade
    walk_segments = [segment for segment in route.segments if segment.mode == "walk"]
    bus_segments = [segment for segment in route.segments if segment.mode == "bus"]
    vertical_segments = [segment for segment in route.segments if segment.needs_vertical_move]
    stair_values = [
        segment.stairs_count
        if segment.stairs_count is not None
        else (0 if segment.has_stairs is False else None)
        for segment in route.segments
        if segment.mode in ("walk", "transfer")
    ]
    crosswalk_values = [segment.crosswalk_count for segment in walk_segments]
    stair_count = (
        sum(value for value in stair_values if value is not None)
        if stair_values and all(value is not None for value in stair_values)
        else None
    )
    elevator_ratio = (
        sum(segment.has_elevator is True for segment in vertical_segments)
        / len(vertical_segments)
        if vertical_segments
        and all(segment.has_elevator is not None for segment in vertical_segments)
        else None
    )
    low_floor = (
        float(all(segment.is_low_floor_bus is True for segment in bus_segments))
        if bus_segments
        and all(segment.is_low_floor_bus is not None for segment in bus_segments)
        else None
    )
    shade_ratio = (
        shade.shade_ratio
        if shade and shade.status in ("estimated_demo", "estimated_public")
        else None
    )
    unshaded_walk_m = (
        route.total_walk_m * (1 - shade_ratio)
        if shade_ratio is not None
        else None
    )
    return {
        "route_id": route.id,
        "profile": profile,
        "avg_slope_percent": terrain.avg_slope_percent if terrain else None,
        "max_slope_percent": terrain.max_slope_percent if terrain else None,
        "stair_count": stair_count,
        "elevator_ratio": elevator_ratio,
        "transfer_count": route.transfer_count,
        "walk_distance_m": route.total_walk_m,
        "total_duration_min": route.total_duration_min,
        "is_low_floor_bus": low_floor,
        "crosswalk_count": (
            sum(value for value in crosswalk_values if value is not None)
            if crosswalk_values and all(value is not None for value in crosswalk_values)
            else None
        ),
        "shade_ratio": shade_ratio,
        "shaded_walk_m": (
            shade.shaded_walk_m
            if shade and shade.status in ("estimated_demo", "estimated_public") else None
        ),
        "solar_elevation_deg": (
            shade.solar_elevation_deg
            if shade and shade.status in ("estimated_demo", "estimated_public") else None
        ),
        "stair_avoidance_burden": stair_count if opts.avoid_stairs else 0.0,
        "luggage_walk_burden": route.total_walk_m if opts.carry_luggage else 0.0,
        "luggage_stair_burden": stair_count if opts.carry_luggage else 0.0,
        "low_floor_priority_mismatch": (
            None
            if opts.low_floor_priority and low_floor is None
            else float(opts.low_floor_priority and low_floor == 0)
        ),
        "stroller_walk_burden": route.total_walk_m if opts.stroller else 0.0,
        "stroller_stair_burden": stair_count if opts.stroller else 0.0,
        "stroller_elevator_gap": (
            None
            if opts.stroller and elevator_ratio is None
            else (1.0 - elevator_ratio if opts.stroller else 0.0)
        ),
        "shade_priority_unshaded_walk_m": (
            unshaded_walk_m if opts.shade_priority else 0.0
        ),
        "minimize_transfers_burden": (
            route.transfer_count if opts.minimize_transfers else 0.0
        ),
        "rule_score": item.score.final_score,
    }


def select_representative_routes(
    ranked: list[ScoredRoute], top_n: int
) -> list[ScoredRoute]:
    """대표 특성은 배지로 보존하고 결과 순서는 적합 점수순으로 유지한다."""
    return ranked[:top_n]


def personalize_and_sign(
    items: list[ScoredRoute],
    profile: str,
    personalization_state: str | None,
    options: ScoringOptions | None = None,
) -> list[ScoredRoute]:
    state = parse_state(personalization_state)
    active = int(state.get("updates", 0)) > 0
    if active and not settings.personalization_configured:
        raise RuntimeError("Personalization policy is not configured.")

    rows: list[tuple[ScoredRoute, dict]] = [
        (item, route_features(item, profile, options))
        for item in items
    ]
    if rows:
        opts = options or ScoringOptions()
        first_route = rows[0][0].route
        if settings.route_mode == "live":
            live_rows: list[tuple[ScoredRoute, dict]] = []
            group_ids: set[str] = set()
            holdout_group_ids: set[str] = set()
            captured_times: set[str] = set()
            shade_times: set[str] = set()
            for item, rule_features in rows:
                route = item.route
                snapshot = route.model_snapshot
                if (
                    not snapshot
                    or snapshot.get("snapshot_schema_version")
                    != SNAPSHOT_SCHEMA_VERSION
                    or snapshot.get("snapshot_kind") != LIVE_SNAPSHOT_KIND
                    or snapshot.get("route_id") != route.id
                    or not route.model_features
                    or snapshot.get("features") != route.model_features
                    or snapshot.get("feature_snapshot_hash")
                    != _snapshot_hash(snapshot)
                ):
                    raise RuntimeError(
                        "Live rule feedback requires a verified enriched feature snapshot."
                    )
                group_id = str(snapshot.get("group_id") or "")
                holdout_group_id = str(snapshot.get("holdout_group_id") or "")
                captured_at = str(snapshot.get("captured_at") or "")
                shade_evaluated_at = str(
                    snapshot.get("shade_evaluated_at") or ""
                )
                sources = snapshot.get("sources")
                if (
                    not group_id
                    or not holdout_group_id
                    or not captured_at
                    or not shade_evaluated_at
                    or not isinstance(sources, list)
                    or not sources
                ):
                    raise RuntimeError(
                        "Live rule feedback snapshot provenance is incomplete."
                    )
                group_ids.add(group_id)
                holdout_group_ids.add(holdout_group_id)
                captured_times.add(captured_at)
                shade_times.add(shade_evaluated_at)
                live_rows.append((
                    item,
                    {
                        **route.model_features,
                        "route_id": route.id,
                        "profile": profile,
                        "rule_score": rule_features["rule_score"],
                        "solar_elevation_deg": rule_features[
                            "solar_elevation_deg"
                        ],
                        "group_id": group_id,
                        "holdout_group_id": holdout_group_id,
                        "snapshot_schema_version": SNAPSHOT_SCHEMA_VERSION,
                        "snapshot_kind": LIVE_SNAPSHOT_KIND,
                        "captured_at": captured_at,
                        "shade_evaluated_at": shade_evaluated_at,
                        "sources": list(sources),
                        "geometry_quality": snapshot.get(
                            "geometry_quality"
                        ),
                        "feature_snapshot_hash": snapshot[
                            "feature_snapshot_hash"
                        ],
                        "training_eligible": True,
                    },
                ))
            if (
                len(group_ids) != 1
                or len(holdout_group_ids) != 1
                or len(captured_times) != 1
                or len(shade_times) != 1
            ):
                raise RuntimeError(
                    "Live rule feedback candidates do not share one query snapshot."
                )
            rows = live_rows
        else:
            if not first_route.path or len(first_route.path) < 2:
                raise RuntimeError("Signed rule feedback requires route geometry.")
            holdout_fingerprint = {
                "origin": {
                    "lat": round(first_route.path[0].lat, 5),
                    "lng": round(first_route.path[0].lng, 5),
                },
                "destination": {
                    "lat": round(first_route.path[-1].lat, 5),
                    "lng": round(first_route.path[-1].lng, 5),
                },
            }
            holdout_group_id = "od-" + hashlib.sha256(
                json.dumps(
                    holdout_fingerprint,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            ).hexdigest()[:20]
            shade_times = {
                item.route.shade.evaluated_at.astimezone(UTC).isoformat()
                for item, _ in rows
                if item.route.shade is not None
            }
            if len(shade_times) != 1:
                raise RuntimeError(
                    "Signed rule feedback requires one fixed shade evaluation time."
                )
            captured_at = datetime.now(UTC).isoformat()
            shade_evaluated_at = next(iter(shade_times))
            query_context = {
                "holdout_group_id": holdout_group_id,
                "captured_at": captured_at,
                "shade_evaluated_at": shade_evaluated_at,
                "profile": profile,
                "options": opts.model_dump(mode="json", by_alias=False),
                "route_ids": sorted(item.route.id for item, _ in rows),
            }
            group_id = "rule-" + hashlib.sha256(
                json.dumps(
                    query_context,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            ).hexdigest()[:20]
            for item, features in rows:
                route = item.route
                if not route.sources:
                    raise RuntimeError(
                        "Signed rule feedback requires route sources."
                    )
                snapshot = {
                    "snapshot_schema_version": SNAPSHOT_SCHEMA_VERSION,
                    "snapshot_kind": DEMO_SNAPSHOT_KIND,
                    "captured_at": captured_at,
                    "shade_evaluated_at": shade_evaluated_at,
                    "group_id": group_id,
                    "holdout_group_id": holdout_group_id,
                    "route_id": route.id,
                    "sources": list(route.sources),
                    "geometry_quality": route.geometry_quality,
                    "features": dict(features),
                }
                snapshot["feature_snapshot_hash"] = _snapshot_hash(snapshot)
                features.update({
                    "group_id": group_id,
                    "holdout_group_id": holdout_group_id,
                    "snapshot_schema_version": SNAPSHOT_SCHEMA_VERSION,
                    "snapshot_kind": DEMO_SNAPSHOT_KIND,
                    "captured_at": captured_at,
                    "shade_evaluated_at": shade_evaluated_at,
                    "sources": list(route.sources),
                    "geometry_quality": route.geometry_quality,
                    "feature_snapshot_hash": snapshot[
                        "feature_snapshot_hash"
                    ],
                    "training_eligible": False,
                })
    if active:
        assert settings.personalization_max_share is not None
        assert settings.personalization_prior_reviews is not None
        for item, features in rows:
            item.score.final_score = round(
                blended_rank_score(
                    item.score.final_score / 100,
                    state,
                    features,
                    max_personal_share=settings.personalization_max_share,
                    prior_reviews=settings.personalization_prior_reviews,
                ) * 100,
                1,
            )
        rows.sort(key=lambda row: row[0].score.final_score, reverse=True)

    result: list[ScoredRoute] = []
    for rank, (item, features) in enumerate(rows, start=1):
        item.score.feedback_token = create_feedback_token(
            item.route.id, RULE_MODEL_VERSION, features
        )
        item.score.voice_summary = build_voice_summary(
            item.route,
            rank,
            item.score.low_floor_status,
            item.score.cautions[0] if item.score.cautions else None,
        )
        result.append(item)
    return result
