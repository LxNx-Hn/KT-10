"""날씨 프로바이더. OpenWeather 실시간(부산진구 중심) 라이브 + mock 시나리오 폴백.

라이브 모드에서는 데모 시나리오(scenario) 대신 실제 관측값을 사용한다.
폭염/한파 판정은 체감온도 임계값(기상청 기준 근사)으로 산출한다.
미세먼지(PM)는 별도 대기 API가 필요하므로 라이브 기본값은 보수적으로 둔다(README 참고).
"""
from __future__ import annotations

import logging

import httpx

from ..config import DISTRICT
from ..data.weather import get_weather
from ..models import WeatherCondition
from ..settings import settings

log = logging.getLogger("providers.weather")

OPENWEATHER_URL = "https://api.openweathermap.org/data/2.5/weather"


def _map_openweather(d: dict) -> WeatherCondition:
    main = d.get("main", {})
    wind = d.get("wind", {})
    weather0 = (d.get("weather") or [{}])[0]
    cond = (weather0.get("main") or "").lower()

    temp_c = float(main.get("temp", 0))
    feels = float(main.get("feels_like", temp_c))
    rain = float((d.get("rain") or {}).get("1h", 0) or 0)
    snow = float((d.get("snow") or {}).get("1h", 0) or 0)

    if cond in ("rain", "drizzle", "thunderstorm"):
        sky = "rain"
    elif cond == "snow":
        sky = "snow"
    elif cond == "clear":
        sky = "clear"
    else:
        sky = "cloudy"

    return WeatherCondition(
        label="실시간",
        temp_c=round(temp_c, 1),
        feels_like_c=round(feels, 1),
        precipitation_mm=round(rain + snow, 1),
        is_heatwave=feels >= 33,          # 폭염 체감 기준 근사
        is_coldwave=feels <= -10,         # 한파 체감 기준 근사
        wind_ms=round(float(wind.get("speed", 0)), 1),
        pm10=35,                          # 대기 API 미연동 기본값(README 참고)
        sky=sky,                          # type: ignore[arg-type]
        air="good",
    )


async def get_current_weather(scenario: str | None) -> WeatherCondition:
    if not settings.live_weather:
        return get_weather(scenario)
    try:
        center = DISTRICT["center"]
        async with httpx.AsyncClient(timeout=settings.request_timeout) as client:
            res = await client.get(
                OPENWEATHER_URL,
                params={
                    "lat": center["lat"],
                    "lon": center["lng"],
                    "appid": settings.openweather_api_key,
                    "units": "metric",
                    "lang": "kr",
                },
            )
            res.raise_for_status()
            return _map_openweather(res.json())
    except Exception as exc:  # 키가 URL 쿼리에 포함되므로 상세 메시지는 로깅하지 않음
        log.warning("실시간 날씨 조회 실패(%s) → mock 폴백", type(exc).__name__)
        return get_weather(scenario)
