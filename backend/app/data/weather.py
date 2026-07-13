"""날씨 시나리오 — 공유 데이터셋(data/ai/weather.json)에서 로드."""
from __future__ import annotations

from ..models import WeatherCondition
from ._loader import load

WEATHER_SCENARIOS: dict[str, WeatherCondition] = {
    k: WeatherCondition.model_validate(v) for k, v in load("weather.json").items()
}

DEFAULT_WEATHER = "normal"


def get_weather(scenario: str | None) -> WeatherCondition:
    return WEATHER_SCENARIOS.get(scenario or DEFAULT_WEATHER, WEATHER_SCENARIOS[DEFAULT_WEATHER])
