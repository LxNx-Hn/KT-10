from __future__ import annotations

import pandas as pd

from labeling.generate_od_catalog import (
    DistanceBand,
    Situation,
    _allocate_counts,
    generate_catalog_rows,
)


def _poi_grid() -> pd.DataFrame:
    rows = []
    for district_index, district in enumerate(("A구", "B구", "C구")):
        for point_index in range(40):
            rows.append({
                "name": f"{district}-{point_index}",
                "lat": 35.05 + district_index * 0.08 + point_index * 0.001,
                "lng": 129.00 + point_index * 0.001,
                "district": district,
            })
    return pd.DataFrame(rows)


def test_allocate_counts_is_exact_and_stable():
    assert _allocate_counts(10, [0.35, 0.45, 0.20]) == [4, 4, 2]
    assert _allocate_counts(800, [1.0] * 8) == [100] * 8


def test_catalog_is_deterministic_balanced_and_unique():
    bands = (
        DistanceBand("near", 0.1, 8.0, 0.5),
        DistanceBand("far", 8.0, 20.0, 0.5, True),
    )
    situations = (
        Situation("normal", "normal", "2026-08-03T09:00:00+09:00"),
        Situation(
            "luggage",
            "normal",
            "2026-08-03T12:00:00+09:00",
            carry_luggage=True,
        ),
    )
    first = generate_catalog_rows(
        _poi_grid(),
        count=60,
        seed=42,
        distance_bands=bands,
        situations=situations,
    )
    second = generate_catalog_rows(
        _poi_grid(),
        count=60,
        seed=42,
        distance_bands=bands,
        situations=situations,
    )

    assert first == second
    assert len(first) == 60
    assert len({row["od_id"] for row in first}) == 60
    assert len({
        (
            row["origin_lat"],
            row["origin_lng"],
            row["dest_lat"],
            row["dest_lng"],
        )
        for row in first
    }) == 60
    assert {row["distance_band"] for row in first} == {"near", "far"}
    assert {row["situation_id"] for row in first} == {"normal", "luggage"}
    assert max(
        sum(row["origin_district"] == district for row in first)
        for district in ("A구", "B구", "C구")
    ) == 20
    assert all(
        row["origin_district"] != row["dest_district"]
        for row in first
        if row["distance_band"] == "far"
    )
