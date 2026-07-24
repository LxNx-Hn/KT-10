"""AI 경로 서버 응답을 프론트엔드 공통 도메인 모델로 변환한다."""
from __future__ import annotations

import hashlib
import json
import logging
import math
from dataclasses import dataclass
from datetime import UTC, datetime

import httpx

from ..models import (
    LowFloorStatus,
    Place,
    RouteCandidate,
    RouteScore,
    RouteSegment,
    RouteTraitLabel,
    ScoreComponents,
    ScoreDisplay,
    ScoredRoute,
    ScoringOptions,
    TerrainSummary,
)
from ..feedback_tokens import create_feedback_token
from ..personalization import blended_rank_score, parse_state
from ..scoring.utils import clamp, round1
from ..settings import settings

log = logging.getLogger("providers.ai_pipeline")


@dataclass(frozen=True)
class EnrichedCandidateBundle:
    group_id: str
    captured_at: str
    shade_evaluated_at: str
    snapshots: dict[str, dict]
    traits: dict[str, dict]


class AIProviderError(RuntimeError):
    def __init__(self, status_code: int, detail: str):
        super().__init__(detail)
        self.status_code = status_code

_WEATHER_TO_AI = {
    "normal": "normal", "heatwave": "heatwave", "coldwave": "coldwave",
    "rain": "rain", "dust": "bad_air",
}

_DISPLAY_ONLY_TERRAIN_FEATURES = frozenset({
    "uphill_distance_m",
    "downhill_distance_m",
    "elevation_gain_m",
    "elevation_loss_m",
    "elevation_source",
    "elevation_resolution_m",
    "elevation_status",
})


def _pipeline_payload(
    origin: Place,
    destination: Place,
    profile: str,
    weather_scenario: str,
    options: ScoringOptions,
    user_preference=None,
    weather_condition=None,
) -> dict:
    return {
        "origin_lat": origin.lat, "origin_lng": origin.lng, "origin_name": origin.name,
        "dest_lat": destination.lat, "dest_lng": destination.lng, "dest_name": destination.name,
        "profile": profile,
        "weather": _WEATHER_TO_AI.get(weather_scenario, "normal"),
        "prioritize_weather_safety": options.weather_avoid,
        "carry_luggage": options.carry_luggage,
        "stroller": options.stroller,
        "avoid_stairs": options.avoid_stairs or bool(
            user_preference and user_preference.avoid_stairs_required
        ),
        "low_floor_priority": options.low_floor_priority,
        "shade_priority": options.shade_priority,
        "minimize_transfers": options.minimize_transfers,
        "uses_wheelchair": bool(user_preference and user_preference.uses_wheelchair),
        "uses_walking_aid": bool(user_preference and user_preference.uses_walking_aid),
        "max_walk_distance_m": (
            user_preference.max_walk_distance_m if user_preference else None
        ),
        "temp_c": weather_condition.temp_c if weather_condition else None,
        "feels_like_c": weather_condition.feels_like_c if weather_condition else None,
        "precipitation_mm": (
            weather_condition.precipitation_mm if weather_condition else None
        ),
        "wind_ms": weather_condition.wind_ms if weather_condition else None,
        "pm10": weather_condition.pm10 if weather_condition else None,
    }


def _response_detail(response: httpx.Response) -> str:
    try:
        detail = response.json().get("detail")
    except (ValueError, TypeError, AttributeError):
        detail = None
    if isinstance(detail, str):
        return detail
    if isinstance(detail, dict) and isinstance(detail.get("message"), str):
        return detail["message"]
    return f"AI pipeline server returned HTTP {response.status_code}."


async def _post_pipeline(path: str, payload: dict) -> dict:
    if not settings.ai_server_url:
        raise AIProviderError(503, "AI_SERVER_URL is not configured.")
    try:
        async with httpx.AsyncClient(timeout=settings.request_timeout * 8) as client:
            response = await client.post(
                f"{settings.ai_server_url.rstrip('/')}{path}",
                json=payload,
            )
            response.raise_for_status()
        data = response.json()
        if not isinstance(data, dict):
            raise TypeError("pipeline response must be an object")
        return data
    except httpx.HTTPStatusError as exc:
        status = exc.response.status_code
        log.warning("AI 경로 서버가 HTTP %s를 반환했습니다.", status)
        raise AIProviderError(
            503 if status == 503 else 502,
            _response_detail(exc.response),
        ) from exc
    except (httpx.HTTPError, ValueError, TypeError, KeyError) as exc:
        log.warning("AI 경로 서버 호출 실패 (%s)", type(exc).__name__)
        raise AIProviderError(502, "AI pipeline server request failed.") from exc


async def get_ai_pipeline_candidates(
    origin: Place,
    destination: Place,
    profile: str = "general",
    weather_scenario: str = "normal",
    options: ScoringOptions | None = None,
    user_preference=None,
    weather_condition=None,
) -> list[RouteCandidate]:
    """학습 모델 없이도 실제 geometry·지형 피처가 있는 후보를 수집한다."""
    payload = _pipeline_payload(
        origin,
        destination,
        profile,
        weather_scenario,
        options or ScoringOptions(),
        user_preference,
        weather_condition,
    )
    data = await _post_pipeline("/labeling/candidates", payload)
    candidates = data.get("candidates") or []
    if not isinstance(candidates, list) or not candidates:
        raise AIProviderError(502, "AI pipeline server returned no route candidates.")
    try:
        return [
            _to_route_candidate(item, origin, destination, index + 1)
            for index, item in enumerate(candidates)
        ]
    except (KeyError, TypeError, ValueError, RuntimeError) as exc:
        raise AIProviderError(
            502,
            "AI pipeline candidate contract is invalid.",
        ) from exc


def _shade_enriched_features(
    route: RouteCandidate,
    options: ScoringOptions,
) -> dict[str, float | int | bool | None]:
    """AI 수집 피처에 백엔드에서 검증한 건물 그늘 사실을 결합한다."""
    if not route.model_features:
        raise AIProviderError(502, "AI candidate has no fixed model features.")
    features = dict(route.model_features)
    shade = route.shade
    shade_known = (
        shade is not None
        and shade.status in ("estimated_demo", "estimated_public")
        and shade.shade_ratio is not None
    )
    features["shade_ratio"] = shade.shade_ratio if shade_known else None
    features["shaded_walk_m"] = (
        shade.shaded_walk_m if shade_known else None
    )
    features["shade_building_height_coverage"] = (
        shade.building_height_coverage if shade_known else None
    )
    if not options.shade_priority:
        features["shade_priority_unshaded_walk_m"] = 0.0
    elif not shade_known:
        features["shade_priority_unshaded_walk_m"] = None
    elif shade.shaded_walk_m is not None:
        features["shade_priority_unshaded_walk_m"] = max(
            0.0,
            route.total_walk_m - shade.shaded_walk_m,
        )
    else:
        features["shade_priority_unshaded_walk_m"] = max(
            0.0,
            route.total_walk_m * (1.0 - shade.shade_ratio),
        )
    return features


def _canonical_snapshot_hash(snapshot: dict) -> str:
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


def _expected_enriched_snapshot_features(
    sent_features: dict[str, float | int | bool | None],
) -> dict[str, float | int | bool | None]:
    """AI 학습 스키마에 속하지 않는 표시용 지형 메타데이터만 제외한다."""
    return {
        key: value
        for key, value in sent_features.items()
        if key not in _DISPLAY_ONLY_TERRAIN_FEATURES
    }


async def enrich_ai_pipeline_candidates(
    candidates: list[RouteCandidate],
    options: ScoringOptions,
) -> EnrichedCandidateBundle:
    """같은 그늘 피처·시각·해시를 학습, 추천, 후기에 공통 적용한다."""
    if not candidates:
        raise AIProviderError(502, "No AI candidates to enrich.")
    route_ids = [route.id for route in candidates]
    if len(set(route_ids)) != len(route_ids):
        raise AIProviderError(502, "AI candidate route IDs are not unique.")
    base_group_ids = {route.model_group_id for route in candidates}
    if None in base_group_ids or len(base_group_ids) != 1:
        raise AIProviderError(502, "AI candidates do not share one source group.")
    if any(not route.model_snapshot_hash for route in candidates):
        raise AIProviderError(502, "AI candidate source snapshot provenance is incomplete.")
    holdout_group_ids = {route.model_holdout_group_id for route in candidates}
    if None in holdout_group_ids or len(holdout_group_ids) != 1:
        raise AIProviderError(502, "AI candidates do not share one holdout OD group.")

    evaluated_values = {
        route.shade.evaluated_at.astimezone(UTC).isoformat()
        for route in candidates
        if route.shade is not None
    }
    if len(evaluated_values) != 1 or any(route.shade is None for route in candidates):
        raise AIProviderError(502, "AI candidate shade evaluation time is inconsistent.")
    shade_evaluated_at = next(iter(evaluated_values))
    raw_captured_values = {
        str(route.model_snapshot.get("captured_at") or "")
        for route in candidates
        if route.model_snapshot
    }
    if (
        "" in raw_captured_values
        or len(raw_captured_values) != 1
        or any(not route.model_snapshot for route in candidates)
    ):
        raise AIProviderError(502, "AI candidate collection time is inconsistent.")
    try:
        captured_at = datetime.fromisoformat(
            next(iter(raw_captured_values)).replace("Z", "+00:00")
        ).astimezone(UTC).isoformat()
    except ValueError as exc:
        raise AIProviderError(
            502,
            "AI candidate collection time is invalid.",
        ) from exc
    features_by_id = {
        route.id: _shade_enriched_features(route, options)
        for route in candidates
    }
    data = await _post_pipeline(
        "/labeling/enriched-snapshots",
        {
            "base_group_id": next(iter(base_group_ids)),
            "holdout_group_id": next(iter(holdout_group_ids)),
            "captured_at": captured_at,
            "shade_evaluated_at": shade_evaluated_at,
            "candidates": [
                {
                    "route_id": route.id,
                    "base_snapshot_hash": route.model_snapshot_hash,
                    "sources": list(dict.fromkeys([
                        *route.sources,
                        str(route.shade.source),
                    ])),
                    "geometry_quality": route.geometry_quality,
                    "features": features_by_id[route.id],
                }
                for route in candidates
            ],
        },
    )
    group_id = str(data.get("group_id") or "")
    enriched_rows = data.get("candidates")
    if not group_id or not isinstance(enriched_rows, list):
        raise AIProviderError(502, "AI enriched snapshot response is invalid.")
    if (
        str(data.get("captured_at") or "") != captured_at
        or str(data.get("shade_evaluated_at") or "") != shade_evaluated_at
    ):
        raise AIProviderError(502, "AI enriched snapshot times do not match.")

    snapshots: dict[str, dict] = {}
    traits: dict[str, dict] = {}
    for item in enriched_rows:
        if not isinstance(item, dict):
            raise AIProviderError(502, "AI enriched snapshot row is invalid.")
        route_id = str(item.get("route_id") or "")
        snapshot = item.get("feature_snapshot")
        trait_wrapper = item.get("trait_labels")
        if (
            route_id not in features_by_id
            or route_id in snapshots
            or not isinstance(snapshot, dict)
            or not isinstance(trait_wrapper, dict)
        ):
            raise AIProviderError(502, "AI enriched snapshot identity is invalid.")
        snapshot_hash = str(snapshot.get("feature_snapshot_hash") or "")
        snapshot_features = snapshot.get("features")
        sent_features = features_by_id[route_id]
        expected_snapshot_features = _expected_enriched_snapshot_features(
            sent_features
        )
        if (
            str(snapshot.get("group_id") or "") != group_id
            or str(snapshot.get("holdout_group_id") or "")
            != next(iter(holdout_group_ids))
            or str(snapshot.get("route_id") or "") != route_id
            or not isinstance(snapshot_features, dict)
            # AI 서버는 표시용 지형 메타데이터만 제거할 수 있다.
            # 학습 피처의 누락·추가·변경은 허용하지 않는다.
            or snapshot_features != expected_snapshot_features
            or snapshot_hash != _canonical_snapshot_hash(snapshot)
        ):
            raise AIProviderError(502, "AI enriched feature snapshot is invalid.")
        if (
            str(trait_wrapper.get("group_id") or "") != group_id
            or str(trait_wrapper.get("route_id") or "") != route_id
            or str(trait_wrapper.get("feature_snapshot_hash") or "") != snapshot_hash
            or not isinstance(trait_wrapper.get("labels"), list)
        ):
            raise AIProviderError(502, "AI enriched trait provenance is invalid.")
        snapshots[route_id] = snapshot
        traits[route_id] = trait_wrapper

    if set(snapshots) != set(route_ids):
        raise AIProviderError(502, "AI enriched snapshots do not match candidate IDs.")
    route_by_id = {route.id: route for route in candidates}
    for route_id, snapshot in snapshots.items():
        route = route_by_id[route_id]
        route.model_group_id = group_id
        route.model_holdout_group_id = str(
            snapshot.get("holdout_group_id") or ""
        ) or None
        route.model_snapshot_hash = str(snapshot["feature_snapshot_hash"])
        route.model_features = dict(snapshot["features"])
        route.model_snapshot = dict(snapshot)
        route.trait_labels = [
            RouteTraitLabel.model_validate(label)
            for label in traits[route_id]["labels"]
        ]
    return EnrichedCandidateBundle(
        group_id=group_id,
        captured_at=captured_at,
        shade_evaluated_at=shade_evaluated_at,
        snapshots=snapshots,
        traits=traits,
    )


def _factual_route_reasons(route: RouteCandidate) -> list[str]:
    labels = [
        label.display_label
        for label in route.trait_labels
        if label.evidence_status in ("observed", "derived")
    ]
    return [f"{label} 특성이 확인되었습니다." for label in labels[:4]]


def _score_existing_ai_candidate(
    route: RouteCandidate,
    *,
    rank: int,
    displayed_score: float,
    profile: str,
    model_tier: str,
    model_version: str,
    features: dict[str, float | int | bool | None],
) -> ScoredRoute:
    bus_used = any(segment.mode == "bus" for segment in route.segments)
    bus_values = [
        segment.is_low_floor_bus
        for segment in route.segments
        if segment.mode == "bus"
    ]
    low_floor = (
        True
        if bus_values and all(value is True for value in bus_values)
        else False
        if bus_values and all(value is False for value in bus_values)
        else None
    )
    reasons = _factual_route_reasons(route)
    voice_summary = (
        f"{rank}번째 경로입니다. 총 {round(route.total_duration_min)}분, "
        f"도보 {round(route.total_walk_m)}미터, 환승 {route.transfer_count}회입니다."
        + (f" {reasons[0]}" if reasons else "")
    )
    score = RouteScore(
        route_id=route.id,
        components=ScoreComponents(),
        display=ScoreDisplay(),
        final_score=round1(clamp(displayed_score * 100)),
        low_floor_status=_derive_low_floor_status(bus_used, low_floor),
        reasons=reasons,
        cautions=[],
        voice_summary=voice_summary,
        score_kind=(
            "judge_baseline"
            if model_tier == "judge_baseline"
            else "human_model"
        ),
        feedback_token=create_feedback_token(
            route.id,
            model_version,
            {
                "group_id": route.model_group_id,
                "holdout_group_id": route.model_holdout_group_id,
                "snapshot_schema_version": route.model_snapshot.get(
                    "snapshot_schema_version"
                ),
                "snapshot_kind": route.model_snapshot.get("snapshot_kind"),
                "captured_at": route.model_snapshot.get("captured_at"),
                "shade_evaluated_at": route.model_snapshot.get(
                    "shade_evaluated_at"
                ),
                "sources": route.model_snapshot.get("sources"),
                "geometry_quality": route.model_snapshot.get("geometry_quality"),
                "feature_snapshot_hash": route.model_snapshot_hash,
                "training_eligible": True,
                "route_id": route.id,
                "profile": profile,
                **features,
            },
            displayed_rank=rank,
        ),
    )
    return ScoredRoute(route=route, score=score)


async def rank_ai_pipeline_candidates(
    candidates: list[RouteCandidate],
    profile: str,
    options: ScoringOptions,
    *,
    top_n: int = 3,
    personalization_state: str | None = None,
) -> list[ScoredRoute]:
    """건물 그늘까지 보강된 후보를 선택된 AI tier로 순위화한다."""
    if not candidates:
        raise AIProviderError(502, "No AI candidates to rank.")
    await enrich_ai_pipeline_candidates(candidates, options)
    features_by_id = {
        route.id: dict(route.model_features)
        for route in candidates
    }
    if len(features_by_id) != len(candidates):
        raise AIProviderError(502, "AI candidate route IDs are not unique.")
    data = await _post_pipeline(
        "/rank/candidates",
        {
            "profile": profile,
            "candidates": [
                {
                    "route_id": route.id,
                    "features": features_by_id[route.id],
                }
                for route in candidates
            ],
        },
    )
    ranked = data.get("ranked")
    if not isinstance(ranked, list) or not ranked:
        raise AIProviderError(502, "AI rank endpoint returned no rankings.")
    ranked_ids = [str(item.get("route_id") or "") for item in ranked]
    if (
        len(set(ranked_ids)) != len(ranked_ids)
        or set(ranked_ids) != set(features_by_id)
    ):
        raise AIProviderError(502, "AI rank endpoint returned mismatched route IDs.")

    metadata = data.get("metadata") or {}
    model_tier = str(metadata.get("model_tier") or "")
    if model_tier not in {"human_validated", "judge_baseline"}:
        raise AIProviderError(502, "AI rank endpoint returned an invalid model tier.")
    model_version = str(metadata.get("model_version") or "")
    if not model_version:
        raise AIProviderError(502, "AI rank endpoint returned no model version.")

    state = parse_state(personalization_state)
    personalization_active = int(state.get("updates", 0)) > 0
    if personalization_active and not settings.personalization_configured:
        raise AIProviderError(503, "Personalization policy is not configured.")
    route_by_id = {route.id: route for route in candidates}
    scored_rows: list[tuple[RouteCandidate, float]] = []
    for item in ranked:
        route_id = str(item["route_id"])
        try:
            global_fit_score = float(item["relative_fit_score"])
        except (KeyError, TypeError, ValueError) as exc:
            raise AIProviderError(
                502,
                "AI rank endpoint returned an invalid relative fit score.",
            ) from exc
        if not math.isfinite(global_fit_score) or not 0 <= global_fit_score <= 1:
            raise AIProviderError(
                502,
                "AI rank endpoint relative fit score is outside 0..1.",
            )
        displayed_score = global_fit_score
        if personalization_active:
            max_personal_share = settings.personalization_max_share
            prior_reviews = settings.personalization_prior_reviews
            if max_personal_share is None or prior_reviews is None:
                raise AIProviderError(
                    503,
                    "Personalization ranking policy is incomplete.",
                )
            displayed_score = blended_rank_score(
                global_fit_score,
                state,
                features_by_id[route_id],
                max_personal_share=max_personal_share,
                prior_reviews=prior_reviews,
            )
        scored_rows.append((route_by_id[route_id], displayed_score))
    # UI가 받는 점수는 0.1점 단위다. 그보다 작은 내부 점수 차이로
    # 순위를 먼저 고정하면 UI의 동점 소요시간 정렬과 서명 rank가
    # 달라질 수 있으므로 공개 점수 계약으로 최종 순위를 확정한다.
    scored_rows.sort(
        key=lambda row: (
            -round1(clamp(row[1] * 100)),
            row[0].total_duration_min,
        )
    )

    return [
        _score_existing_ai_candidate(
            route,
            rank=rank,
            displayed_score=displayed_score,
            profile=profile,
            model_tier=model_tier,
            model_version=model_version,
            features=features_by_id[route.id],
        )
        for rank, (route, displayed_score) in enumerate(
            scored_rows[:top_n],
            start=1,
        )
    ]


def _to_segment(item: dict, rank: int, index: int) -> RouteSegment:
    duration = float(item["duration_min"])
    stairs = item.get("stairs_count")
    return RouteSegment(
        id=str(item.get("id") or f"ai-{rank}-{index}"),
        mode=item.get("mode", "transfer"),
        description=str(item.get("description") or "이동 구간"),
        duration_min=duration,
        distance_m=item.get("distance_m"),
        outdoor=item.get("outdoor"),
        has_stairs=item.get("has_stairs"),
        stairs_count=int(stairs) if stairs is not None else None,
        has_slope=item.get("has_slope"),
        crosswalk_count=item.get("crosswalk_count"),
        bus_route_name=item.get("bus_route_name"),
        is_low_floor_bus=item.get("is_low_floor_bus"),
        wait_min=item.get("wait_min"),
        station_name=item.get("station_name"),
        has_elevator=item.get("has_elevator"),
        needs_vertical_move=item.get("needs_vertical_move"),
        path=item.get("path"),
        geometry_quality=item.get("geometry_quality"),
    )


def _to_route_candidate(
    r: dict,
    origin: Place,
    destination: Place,
    rank: int,
) -> RouteCandidate:
    route_id = str(r.get("route_id") or f"ai-{rank}")
    feature = r.get("features") or {}
    snapshot = r.get("feature_snapshot")
    snapshot_features = feature
    model_group_id = None
    model_holdout_group_id = None
    model_snapshot_hash = None
    if snapshot is not None:
        if not isinstance(snapshot, dict) or not isinstance(snapshot.get("features"), dict):
            raise RuntimeError("ai pipeline feature snapshot has an invalid shape")
        if str(snapshot.get("route_id")) != route_id:
            raise RuntimeError("ai pipeline feature snapshot route_id does not match")
        snapshot_features = snapshot["features"]
        if snapshot_features != feature:
            raise RuntimeError("ai pipeline feature snapshot differs from candidate features")
        model_group_id = str(snapshot.get("group_id") or "") or None
        model_holdout_group_id = str(
            snapshot.get("holdout_group_id") or model_group_id or ""
        ) or None
        model_snapshot_hash = str(snapshot.get("feature_snapshot_hash") or "") or None
        if model_group_id is None or model_snapshot_hash is None:
            raise RuntimeError("ai pipeline feature snapshot provenance is incomplete")
    model_features: dict[str, float | int | bool | None] = {}
    for name, value in snapshot_features.items():
        if value is None or isinstance(value, bool):
            model_features[str(name)] = value
        elif isinstance(value, (int, float)) and math.isfinite(float(value)):
            model_features[str(name)] = value
    segments = [
        _to_segment(item, rank, index)
        for index, item in enumerate(r.get("segments") or [])
    ]
    if not segments:
        raise RuntimeError("ai pipeline route has no truthful segments")

    transfer_count = feature.get("transfer_count")
    if transfer_count is None:
        transfer_count = sum(1 for segment in segments if segment.mode == "transfer")
    walk_distance = feature.get("walk_distance_m")
    if walk_distance is None:
        walking_segments = [segment for segment in segments if segment.mode == "walk"]
        if any(segment.distance_m is None for segment in walking_segments):
            raise RuntimeError("ai pipeline route has no truthful walking distance")
        walk_distance = sum(float(segment.distance_m) for segment in walking_segments)
    source_names = [str(source) for source in r.get("sources") or []]
    modes = [segment.bus_route_name or {"subway": "도시철도", "walk": "도보"}.get(segment.mode)
             for segment in segments]
    summary = str(r.get("summary") or "") or (
        " + ".join(dict.fromkeys(mode for mode in modes if mode))
        or f"{origin.name} → {destination.name}"
    )

    trait_payload = r.get("trait_labels")
    if trait_payload is None:
        trait_payload = r.get("traits")
    if trait_payload is None:
        trait_labels = []
    elif isinstance(trait_payload, dict):
        if str(trait_payload.get("route_id") or "") != route_id:
            raise RuntimeError("ai pipeline trait route_id does not match")
        if (
            model_group_id is None
            or str(trait_payload.get("group_id") or "") != model_group_id
        ):
            raise RuntimeError("ai pipeline trait group_id does not match")
        if (
            model_snapshot_hash is None
            or str(trait_payload.get("feature_snapshot_hash") or "")
            != model_snapshot_hash
        ):
            raise RuntimeError("ai pipeline trait snapshot hash does not match")
        trait_labels = trait_payload.get("labels")
        if not isinstance(trait_labels, list):
            raise RuntimeError("ai pipeline trait label wrapper has no labels list")
    else:
        raise RuntimeError("ai pipeline trait labels must use the provenance wrapper")
    path = [
        {"lat": point["lat"], "lng": point["lng"]}
        for point in r.get("path") or []
    ]
    if len(path) < 2:
        raise RuntimeError("ai pipeline route has no truthful geometry")
    return RouteCandidate(
        id=route_id,
        summary=summary,
        origin=origin.name,
        destination=destination.name,
        segments=segments,
        total_duration_min=float(r["duration_min"]),
        total_walk_m=float(walk_distance),
        transfer_count=int(transfer_count),
        path=path,
        sources=source_names,
        geometry_quality=r.get("geometry_quality"),
        terrain=TerrainSummary(
            avg_slope_percent=feature.get("avg_slope_percent"),
            max_slope_percent=feature.get("max_slope_percent"),
            min_slope_percent=feature.get("min_slope_percent"),
            uphill_distance_m=feature.get("uphill_distance_m"),
            downhill_distance_m=feature.get("downhill_distance_m"),
            elevation_gain_m=feature.get("elevation_gain_m"),
            elevation_loss_m=feature.get("elevation_loss_m"),
            source=feature.get("elevation_source"),
            resolution_m=feature.get("elevation_resolution_m"),
            status=feature.get("elevation_status", "unavailable"),
        ),
        trait_labels=trait_labels,
        model_features=model_features,
        model_group_id=model_group_id,
        model_holdout_group_id=model_holdout_group_id,
        model_snapshot_hash=model_snapshot_hash,
        model_snapshot=dict(snapshot) if isinstance(snapshot, dict) else {},
    )


def _derive_low_floor_status(bus_used: bool, is_low_floor) -> LowFloorStatus:
    if not bus_used:
        return "none"
    if is_low_floor is True:
        return "confirmed"
    if is_low_floor is False:
        return "regular"
    return "unknown"
