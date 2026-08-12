import asyncio

from config import settings
from features.route_feature_cache import (
    cache_identity,
    read,
    request_lock,
    write,
)


def test_route_feature_cache_reuses_larger_precomputed_candidate_set(
    monkeypatch,
    tmp_path,
):
    monkeypatch.setattr(settings, "ROUTE_FEATURE_CACHE_DIR", str(tmp_path))
    monkeypatch.setattr(settings, "ROUTE_FEATURE_CACHE_TTL_SECONDS", 3600)
    identity = cache_identity(35.1, 129.0, 35.2, 129.1)
    features = [
        {"_sources": ["odsay"], "_path": [{"lat": 35.1, "lng": 129.0}]}
        for _ in range(10)
    ]
    metadata = {"captured_at": "2026-07-26T00:00:00+00:00"}

    write(
        identity,
        candidate_limit=10,
        route_features=features,
        metadata=metadata,
    )

    assert read(identity, minimum_candidate_limit=5) == (features, metadata)
    assert read(identity, minimum_candidate_limit=10) == (features, metadata)
    assert read(identity, minimum_candidate_limit=11) is None
    rendered = next(tmp_path.glob("route-features-*.json")).read_text(
        encoding="utf-8"
    )
    assert "apiKey" not in rendered
    assert "YOUR_" not in rendered


def test_route_feature_cache_singleflights_same_od():
    identity = cache_identity(35.1, 129.0, 35.2, 129.1)

    async def run():
        first = request_lock(identity)
        second = request_lock(identity)
        return first is second

    assert asyncio.run(run()) is True


def test_wheelchair_cache_identity_is_separate_from_general_route():
    general = cache_identity(35.1, 129.0, 35.2, 129.1)
    wheelchair = cache_identity(
        35.1,
        129.0,
        35.2,
        129.1,
        avoid_stairs=True,
    )

    assert general != wheelchair
    assert general["geometryProfile"]["stairsExcluded"] is False
    assert wheelchair["geometryProfile"]["stairsExcluded"] is True
