"""날씨 시나리오 mock. 프론트 data/weather.ts 와 동일."""
from __future__ import annotations

from ..models import WeatherCondition

WEATHER_SCENARIOS: dict[str, WeatherCondition] = {
    "normal": WeatherCondition(
        label="평상 (맑음)", temp_c=21, feels_like_c=21, precipitation_mm=0,
        is_heatwave=False, is_coldwave=False, wind_ms=2, pm10=30, sky="clear", air="good",
    ),
    "heatwave": WeatherCondition(
        label="폭염", temp_c=36, feels_like_c=39, precipitation_mm=0,
        is_heatwave=True, is_coldwave=False, wind_ms=1, pm10=55, sky="clear", air="moderate",
    ),
    "coldwave": WeatherCondition(
        label="한파", temp_c=-8, feels_like_c=-14, precipitation_mm=0,
        is_heatwave=False, is_coldwave=True, wind_ms=7, pm10=40, sky="cloudy", air="moderate",
    ),
    "rain": WeatherCondition(
        label="비", temp_c=18, feels_like_c=18, precipitation_mm=7,
        is_heatwave=False, is_coldwave=False, wind_ms=5, pm10=20, sky="rain", air="good",
    ),
    "dust": WeatherCondition(
        label="미세먼지 나쁨", temp_c=14, feels_like_c=14, precipitation_mm=0,
        is_heatwave=False, is_coldwave=False, wind_ms=3, pm10=145, sky="cloudy", air="very_bad",
    ),
}

DEFAULT_WEATHER = "normal"


def get_weather(scenario: str | None) -> WeatherCondition:
    return WEATHER_SCENARIOS.get(scenario or DEFAULT_WEATHER, WEATHER_SCENARIOS[DEFAULT_WEATHER])
