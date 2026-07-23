"""후보군 내 확인된 사실만으로 설명용 경로 특성 라벨을 만든다."""
from __future__ import annotations

from typing import Any, Callable

TRAIT_SCHEMA_VERSION = "route-traits-v1"
TRAIT_RUBRIC_VERSION = "route-traits-v1"


def _evidence(
    feature: str,
    value: int | float | bool | None,
    unit: str | None,
    source: str,
) -> dict[str, Any]:
    return {
        "feature": feature,
        "value": value,
        "unit": unit,
        "source": source,
    }


def _label(
    label_id: str,
    display_label: str,
    evidence_status: str,
    evidence: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "label_id": label_id,
        "display_label": display_label,
        "evidence_status": evidence_status,
        "evidence": evidence,
    }


def _minimum_route_ids(
    snapshots: list[dict[str, Any]],
    value_getter: Callable[[dict[str, Any]], int | float | None],
) -> set[str]:
    observed = []
    for snapshot in snapshots:
        value = value_getter(snapshot["features"])
        if value is None:
            return set()
        observed.append((str(snapshot["route_id"]), float(value)))
    if not observed:
        return set()
    minimum = min(value for _, value in observed)
    return {
        route_id
        for route_id, value in observed
        if abs(value - minimum) <= 1e-9
    }


def _maximum_route_ids(
    snapshots: list[dict[str, Any]],
    value_getter: Callable[[dict[str, Any]], int | float | None],
) -> set[str]:
    observed = []
    for snapshot in snapshots:
        value = value_getter(snapshot["features"])
        if value is None:
            return set()
        observed.append((str(snapshot["route_id"]), float(value)))
    if not observed:
        return set()
    maximum = max(value for _, value in observed)
    return {
        route_id
        for route_id, value in observed
        if abs(value - maximum) <= 1e-9
    }


def generate_route_traits(
    snapshots: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    """같은 OD 후보군에서 관측 가능한 사실의 상대·절대 특성을 반환한다."""
    if not snapshots:
        return {}
    fastest = _minimum_route_ids(
        snapshots, lambda features: features.get("total_duration_min")
    )
    shortest = _minimum_route_ids(
        snapshots, lambda features: features.get("walk_distance_m")
    )
    fewest_transfers = _minimum_route_ids(
        snapshots, lambda features: features.get("transfer_count")
    )
    lowest_slope = _minimum_route_ids(
        snapshots,
        lambda features: (
            max(
                abs(float(features["max_slope_percent"])),
                abs(float(features["min_slope_percent"])),
            )
            if (
                features.get("max_slope_percent") is not None
                and features.get("min_slope_percent") is not None
            )
            else None
        ),
    )
    shade_values = [
        snapshot["features"].get("shade_ratio")
        for snapshot in snapshots
    ]
    most_shade = (
        _maximum_route_ids(
            snapshots, lambda features: features.get("shade_ratio")
        )
        if (
            shade_values
            and all(value is not None for value in shade_values)
            and max(float(value) for value in shade_values) > 0
        )
        else set()
    )

    result: dict[str, dict[str, Any]] = {}
    for snapshot in snapshots:
        route_id = str(snapshot["route_id"])
        features = snapshot["features"]
        labels: list[dict[str, Any]] = []
        if route_id in fastest:
            labels.append(_label(
                "fastest",
                "제일 빠른 길",
                "derived",
                [_evidence(
                    "total_duration_min",
                    features.get("total_duration_min"),
                    "min",
                    "route_provider",
                )],
            ))
        if route_id in shortest:
            labels.append(_label(
                "shortest",
                "도보가 짧은 길",
                "derived",
                [_evidence(
                    "walk_distance_m",
                    features.get("walk_distance_m"),
                    "m",
                    "route_provider",
                )],
            ))
        if route_id in fewest_transfers:
            labels.append(_label(
                "fewest_transfers",
                "환승이 적은 길",
                "derived",
                [_evidence(
                    "transfer_count",
                    features.get("transfer_count"),
                    "count",
                    "route_provider",
                )],
            ))
        if route_id in lowest_slope:
            labels.append(_label(
                "lowest_slope",
                "경사가 완만한 길",
                "derived",
                [
                    _evidence(
                        "max_slope_percent",
                        features.get("max_slope_percent"),
                        "percent",
                        str(features.get("elevation_source") or "elevation"),
                    ),
                    _evidence(
                        "min_slope_percent",
                        features.get("min_slope_percent"),
                        "percent",
                        str(features.get("elevation_source") or "elevation"),
                    ),
                ],
            ))
        if route_id in most_shade:
            labels.append(_label(
                "most_shade",
                "그늘 많은 길",
                "derived",
                [_evidence(
                    "shade_ratio",
                    features.get("shade_ratio"),
                    "ratio",
                    "building_shade",
                )],
            ))
        if features.get("stair_count") == 0:
            labels.append(_label(
                "stair_free_confirmed",
                "계단 없는 길",
                "observed",
                [_evidence(
                    "stair_count",
                    0,
                    "count",
                    "route_facility_data",
                )],
            ))
        if features.get("is_low_floor_bus") is True:
            labels.append(_label(
                "low_floor_confirmed",
                "저상버스 확인 경로",
                "observed",
                [_evidence(
                    "is_low_floor_bus",
                    True,
                    None,
                    "route_provider",
                )],
            ))

        result[route_id] = {
            "schema_version": TRAIT_SCHEMA_VERSION,
            "group_id": str(snapshot["group_id"]),
            "route_id": route_id,
            "feature_snapshot_hash": str(snapshot["feature_snapshot_hash"]),
            "labels": labels,
            "provenance": {
                "labeler_kind": "deterministic_factual",
                "rubric_version": TRAIT_RUBRIC_VERSION,
                "generated_at": str(snapshot["captured_at"]),
            },
        }
    return result
