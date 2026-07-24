"""장소/날씨 공급자 계약. 개발 demo와 운영 live를 섞지 않는다."""
import asyncio

import httpx
import pytest

from app.providers import get_current_weather, search_places
from app.providers import places as places_provider
from app.providers.weather import _map_openweather
from app.providers.odsay import _normalize
from app.models import Place
from app.settings import settings


def _force_mock(monkeypatch):
    monkeypatch.setattr(settings, "kakao_rest_api_key", "")
    monkeypatch.setattr(settings, "openweather_api_key", "")


def test_places_falls_back_to_mock_without_key(monkeypatch):
    _force_mock(monkeypatch)
    results = asyncio.run(search_places("서면"))
    assert any(p.name == "서면역" for p in results)


def test_places_empty_query_returns_empty(monkeypatch):
    _force_mock(monkeypatch)
    assert asyncio.run(search_places("   ")) == []


def test_kakao_places_searches_busan_with_rest_key(monkeypatch):
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            request=request,
            json={
                "documents": [
                    {
                        "id": "place-busan-station",
                        "place_name": "부산역",
                        "y": "35.1151",
                        "x": "129.0414",
                        "category_group_name": "지하철역",
                        "road_address_name": "부산 동구 중앙대로 206",
                    },
                    {
                        "id": "place-bukgu-office",
                        "place_name": "부산광역시 북구청",
                        "y": "35.1972",
                        "x": "128.9903",
                        "category_group_name": "공공기관",
                        "address_name": "부산 북구 구포동",
                    },
                ]
            },
        )

    transport = httpx.MockTransport(handler)
    real_client = httpx.AsyncClient
    monkeypatch.setattr(
        places_provider.httpx,
        "AsyncClient",
        lambda **kwargs: real_client(transport=transport, **kwargs),
    )
    monkeypatch.setattr(settings, "app_env", "development")
    monkeypatch.setattr(settings, "kakao_rest_api_key", "test-rest-key")

    results = asyncio.run(search_places("부산역"))

    assert [place.name for place in results] == ["부산역", "부산광역시 북구청"]
    assert len(requests) == 1
    request = requests[0]
    assert request.headers["Authorization"] == "KakaoAK test-rest-key"
    assert request.url.params["query"] == "부산역"
    assert request.url.params["size"] == "15"
    assert request.url.params["rect"] == "128.7,34.8,129.4,35.5"


def test_kakao_places_reports_auth_failure_without_exposing_key(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, request=request, json={"code": -401})

    transport = httpx.MockTransport(handler)
    real_client = httpx.AsyncClient
    monkeypatch.setattr(
        places_provider.httpx,
        "AsyncClient",
        lambda **kwargs: real_client(transport=transport, **kwargs),
    )
    monkeypatch.setattr(settings, "kakao_rest_api_key", "must-not-leak")

    with pytest.raises(RuntimeError, match="authentication failed") as error:
        asyncio.run(search_places("북구청"))
    assert "must-not-leak" not in str(error.value)


def test_weather_falls_back_to_mock_without_key(monkeypatch):
    _force_mock(monkeypatch)
    w = asyncio.run(get_current_weather("heatwave"))
    assert w.is_heatwave is True
    assert w.label == "폭염"


def test_active_sources_hides_keys(monkeypatch):
    _force_mock(monkeypatch)
    src = settings.active_sources()
    assert src["places"] == "mock"
    assert src["weather"] == "mock"
    # 키 값이 노출되지 않는다
    assert all("=" not in v and len(v) < 30 for v in src.values())


def test_live_weather_uses_measured_pm10_and_aqi():
    weather = {
        "main": {"temp": 28.4, "feels_like": 30.1},
        "wind": {"speed": 2.4},
        "weather": [{"main": "Clear"}],
    }
    air = {"list": [{"main": {"aqi": 3}, "components": {"pm10": 61.25}}]}
    result = _map_openweather(weather, air)
    assert result.pm10 == 61.2
    assert result.air == "bad"


def test_live_weather_rejects_missing_measurement_instead_of_defaulting():
    with pytest.raises(ValueError, match="필수 관측값"):
        _map_openweather({"main": {}, "wind": {}, "weather": []}, {"list": []})


def test_odsay_normalizer_rejects_missing_required_metrics():
    origin = Place(id="a", name="부산역", lat=35.1151, lng=129.0414)
    destination = Place(id="b", name="서면역", lat=35.1578, lng=129.0594)
    payload = {
        "result": {"path": [{
            "info": {
                "totalTime": 20,
                # totalWalk 누락을 도보 0m로 위장해서는 안 된다.
                "busTransitCount": 0,
                "subwayTransitCount": 0,
            },
            "subPath": [{"trafficType": 3, "sectionTime": 5, "distance": 320}],
        }]}
    }
    assert _normalize(payload, origin, destination) == []
