import pytest

from scripts import prewarm_route_cache


def _routes(quality: str, *, terrain: str = "unavailable", shade: str = "unavailable"):
    return [
        {
            "route": {
                "geometryQuality": quality,
                "terrain": {"status": terrain},
                "shade": {"status": shade},
            }
        }
        for _ in range(3)
    ]


def test_quality_keeps_unavailable_metrics_distinct_from_zero():
    quality = prewarm_route_cache._quality(_routes("mixed"))

    assert quality == {
        "routeCount": 3,
        "exactGeometryCount": 0,
        "terrainReadyCount": 0,
        "shadeReadyCount": 0,
    }


def test_prewarm_polls_until_exact_then_verifies_cached_latency(monkeypatch):
    monkeypatch.setattr(
        prewarm_route_cache,
        "_place",
        lambda _base, query: {"id": query, "name": query, "lat": 35.1, "lng": 129.0},
    )
    responses = iter((
        (_routes("mixed"), 1.0),
        (_routes("exact", terrain="estimated_90m", shade="estimated_public"), 2.0),
        (_routes("exact", terrain="estimated_90m", shade="estimated_public"), 0.4),
    ))
    monkeypatch.setattr(
        prewarm_route_cache,
        "_recommend",
        lambda *_args: next(responses),
    )
    monkeypatch.setattr(prewarm_route_cache.time, "sleep", lambda _seconds: None)

    result = prewarm_route_cache.prewarm_pair(
        "http://localhost:8080",
        "북구청",
        "부산역",
        max_wait_seconds=30,
        poll_seconds=1,
        max_cached_seconds=2,
    )

    assert result["attempts"] == 2
    assert result["cachedResponseSeconds"] == 0.4
    assert result["terrainReadyCount"] == 3
    assert result["shadeReadyCount"] == 3


def test_prewarm_retries_transient_route_provider_error(monkeypatch):
    monkeypatch.setattr(
        prewarm_route_cache,
        "_place",
        lambda _base, query: {
            "id": query,
            "name": query,
            "lat": 35.1,
            "lng": 129.0,
        },
    )
    responses = iter((
        RuntimeError("HTTP 503"),
        (
            _routes(
                "exact",
                terrain="estimated_90m",
                shade="estimated_public",
            ),
            0.5,
        ),
        (
            _routes(
                "exact",
                terrain="estimated_90m",
                shade="estimated_public",
            ),
            0.4,
        ),
    ))

    def recommend(*_args):
        result = next(responses)
        if isinstance(result, Exception):
            raise result
        return result

    monkeypatch.setattr(prewarm_route_cache, "_recommend", recommend)
    monkeypatch.setattr(prewarm_route_cache.time, "sleep", lambda _seconds: None)

    result = prewarm_route_cache.prewarm_pair(
        "http://localhost:8080",
        "북구청",
        "부산역",
        max_wait_seconds=30,
        poll_seconds=1,
        max_cached_seconds=2,
    )

    assert result["attempts"] == 2


def test_prewarm_rejects_slow_cached_response(monkeypatch):
    monkeypatch.setattr(
        prewarm_route_cache,
        "_place",
        lambda _base, query: {"id": query, "name": query, "lat": 35.1, "lng": 129.0},
    )
    monkeypatch.setattr(
        prewarm_route_cache,
        "_recommend",
        lambda *_args: (
            _routes(
                "exact",
                terrain="estimated_90m",
                shade="estimated_public",
            ),
            3.0,
        ),
    )

    with pytest.raises(RuntimeError, match="캐시 응답"):
        prewarm_route_cache.prewarm_pair(
            "http://localhost:8080",
            "북구청",
            "부산역",
            max_wait_seconds=30,
            poll_seconds=1,
            max_cached_seconds=2,
        )
