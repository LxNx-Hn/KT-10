from app.models import LatLng, Place, ScoringOptions
from app.feedback_tokens import verify_feedback_token
import json
import asyncio
from datetime import datetime
from zoneinfo import ZoneInfo

import httpx
import app.providers.ai_pipeline as ai_pipeline
from app.providers.ai_pipeline import (
    _pipeline_payload,
    _response_detail,
    _score_existing_ai_candidate,
    _to_route_candidate,
    _to_segment,
    rank_ai_pipeline_candidates,
)
from app.settings import settings
from app.shade import add_demo_shade
from app.correlation import correlation_id


ORIGIN = Place(id="origin", name="부산역", lat=35.1151, lng=129.0414)
DESTINATION = Place(id="destination", name="서면역", lat=35.1578, lng=129.0594)


def test_station_accessibility_inventory_survives_ai_adapter_without_route_claim():
    segment = _to_segment({
        "id": "subway-1",
        "mode": "subway",
        "description": "부산역 → 서면역",
        "duration_min": 10,
        "station_name": "부산역",
        "end_station_name": "서면역",
        "station_external_ramp_count": 2,
        "station_wheelchair_lift_count": 1,
        "station_accessibility_evidence_source": "부산교통공사 공식 원본",
        "station_ramp_route_match": None,
        "start_station_elevator_exit_match": True,
        "end_station_elevator_exit_match": True,
        "station_elevator_route_evidence_source": "부산교통공사 공식 이동경로",
    }, 1, 0)

    assert segment.station_external_ramp_count == 2
    assert segment.station_wheelchair_lift_count == 1
    assert segment.station_ramp_route_match is None
    assert segment.end_station_name == "서면역"
    assert segment.start_station_elevator_exit_match is True
    assert segment.end_station_elevator_exit_match is True


def test_subway_adapter_replaces_intermediate_stop_with_terminal_direction():
    segment = _to_segment({
        "id": "subway-direction",
        "mode": "subway",
        "description": "시청 → 교대",
        "duration_min": 4,
        "station_name": "시청",
        "end_station_name": "교대",
        "transit_route_id": "71",
        "transit_direction": "교대",
    }, 1, 0)

    assert segment.transit_direction == "노포"


def test_internal_ai_headers_preserve_request_correlation_id(monkeypatch):
    """Backend→AI 호출은 내부 토큰과 동일한 요청 correlation ID를 보낸다."""
    internal_token = "internal-service-token-for-tests-0123456789"
    monkeypatch.setattr(
        settings,
        "ai_internal_service_token",
        internal_token,
    )
    context_token = correlation_id.set("backend-trace-0003")
    try:
        headers = ai_pipeline._internal_headers()
    finally:
        correlation_id.reset(context_token)

    assert headers["X-Correlation-ID"] == "backend-trace-0003"
    assert headers["X-KT10-Internal-Token"] == internal_token


def _candidate_payload() -> dict:
    return {
        "route_id": "route-live-1",
        "summary": "도보 + 도시철도",
        "duration_min": 24,
        "distance_m": 4100,
        "sources": ["odsay", "osmnx"],
        "geometry_quality": "mixed",
        "path": [
            {"lat": 35.1151, "lng": 129.0414},
            {"lat": 35.1300, "lng": 129.0500},
            {"lat": 35.1578, "lng": 129.0594},
        ],
        "segments": [
            {
                "id": "walk-1",
                "mode": "walk",
                "description": "부산역 출구까지 이동",
                "duration_min": 5,
                "distance_m": 320,
                "outdoor": True,
                "path": [
                    {"lat": 35.1151, "lng": 129.0414},
                    {"lat": 35.1160, "lng": 129.0420},
                ],
                "geometry_quality": "exact",
            },
            {
                "id": "subway-1",
                "mode": "subway",
                "description": "도시철도 1호선",
                "duration_min": 19,
                "distance_m": 3780,
                "station_name": "부산역",
                "path": [
                    {"lat": 35.1160, "lng": 129.0420},
                    {"lat": 35.1578, "lng": 129.0594},
                ],
                "geometry_quality": "exact",
            },
        ],
        "slope_segments": [
            {
                "start": {"lat": 35.1151, "lng": 129.0414},
                "end": {"lat": 35.1160, "lng": 129.0420},
                "slope_percent": 4.2,
                "distance_m": 112.8,
            }
        ],
        "features": {
            "transfer_count": 0,
            "walk_distance_m": 320,
            "avg_slope_percent": 1.4,
            "max_slope_percent": 4.2,
            "min_slope_percent": -2.1,
            "elevation_gain_m": 7.5,
            "elevation_status": "estimated_90m",
            "elevation_source": "Open-Meteo Copernicus DEM GLO-90",
            "elevation_resolution_m": 90,
        },
        "feature_snapshot": {
            "snapshot_schema_version": "route-feature-snapshot-v2",
            "snapshot_kind": "live_route_candidate",
            "captured_at": "2026-07-24T12:00:00+09:00",
            "group_id": "group-live-1",
            "route_id": "route-live-1",
            "sources": ["odsay", "osmnx"],
            "geometry_quality": "mixed",
            "features": {
                "transfer_count": 0,
                "walk_distance_m": 320,
                "avg_slope_percent": 1.4,
                "max_slope_percent": 4.2,
                "min_slope_percent": -2.1,
                "elevation_gain_m": 7.5,
                "elevation_status": "estimated_90m",
                "elevation_source": "Open-Meteo Copernicus DEM GLO-90",
                "elevation_resolution_m": 90,
            },
            "feature_snapshot_hash": "a" * 64,
        },
        "trait_labels": {
            "schema_version": "route-traits-v1",
            "group_id": "group-live-1",
            "route_id": "route-live-1",
            "feature_snapshot_hash": "a" * 64,
            "labels": [
                {
                    "label_id": "gentle_slope",
                    "display_label": "경사가 완만한 길",
                    "evidence_status": "derived",
                    "evidence": [
                        {
                            "feature": "max_slope_percent",
                            "value": 4.2,
                            "unit": "percent",
                            "source": "copernicus_glo90",
                        }
                    ],
                }
            ],
        },
    }


def test_labeling_candidate_maps_geometry_and_terrain_without_invention():
    route = _to_route_candidate(_candidate_payload(), ORIGIN, DESTINATION, 1)

    assert route.id == "route-live-1"
    assert route.path is not None and len(route.path) == 3
    assert route.geometry_quality == "mixed"
    assert route.total_walk_m == 320
    assert route.transfer_count == 0
    assert route.terrain is not None
    assert route.terrain.status == "estimated_90m"
    assert route.terrain.avg_slope_percent == 1.4
    assert len(route.terrain.slope_segments) == 1
    assert route.terrain.slope_segments[0].slope_percent == 4.2
    assert route.segments[0].path is not None
    assert route.trait_labels[0].label_id == "gentle_slope"
    assert route.trait_labels[0].evidence[0].value == 4.2


def test_ai_ranked_wheelchair_route_keeps_constraint_caution_in_voice():
    payload = _candidate_payload()
    payload["segments"][0].update({
        "stairs_excluded_by_provider": True,
        "wheelchair_constraints_applied": True,
        "wheelchair_constraint_source": (
            "openrouteservice wheelchair profile"
        ),
        "wheelchair_restrictions": {
            "surface_type": "cobblestone:flattened",
            "track_type": "grade1",
            "smoothness_type": "good",
            "maximum_sloped_kerb": 0.06,
            "maximum_incline": 6,
            "minimum_width": 0.9,
        },
        "wheelchair_data_limitations": ["OSM 태그 누락 가능"],
        "wheelchair_constraint_categories": [
            "steps",
            "surface",
            "width",
            "wheelchair_access",
        ],
        "wheelchair_extra_info_full_route_coverage": True,
        "wheelchair_extra_response_keys": {
            "steepness": "steepness",
            "suitability": "suitability",
            "surface": "surface",
            "waytype": "waytypes",
            "osmid": "osmId",
        },
    })
    route = _to_route_candidate(payload, ORIGIN, DESTINATION, 1)

    scored = _score_existing_ai_candidate(
        route,
        rank=1,
        displayed_score=0.9,
        profile="disabled",
        model_tier="bootstrap_baseline",
        model_version="test-model",
        features={},
    )

    assert "지도에 기록된 계단·노면·폭·턱·경사 제한" in scored.score.reasons[0]
    assert "임시 장애물" in scored.score.cautions[0]
    assert "주의:" in scored.score.voice_summary


def test_labeling_candidate_rejects_missing_geometry():
    payload = _candidate_payload()
    payload["path"] = []

    try:
        _to_route_candidate(payload, ORIGIN, DESTINATION, 1)
    except RuntimeError as exc:
        assert "geometry" in str(exc)
    else:
        raise AssertionError("geometry 없는 live 경로를 허용하면 안 됩니다.")


def test_labeling_candidate_rejects_invalid_trait_wrapper():
    payload = _candidate_payload()
    payload["trait_labels"].pop("labels")

    try:
        _to_route_candidate(payload, ORIGIN, DESTINATION, 1)
    except RuntimeError as exc:
        assert "labels list" in str(exc)
    else:
        raise AssertionError("labels 배열이 없는 특성 wrapper를 허용하면 안 됩니다.")


def test_labeling_candidate_rejects_trait_from_different_snapshot():
    payload = _candidate_payload()
    payload["trait_labels"]["feature_snapshot_hash"] = "b" * 64

    try:
        _to_route_candidate(payload, ORIGIN, DESTINATION, 1)
    except RuntimeError as exc:
        assert "snapshot hash" in str(exc)
    else:
        raise AssertionError("다른 스냅샷의 특성 라벨을 허용하면 안 됩니다.")


def test_pipeline_payload_keeps_profile_and_trip_conditions_separate():
    payload = _pipeline_payload(
        ORIGIN,
        DESTINATION,
        "pregnant",
        "normal",
        ScoringOptions(
            carry_luggage=True,
            stroller=True,
            avoid_stairs=True,
            shade_priority=True,
            low_floor_priority=True,
            minimize_transfers=True,
        ),
    )
    assert payload["profile"] == "pregnant"
    assert payload["carry_luggage"] is True
    assert payload["stroller"] is True
    assert payload["avoid_stairs"] is True
    assert payload["shade_priority"] is True
    assert payload["low_floor_priority"] is True
    assert payload["minimize_transfers"] is True
    assert payload["candidate_limit"] == 5
    assert payload["max_walk_distance_m"] == settings.max_supported_total_walk_m


def test_response_detail_includes_source_failures():
    response = httpx.Response(
        503,
        json={
            "detail": {
                "message": "유효한 실제 경로 후보를 수집하지 못했습니다.",
                "sources": {
                    "odsay": "CollectorError: ApiKey authentication failed.",
                    "tmap": "CollectorNotConfigured: TMAP_API_KEY가 설정되지 않았습니다.",
                },
            }
        },
    )

    detail = _response_detail(response)

    assert "유효한 실제 경로 후보를 수집하지 못했습니다." in detail
    assert "odsay: CollectorError: ApiKey authentication failed." in detail
    assert "tmap: CollectorNotConfigured: TMAP_API_KEY가 설정되지 않았습니다." in detail


def test_ai_personalization_score_preserves_personalized_order_for_frontend(
    monkeypatch,
):
    first_payload = _candidate_payload()
    first_payload["route_id"] = "global-first"
    first_payload["feature_snapshot"]["route_id"] = "global-first"
    first_payload["trait_labels"]["route_id"] = "global-first"
    second_payload = _candidate_payload()
    second_payload["route_id"] = "personal-first"
    second_payload["feature_snapshot"]["route_id"] = "personal-first"
    second_payload["trait_labels"]["route_id"] = "personal-first"
    candidates = [
        _to_route_candidate(first_payload, ORIGIN, DESTINATION, 1),
        _to_route_candidate(second_payload, ORIGIN, DESTINATION, 2),
    ]

    async def fake_enrich(routes, _options):
        for route, shade_ratio in zip(routes, (0.0, 1.0), strict=True):
            route.model_features = {
                "shade_ratio": shade_ratio,
                "walk_distance_m": route.total_walk_m,
            }
            route.model_group_id = "enriched-group-1"
            route.model_holdout_group_id = "od-group-1"
            route.model_snapshot_hash = f"{route.id}-hash"
            route.model_snapshot = {
                "snapshot_schema_version": "route-feature-snapshot-v2",
                "snapshot_kind": "live_route_candidate",
                "captured_at": "2026-07-24T03:00:00+00:00",
                "shade_evaluated_at": "2026-07-24T05:00:00+00:00",
                "sources": ["odsay"],
            }

    async def fake_post(path, _payload):
        assert path == "/rank/candidates"
        return {
            "ranked": [
                {
                    "route_id": "global-first",
                    "relative_fit_score": 0.65,
                },
                {
                    "route_id": "personal-first",
                    "relative_fit_score": 0.35,
                },
            ],
            "metadata": {
                "model_tier": "human_validated",
                "model_version": "human-test",
            },
        }

    monkeypatch.setattr(
        ai_pipeline,
        "enrich_ai_pipeline_candidates",
        fake_enrich,
    )
    monkeypatch.setattr(ai_pipeline, "_post_pipeline", fake_post)
    monkeypatch.setattr(settings, "personalization_max_share", 0.35)
    monkeypatch.setattr(settings, "personalization_prior_reviews", 5.0)
    monkeypatch.setattr(settings, "personalization_learning_rate", 0.25)
    monkeypatch.setattr(settings, "personalization_regularization", 0.02)
    monkeypatch.setattr(settings, "personalization_usable_weight", 0.45)
    monkeypatch.setattr(settings, "personalization_rating_weight", 0.35)
    monkeypatch.setattr(settings, "personalization_reuse_weight", 0.20)
    state = json.dumps({
        "version": 1,
        "bias": -10.0,
        "weights": {"shade_ratio": 20.0},
        "updates": 1000,
    })

    results = asyncio.run(
        rank_ai_pipeline_candidates(
            candidates,
            "general",
            ScoringOptions(),
            top_n=2,
            personalization_state=state,
        )
    )

    assert [item.route.id for item in results] == [
        "personal-first",
        "global-first",
    ]
    assert results[0].score.final_score > results[1].score.final_score


def test_ai_signed_rank_uses_display_score_and_duration_tie_break(
    monkeypatch,
):
    slower_payload = _candidate_payload()
    slower_payload["route_id"] = "slower"
    slower_payload["duration_min"] = 30
    slower_payload["feature_snapshot"]["route_id"] = "slower"
    slower_payload["trait_labels"]["route_id"] = "slower"
    faster_payload = _candidate_payload()
    faster_payload["route_id"] = "faster"
    faster_payload["duration_min"] = 20
    faster_payload["feature_snapshot"]["route_id"] = "faster"
    faster_payload["trait_labels"]["route_id"] = "faster"
    candidates = [
        _to_route_candidate(slower_payload, ORIGIN, DESTINATION, 1),
        _to_route_candidate(faster_payload, ORIGIN, DESTINATION, 2),
    ]

    async def fake_enrich(routes, _options):
        for route in routes:
            route.model_features = {
                "walk_distance_m": route.total_walk_m,
            }
            route.model_group_id = "enriched-group-1"
            route.model_holdout_group_id = "od-group-1"
            route.model_snapshot_hash = f"{route.id}-hash"
            route.model_snapshot = {
                "snapshot_schema_version": "route-feature-snapshot-v2",
                "snapshot_kind": "live_route_candidate",
                "captured_at": "2026-07-24T03:00:00+00:00",
                "shade_evaluated_at": "2026-07-24T05:00:00+00:00",
                "sources": ["odsay"],
            }

    async def fake_post(path, _payload):
        assert path == "/rank/candidates"
        return {
            "ranked": [
                {
                    "route_id": "slower",
                    "relative_fit_score": 0.80049,
                },
                {
                    "route_id": "faster",
                    "relative_fit_score": 0.8004,
                },
            ],
            "metadata": {
                "model_tier": "human_validated",
                "model_version": "human-test",
            },
        }

    monkeypatch.setattr(
        ai_pipeline,
        "enrich_ai_pipeline_candidates",
        fake_enrich,
    )
    monkeypatch.setattr(ai_pipeline, "_post_pipeline", fake_post)
    monkeypatch.setattr(
        settings,
        "session_secret",
        "test-session-secret-with-at-least-32-chars",
    )

    results = asyncio.run(
        rank_ai_pipeline_candidates(
            candidates,
            "general",
            ScoringOptions(),
            top_n=2,
        )
    )

    assert [item.route.id for item in results] == ["faster", "slower"]
    assert [item.score.final_score for item in results] == [80.0, 80.0]
    assert [
        verify_feedback_token(item.score.feedback_token)["displayed_rank"]
        for item in results
    ] == [1, 2]


def test_ai_minimize_transfers_is_lexicographic_before_model_score(monkeypatch):
    fewer_payload = _candidate_payload()
    fewer_payload["route_id"] = "fewer"
    fewer_payload["feature_snapshot"]["route_id"] = "fewer"
    fewer_payload["trait_labels"]["route_id"] = "fewer"
    more_payload = _candidate_payload()
    more_payload["route_id"] = "more"
    more_payload["feature_snapshot"]["route_id"] = "more"
    more_payload["trait_labels"]["route_id"] = "more"
    candidates = [
        _to_route_candidate(more_payload, ORIGIN, DESTINATION, 1),
        _to_route_candidate(fewer_payload, ORIGIN, DESTINATION, 2),
    ]
    candidates[0].transfer_count = 3
    candidates[1].transfer_count = 0

    async def fake_enrich(routes, _options):
        for route in routes:
            route.model_features = {"walk_distance_m": route.total_walk_m}
            route.model_group_id = "enriched-group-1"
            route.model_holdout_group_id = "od-group-1"
            route.model_snapshot_hash = f"{route.id}-hash"
            route.model_snapshot = {
                "snapshot_schema_version": "route-feature-snapshot-v2",
                "snapshot_kind": "live_route_candidate",
                "captured_at": "2026-07-24T03:00:00+00:00",
                "shade_evaluated_at": "2026-07-24T05:00:00+00:00",
                "sources": ["tmap_transit"],
            }

    async def fake_post(path, _payload):
        assert path == "/rank/candidates"
        return {
            "ranked": [
                {"route_id": "more", "relative_fit_score": 1.0},
                {"route_id": "fewer", "relative_fit_score": 0.1},
            ],
            "metadata": {
                "model_tier": "human_validated",
                "model_version": "human-test",
            },
        }

    monkeypatch.setattr(ai_pipeline, "enrich_ai_pipeline_candidates", fake_enrich)
    monkeypatch.setattr(ai_pipeline, "_post_pipeline", fake_post)
    monkeypatch.setattr(
        settings,
        "session_secret",
        "test-session-secret-with-at-least-32-chars",
    )

    results = asyncio.run(
        rank_ai_pipeline_candidates(
            candidates,
            "general",
            ScoringOptions(minimize_transfers=True),
            top_n=2,
        )
    )

    assert [item.route.id for item in results] == ["fewer", "more"]


def test_backend_shade_is_enriched_before_ai_ranking(monkeypatch):
    route = _to_route_candidate(_candidate_payload(), ORIGIN, DESTINATION, 1)
    route.path = [
        LatLng(lat=35.1626, lng=129.0530),
        LatLng(lat=35.1600, lng=129.0560),
        LatLng(lat=35.1578, lng=129.0594),
    ]
    add_demo_shade(
        [route],
        datetime(2026, 7, 24, 14, 0, tzinfo=ZoneInfo("Asia/Seoul")),
    )
    captured = {}

    async def fake_post(path, payload):
        if path == "/labeling/enriched-snapshots":
            row = payload["candidates"][0]
            # AI의 학습 스키마는 경로 표시용 지형 메타데이터를 스냅샷에서
            # 제외할 수 있다. 남은 값은 백엔드가 보낸 값과 같아야 한다.
            snapshot_features = ai_pipeline._expected_enriched_snapshot_features(
                row["features"]
            )
            snapshot = {
                "snapshot_schema_version": "route-feature-snapshot-v2",
                "snapshot_kind": "live_route_candidate",
                "captured_at": payload["captured_at"],
                "shade_evaluated_at": payload["shade_evaluated_at"],
                "group_id": "enriched-group-1",
                "holdout_group_id": payload["holdout_group_id"],
                "route_id": row["route_id"],
                "sources": row["sources"],
                "geometry_quality": row["geometry_quality"],
                "features": snapshot_features,
            }
            snapshot["feature_snapshot_hash"] = (
                ai_pipeline._canonical_snapshot_hash(snapshot)
            )
            return {
                "group_id": "enriched-group-1",
                "captured_at": payload["captured_at"],
                "shade_evaluated_at": payload["shade_evaluated_at"],
                "candidates": [{
                    "route_id": row["route_id"],
                    "feature_snapshot": snapshot,
                    "trait_labels": {
                        "schema_version": "route-traits-v1",
                        "group_id": "enriched-group-1",
                        "route_id": row["route_id"],
                        "feature_snapshot_hash": snapshot["feature_snapshot_hash"],
                        "labels": [],
                    },
                }],
            }
        captured["path"] = path
        captured["payload"] = payload
        return {
            "ranked": [{
                "route_id": route.id,
                "rank": 1,
                "model_score": 0.8,
                "relative_fit_score": 1.0,
                "selection_probability": 1.0,
            }],
            "metadata": {
                "model_tier": "bootstrap_baseline",
                "model_version": "bootstrap-test",
            },
        }

    monkeypatch.setattr(ai_pipeline, "_post_pipeline", fake_post)
    monkeypatch.setattr(
        settings,
        "session_secret",
        "test-session-secret-with-at-least-32-chars",
    )

    results = asyncio.run(
        rank_ai_pipeline_candidates(
            [route],
            "general",
            ScoringOptions(shade_priority=True),
            top_n=1,
        )
    )

    sent = captured["payload"]["candidates"][0]["features"]
    assert captured["path"] == "/rank/candidates"
    assert sent["shade_ratio"] == route.shade.shade_ratio
    assert sent["shaded_walk_m"] == route.shade.shaded_walk_m
    assert sent["shade_building_height_coverage"] == (
        route.shade.building_height_coverage
    )
    assert sent["shade_priority_unshaded_walk_m"] is not None
    assert "elevation_source" not in sent
    assert results[0].route.shade.status == "estimated_demo"
    assert results[0].score.score_kind == "bootstrap_baseline"
