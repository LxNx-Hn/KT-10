import asyncio
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

import app.main as app_main
import app.providers.transit_arrivals as provider
from app.providers.busan_subway import SubwayJourney
from app.data.weather import WEATHER_SCENARIOS
from app.main import app
from app.models import (
    BusArrival,
    BusStopArrivals,
    RouteCandidate,
    RouteSegment,
    TransitLegArrival,
)
from app.route_set_cache import route_set_cache
from app.settings import settings

client = TestClient(app)


@pytest.fixture(autouse=True)
def _clear_state(monkeypatch):
    provider.clear_transit_arrival_cache()
    route_set_cache.clear()
    monkeypatch.setattr(settings, "bus_service_key", "")
    monkeypatch.setattr(settings, "data_go_kr_service_key", "")


def _bus_segment() -> RouteSegment:
    return RouteSegment(
        id="bus-1",
        mode="bus",
        description="100 · 부산역 → 서면역",
        duration_min=15,
        bus_route_name="100",
        transit_start_id="505780000",
    )


def _bus_segment_with_id(segment_id: str) -> RouteSegment:
    segment = _bus_segment()
    segment.id = segment_id
    return segment


def _subway_segment() -> RouteSegment:
    return RouteSegment(
        id="subway-1",
        mode="subway",
        description="부산 1호선 · 부산역 → 서면역",
        duration_min=12,
        station_name="부산역",
        end_station_name="서면역",
        transit_start_id="114",
        transit_end_id="119",
        transit_direction="노포",
    )


def test_bus_arrival_is_filtered_and_single_flight_cached(monkeypatch):
    monkeypatch.setattr(settings, "bus_service_key", "configured")
    calls = 0

    async def fake_get(stop_id: str):
        nonlocal calls
        calls += 1
        await asyncio.sleep(0.01)
        assert stop_id == "505780000"
        return BusStopArrivals(
            stop_id=stop_id,
            stop_name="부산역",
            arrivals=[
                BusArrival(route_name="101", arrival_min=2),
                BusArrival(route_name="100", arrival_min=7),
                BusArrival(route_name="100", arrival_min=3),
            ],
        )

    monkeypatch.setattr(provider, "get_bus_arrivals", fake_get)

    async def run():
        return await asyncio.gather(*(
            provider.get_route_transit_arrivals([_bus_segment()])
            for _ in range(8)
        ))

    results = asyncio.run(run())
    assert calls == 1
    assert all(result[0].status == "live" for result in results)
    assert all(result[0].arrival_min == 3 for result in results)

    reused = asyncio.run(provider.get_route_transit_arrivals([
        _bus_segment_with_id("another-route-bus-1"),
    ]))
    assert calls == 1
    assert reused[0].segment_id == "another-route-bus-1"


def test_subway_schedule_is_lazy_and_truthfully_labeled(monkeypatch):
    monkeypatch.setattr(settings, "data_go_kr_service_key", "configured")
    calls = 0
    reference = datetime(2026, 8, 3, 1, 0, tzinfo=UTC)  # KST 10:00

    async def fake_journey(start_name, end_name, local_reference):
        nonlocal calls
        calls += 1
        assert start_name == "부산역"
        assert end_name == "서면역"
        assert local_reference.hour == 10
        return SubwayJourney(
            departure_time="10:05:00",
            destination_arrival_time="10:18:00",
            departure_at=datetime(2026, 8, 3, 10, 5, tzinfo=local_reference.tzinfo),
            destination_arrival_at=datetime(
                2026, 8, 3, 10, 18, tzinfo=local_reference.tzinfo
            ),
        )

    monkeypatch.setattr(provider, "get_next_subway_journey", fake_journey)

    async def run():
        return await asyncio.gather(*(
            provider.get_route_transit_arrivals(
                [_subway_segment()],
                reference=reference,
            )
            for _ in range(5)
        ))

    results = asyncio.run(run())
    assert calls == 1
    result = results[0][0]
    assert result.status == "scheduled"
    assert result.arrival_min == 5
    assert result.departure_time == "10:05:00"
    assert "실시간 열차 위치는 아닙니다" in (result.arrival_message or "")
    assert result.source == "부산교통공사 도시철도 시간표"


def test_route_arrival_endpoint_uses_existing_route_set_only(monkeypatch):
    candidate = RouteCandidate(
        id="route-1",
        summary="100번 버스",
        origin="부산역",
        destination="서면역",
        segments=[_bus_segment()],
        total_duration_min=15,
        total_walk_m=0,
        transfer_count=0,
    )
    token = route_set_cache.put(
        [candidate],
        WEATHER_SCENARIOS["normal"].model_copy(deep=True),
    )
    captured = []

    async def fake_arrivals(segments):
        captured.extend(segments)
        return [TransitLegArrival(
            segment_id="bus-1",
            mode="bus",
            status="live",
            arrival_min=4,
            observed_at=datetime.now(UTC),
            source="test",
        )]

    monkeypatch.setattr(app_main, "get_route_transit_arrivals", fake_arrivals)
    response = client.post(
        "/api/routes/transit-arrivals",
        json={"routeSetToken": token, "routeId": "route-1"},
    )

    assert response.status_code == 200
    assert response.json()["arrivals"][0]["arrivalMin"] == 4
    assert captured[0].transit_start_id == "505780000"


def test_route_arrival_endpoint_rejects_foreign_route():
    token = route_set_cache.put(
        [RouteCandidate(
            id="route-1",
            summary="100번 버스",
            origin="부산역",
            destination="서면역",
            segments=[_bus_segment()],
            total_duration_min=15,
            total_walk_m=0,
            transfer_count=0,
        )],
        WEATHER_SCENARIOS["normal"].model_copy(deep=True),
    )
    response = client.post(
        "/api/routes/transit-arrivals",
        json={"routeSetToken": token, "routeId": "other-route"},
    )
    assert response.status_code == 422


def test_initial_recommendation_never_calls_lazy_arrival_provider(monkeypatch):
    monkeypatch.setattr(settings, "route_mode", "demo")
    monkeypatch.setattr(settings, "building_source", "demo")

    async def fail_if_called(_segments):
        raise AssertionError("초기 추천이 도착정보 공급자를 호출했습니다.")

    monkeypatch.setattr(app_main, "get_route_transit_arrivals", fail_if_called)
    response = client.post(
        "/api/routes/recommend",
        json={
            "origin": {
                "id": "gu-office",
                "name": "부산진구청",
                "lat": 35.1627,
                "lng": 129.0531,
            },
            "destination": {
                "id": "seomyeon-stn",
                "name": "서면역",
                "lat": 35.1578,
                "lng": 129.0592,
            },
            "profile": "general",
            "weatherScenario": "normal",
            "options": {"departureAt": "2026-08-03T14:00:00+09:00"},
            "topN": 3,
        },
    )

    assert response.status_code == 200
