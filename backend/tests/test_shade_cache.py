from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from threading import Barrier, Lock
import time
from zoneinfo import ZoneInfo

from app.models import ShadeSummary
from app.settings import settings
from app.shade_cache import get_or_compute, read, write

KST = ZoneInfo("Asia/Seoul")


def _summary(evaluated_at: datetime) -> ShadeSummary:
    return ShadeSummary(
        status="estimated_public",
        evaluated_at=evaluated_at,
        shade_ratio=0.42,
        shaded_walk_m=420,
        total_walk_m=1000,
        solar_azimuth_deg=210,
        solar_elevation_deg=55,
        building_height_coverage=0.8,
        building_count=10,
        known_height_building_count=8,
        estimate_kind="lower_bound",
        overlay_resolution_m=10,
        walking_geometry_quality="exact",
        source="VWorld LT_C_BLDGINFO WFS",
        data_quality="public",
        calculation_note="검증된 공공 건물 결과",
    )


def test_shade_cache_reuses_same_half_hour_bucket(
    monkeypatch,
    tmp_path,
):
    monkeypatch.setattr(settings, "shade_cache_dir", str(tmp_path))
    monkeypatch.setattr(settings, "shade_cache_ttl_seconds", 3600)
    first_at = datetime(2026, 7, 26, 14, 2, tzinfo=KST)
    same_bucket_at = datetime(2026, 7, 26, 14, 29, tzinfo=KST)

    write("route-stable-id", first_at, _summary(first_at))
    cached = read("route-stable-id", same_bucket_at)

    assert cached is not None
    assert cached.shade_ratio == 0.42
    assert cached.evaluated_at == same_bucket_at
    assert (
        read(
            "route-stable-id",
            datetime(2026, 7, 26, 14, 30, tzinfo=KST),
        )
        is None
    )


def test_shade_cache_does_not_store_unavailable_result(
    monkeypatch,
    tmp_path,
):
    monkeypatch.setattr(settings, "shade_cache_dir", str(tmp_path))
    monkeypatch.setattr(settings, "shade_cache_ttl_seconds", 3600)
    evaluated_at = datetime(2026, 7, 26, 14, 0, tzinfo=KST)
    unavailable = ShadeSummary(
        status="unavailable",
        evaluated_at=evaluated_at,
        source="VWorld LT_C_BLDGINFO WFS",
        data_quality="public",
        calculation_note="",
    )

    write("route-unavailable", evaluated_at, unavailable)

    assert list(tmp_path.iterdir()) == []


def test_shade_cache_singleflights_same_route_and_time(
    monkeypatch,
    tmp_path,
):
    monkeypatch.setattr(settings, "shade_cache_dir", str(tmp_path))
    monkeypatch.setattr(settings, "shade_cache_ttl_seconds", 3600)
    evaluated_at = datetime(2026, 7, 26, 14, 0, tzinfo=KST)
    start = Barrier(2)
    counter_lock = Lock()
    compute_count = 0

    def compute() -> ShadeSummary:
        nonlocal compute_count
        with counter_lock:
            compute_count += 1
        time.sleep(0.05)
        return _summary(evaluated_at)

    def request() -> ShadeSummary:
        start.wait()
        return get_or_compute(
            "route-singleflight",
            evaluated_at,
            compute,
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(request)
        second = executor.submit(request)
        summaries = [first.result(), second.result()]

    assert compute_count == 1
    assert [summary.shade_ratio for summary in summaries] == [0.42, 0.42]
