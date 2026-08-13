import json

import pytest

from collectors.base import Coordinate
from features.wheelchair_blockers import (
    CATALOG_SCHEMA_VERSION,
    DEFAULT_CATALOG,
    _load_catalog,
    explicit_unramped_step_ids,
)
from merger.route_merger import MergedRoute


def _write_catalog(path, *, ramp="no"):
    path.write_text(json.dumps({
        "type": "FeatureCollection",
        "schemaVersion": CATALOG_SCHEMA_VERSION,
        "features": [{
            "type": "Feature",
            "properties": {
                "osmWayId": 123,
                "highway": "steps",
                "ramp": ramp,
            },
            "geometry": {
                "type": "LineString",
                "coordinates": [
                    [129.0000, 35.1000],
                    [129.0010, 35.1010],
                ],
            },
        }],
    }), encoding="utf-8")


def test_committed_busan_unramped_step_catalog_is_valid():
    _load_catalog.cache_clear()

    blockers = _load_catalog(str(DEFAULT_CATALOG.resolve()))

    assert len(blockers) == 41
    assert len({osm_way_id for osm_way_id, _ in blockers}) == 41


def test_explicit_unramped_step_catalog_matches_only_crossing_route(tmp_path):
    catalog = tmp_path / "blockers.geojson"
    _write_catalog(catalog)
    _load_catalog.cache_clear()

    assert explicit_unramped_step_ids(
        [[(35.1000, 129.0000), (35.1010, 129.0010)]],
        catalog_path=catalog,
    ) == [123]
    assert explicit_unramped_step_ids(
        [[(35.2000, 129.2000), (35.2010, 129.2010)]],
        catalog_path=catalog,
    ) == []


def test_catalog_rejects_non_blocking_ramp_tag(tmp_path):
    catalog = tmp_path / "invalid.geojson"
    _write_catalog(catalog, ramp="yes")
    _load_catalog.cache_clear()

    with pytest.raises(ValueError, match=r"steps\+ramp=no"):
        explicit_unramped_step_ids(
            [[(35.1000, 129.0000), (35.1010, 129.0010)]],
            catalog_path=catalog,
        )


def test_router_excludes_candidate_crossing_explicit_unramped_steps(
    monkeypatch,
):
    from api import router as module

    safe = MergedRoute(
        sources=["ors"],
        source="ors",
        path=[Coordinate(35.1, 129.0), Coordinate(35.2, 129.1)],
        duration_min=10,
        distance_m=1000,
    )
    blocked = MergedRoute(
        sources=["ors"],
        source="ors",
        path=[Coordinate(35.2, 129.0), Coordinate(35.3, 129.1)],
        duration_min=10,
        distance_m=1000,
    )
    monkeypatch.setattr(
        module,
        "explicit_unramped_step_ids",
        lambda parts: [999] if parts[0][0][0] == 35.2 else [],
    )

    assert module._exclude_explicit_unramped_steps([safe, blocked]) == [safe]
