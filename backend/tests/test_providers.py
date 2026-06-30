"""프로바이더 폴백 테스트: 키가 없으면 mock 으로 동작해야 한다(데모 가용성 보장)."""
import asyncio

from app.providers import get_current_weather, search_places
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
