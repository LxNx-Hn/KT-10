import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

import app.main as app_main
import app.providers.transit_arrivals as provider
from app.providers.busan_subway import SubwayJourney, SubwayTimetableError
from app.providers.busan_bus import BusStopCandidate
from app.data.weather import WEATHER_SCENARIOS
from app.main import app
from app.models import (
    BusArrival,
    BusStopArrivals,
    LatLng,
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
        station_name="부산역",
        path=[
            LatLng(lat=35.1151, lng=129.0414),
            LatLng(lat=35.1578, lng=129.0592),
        ],
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
        transit_route_id="71",
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

    async def fake_find(name, *, lat, lng):
        assert name == "부산역"
        assert lat == 35.1151
        assert lng == 129.0414
        return [BusStopCandidate("505780000", "부산역", 8.0)]

    monkeypatch.setattr(provider, "get_bus_arrivals", fake_get)
    monkeypatch.setattr(provider, "find_bus_stop_candidates", fake_find)

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


def test_tmap_bus_stop_id_is_resolved_once_by_name_and_coordinate(monkeypatch):
    monkeypatch.setattr(settings, "bus_service_key", "configured")
    segment = _bus_segment()
    segment.transit_start_id = "639485"
    segment.station_name = "부산시청"
    segment.path = [
        LatLng(lat=35.1797, lng=129.0750),
        LatLng(lat=35.1800, lng=129.0760),
    ]
    resolved: list[tuple[str, float | None, float | None]] = []

    async def fake_find(name, *, lat, lng):
        resolved.append((name, lat, lng))
        return [BusStopCandidate("505790000", "부산시청", 12.0)]

    async def fake_get(stop_id):
        assert stop_id == "505790000"
        return BusStopArrivals(
            stop_id=stop_id,
            stop_name="부산시청",
            arrivals=[BusArrival(route_name="100", arrival_min=4)],
        )

    monkeypatch.setattr(provider, "find_bus_stop_candidates", fake_find)
    monkeypatch.setattr(provider, "get_bus_arrivals", fake_get)
    result = asyncio.run(provider.get_route_transit_arrivals([segment]))[0]

    assert result.status == "live"
    assert result.arrival_min == 4
    assert resolved == [("부산시청", 35.1797, 129.0750)]


def test_subway_schedule_is_lazy_and_truthfully_labeled(monkeypatch):
    monkeypatch.setattr(settings, "data_go_kr_service_key", "configured")
    calls = 0
    reference = datetime(2026, 8, 3, 1, 0, tzinfo=UTC)  # KST 10:00

    async def fake_journey(start_name, end_name, local_reference, route_id):
        nonlocal calls
        calls += 1
        assert start_name == "부산역"
        assert end_name == "서면역"
        assert route_id == "71"
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


def _subway_segment_between(start_name: str, end_name: str, route_id: str) -> RouteSegment:
    segment = _subway_segment()
    segment.station_name = start_name
    segment.end_station_name = end_name
    segment.transit_route_id = route_id
    return segment


def _scheduled_arrival(
    monkeypatch,
    *,
    seconds_until_departure: float,
    segment: RouteSegment | None = None,
) -> TransitLegArrival:
    """출발까지 남은 초를 지정해 시간표 도착값을 계산한다."""
    monkeypatch.setattr(settings, "data_go_kr_service_key", "configured")
    reference = datetime(2026, 8, 3, 1, 0, tzinfo=UTC)  # KST 10:00
    target = segment or _subway_segment()

    async def fake_journey(_start, _end, local_reference, _route_id):
        departure_at = local_reference + timedelta(seconds=seconds_until_departure)
        return SubwayJourney(
            departure_time=departure_at.strftime("%H:%M:%S"),
            destination_arrival_time="10:18:00",
            departure_at=departure_at,
            destination_arrival_at=departure_at + timedelta(minutes=13),
        )

    monkeypatch.setattr(provider, "get_next_subway_journey", fake_journey)
    provider.clear_transit_arrival_cache()
    return asyncio.run(
        provider.get_route_transit_arrivals([target], reference=reference)
    )[0]


@pytest.mark.parametrize(
    ("seconds_until_departure", "expected_min"),
    [
        (150, 3),   # 2분 30초는 3분으로 반올림
        (119, 2),   # 1분 59초는 2분
        (90, 2),    # 1분 30초는 2분
        (61, 1),    # 1분 01초는 1분
        (60, 1),    # 정확히 1분은 1분
        (59, 0),    # 1분 미만은 반올림하지 않고 0
        (1, 0),
        (0, 0),
        (-30, 0),   # 출발시각이 지나도 음수 분을 만들지 않는다
    ],
)
def test_subway_minutes_round_to_nearest_and_floor_under_one_minute(
    monkeypatch,
    seconds_until_departure,
    expected_min,
):
    result = _scheduled_arrival(
        monkeypatch,
        seconds_until_departure=seconds_until_departure,
    )
    assert result.arrival_min == expected_min


def test_subway_boarding_kind_separates_origin_terminal_from_intermediate(monkeypatch):
    intermediate = _scheduled_arrival(
        monkeypatch,
        seconds_until_departure=300,
        segment=_subway_segment_between("부산역", "서면역", "71"),
    )
    assert intermediate.boarding_kind == "intermediate"

    origin = _scheduled_arrival(
        monkeypatch,
        seconds_until_departure=300,
        segment=_subway_segment_between("다대포해수욕장역", "서면역", "71"),
    )
    assert origin.boarding_kind == "origin"

    reverse_origin = _scheduled_arrival(
        monkeypatch,
        seconds_until_departure=300,
        segment=_subway_segment_between("노포역", "서면역", "71"),
    )
    assert reverse_origin.boarding_kind == "origin"


def test_scheduled_arrival_keeps_timetable_disclaimer_regardless_of_boarding_kind(
    monkeypatch,
):
    """중간역이 '도착'으로 표시되더라도 시간표 기준 고지는 사라지지 않는다."""
    for start, end in (("부산역", "서면역"), ("노포역", "서면역")):
        result = _scheduled_arrival(
            monkeypatch,
            seconds_until_departure=30,
            segment=_subway_segment_between(start, end, "71"),
        )
        assert result.status == "scheduled"
        assert "실시간 열차 위치는 아닙니다" in (result.arrival_message or "")


def test_bus_arrival_has_no_boarding_kind_because_bims_omits_terminals(monkeypatch):
    monkeypatch.setattr(settings, "bus_service_key", "configured")

    async def fake_candidates(*_args, **_kwargs):
        return [BusStopCandidate(stop_id="505780000", stop_name="부산역", distance_m=10.0)]

    async def fake_arrivals(_stop_id):
        return BusStopArrivals(
            stop_id="505780000",
            stop_name="부산역",
            arrivals=[BusArrival(route_name="100", vehicle_no="1234", arrival_min=0)],
        )

    monkeypatch.setattr(provider, "find_bus_stop_candidates", fake_candidates)
    monkeypatch.setattr(provider, "get_bus_arrivals", fake_arrivals)

    result = asyncio.run(provider.get_route_transit_arrivals([_bus_segment()]))[0]
    assert result.status == "live"
    assert result.arrival_min == 0
    assert result.boarding_kind is None


def test_subway_schedule_exposes_classified_safe_failure(monkeypatch):
    monkeypatch.setattr(settings, "data_go_kr_service_key", "configured")

    async def fake_journey(*_args):
        raise SubwayTimetableError(
            "station_mapping_failed",
            "도시철도 노선과 승·하차역을 정확히 확인할 수 없습니다.",
        )

    monkeypatch.setattr(provider, "get_next_subway_journey", fake_journey)
    result = asyncio.run(provider.get_route_transit_arrivals([
        _subway_segment(),
    ]))[0]

    assert result.status == "unavailable"
    assert result.arrival_message == (
        "도시철도 노선과 승·하차역을 정확히 확인할 수 없습니다."
    )


def test_external_subway_is_listed_as_unavailable_without_false_busan_timetable(
    monkeypatch,
):
    segment = _subway_segment()
    segment.description = "동해선 · 교대역 → 거제역"
    segment.transit_route_id = "동해선"
    monkeypatch.setattr(settings, "data_go_kr_service_key", "configured")

    async def fail_if_called(*_args):
        raise AssertionError("외부 철도에 부산교통공사 시간표를 호출하면 안 됩니다.")

    monkeypatch.setattr(provider, "get_next_subway_journey", fail_if_called)
    result = asyncio.run(provider.get_route_transit_arrivals([segment]))[0]

    assert result.status == "unavailable"
    assert result.source == "철도 도착정보 공급원 미연계"
    assert "동해선·부산김해경전철" in (result.arrival_message or "")


def test_train_segment_is_included_and_truthfully_unavailable():
    segment = _subway_segment()
    segment.id = "train-1"
    segment.mode = "train"
    segment.description = "동해선 열차 · 교대역 → 거제역"

    result = asyncio.run(provider.get_route_transit_arrivals([segment]))[0]

    assert result.segment_id == "train-1"
    assert result.mode == "train"
    assert result.status == "unavailable"
    assert "공급원이 아직 연결되지 않았습니다" in (result.arrival_message or "")


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
