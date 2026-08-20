import asyncio
from datetime import UTC, datetime

import pytest

import app.providers.busan_subway as provider
from app.settings import settings


@pytest.fixture(autouse=True)
def _clear(monkeypatch):
    provider.clear_subway_timetable_cache()
    monkeypatch.setattr(settings, "data_go_kr_service_key", "configured")


def _payload(station: str, rows: list[dict[str, str]]):
    return {
        "response": {
            "header": {"resultCode": "00", "resultMsg": "NORMAL SERVICE."},
            "body": {
                "items": {"item": [dict(row, sname=station) for row in rows]},
                "numOfRows": 1000,
                "pageNo": 1,
                "totalCount": len(rows),
            },
        },
    }


def test_next_journey_matches_same_train_and_direction(monkeypatch):
    common = {"line": "1", "dayType": "1", "endcode": "95"}
    payloads = {
        "부산": _payload("부산", [
            dict(common, trainno="1000", updown="0", arrtime="09:58:00"),
            dict(common, trainno="1001", updown="0", arrtime="10:05:00"),
            dict(common, trainno="1001", updown="1", arrtime="10:06:00"),
        ]),
        "서면": _payload("서면", [
            dict(common, trainno="1001", updown="1", arrtime="09:54:00"),
            dict(common, trainno="1001", updown="0", arrtime="10:18:00"),
        ]),
    }
    calls: list[dict[str, object]] = []

    class FakeResponse:
        def __init__(self, payload):
            self._payload = payload

        def raise_for_status(self):
            return None

        def json(self):
            return self._payload

    class FakeClient:
        def __init__(self, **_kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def get(self, url, *, params):
            assert url.endswith("/getTrainTime")
            assert params["serviceKey"] == "configured"
            calls.append(params)
            return FakeResponse(payloads[str(params["sname"])])

    monkeypatch.setattr(provider.httpx, "AsyncClient", FakeClient)
    journey = asyncio.run(provider.get_next_subway_journey(
        "부산역",
        "서면역",
        datetime(2026, 8, 3, 1, 0, tzinfo=UTC),
    ))

    assert journey.departure_time == "10:05:00"
    assert journey.destination_arrival_time == "10:18:00"
    assert {call["sname"] for call in calls} == {"부산", "서면"}
    assert all(call["dayType"] == 1 for call in calls)


def test_station_schedule_is_cached_across_requests(monkeypatch):
    row = {
        "line": "1",
        "trainno": "1001",
        "dayType": "1",
        "updown": "0",
        "endcode": "95",
    }
    payloads = {
        "부산": _payload("부산", [dict(row, arrtime="10:05:00")]),
        "서면": _payload("서면", [dict(row, arrtime="10:18:00")]),
    }
    calls = 0

    class FakeResponse:
        def __init__(self, payload):
            self._payload = payload

        def raise_for_status(self):
            return None

        def json(self):
            return self._payload

    class FakeClient:
        def __init__(self, **_kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def get(self, _url, *, params):
            nonlocal calls
            calls += 1
            await asyncio.sleep(0.01)
            return FakeResponse(payloads[str(params["sname"])])

    monkeypatch.setattr(provider.httpx, "AsyncClient", FakeClient)
    reference = datetime(2026, 8, 3, 1, 0, tzinfo=UTC)

    async def run():
        return await asyncio.gather(*(
            provider.get_next_subway_journey("부산", "서면", reference)
            for _ in range(5)
        ))

    results = asyncio.run(run())
    assert calls == 2
    assert all(result.departure_time == "10:05:00" for result in results)
