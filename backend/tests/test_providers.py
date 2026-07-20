"""프로바이더 폴백 테스트: 키가 없으면 mock 으로 동작해야 한다(데모 가용성 보장)."""
import asyncio

from app.providers import get_current_weather, search_places
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
    import pytest

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
