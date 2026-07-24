"""OpenWeather 현재 날씨와 대기오염 실측을 결합하는 프로바이더."""
from __future__ import annotations

import asyncio
from datetime import UTC, datetime
import logging
import math

import httpx

from ..config import DISTRICT
from ..data.weather import get_weather
from ..models import WeatherCondition
from ..settings import settings

log = logging.getLogger("providers.weather")

OPENWEATHER_URL = "https://api.openweathermap.org/data/2.5/weather"
OPENWEATHER_AIR_URL = "https://api.openweathermap.org/data/2.5/air_pollution"


def _observation_time(value: object, source: str) -> datetime:
    if isinstance(value, bool):
        raise ValueError(f"{source} 관측시각이 유효하지 않습니다.")
    try:
        timestamp = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{source} 관측시각이 유효하지 않습니다.") from exc
    if not math.isfinite(timestamp) or timestamp <= 0:
        raise ValueError(f"{source} 관측시각이 유효하지 않습니다.")
    try:
        return datetime.fromtimestamp(timestamp, tz=UTC)
    except (OSError, OverflowError, ValueError) as exc:
        raise ValueError(f"{source} 관측시각이 유효하지 않습니다.") from exc


def _map_openweather(d: dict, air_data: dict) -> WeatherCondition:
    try:
        main = d["main"]
        wind = d["wind"]
        weather0 = d["weather"][0]
        cond = str(weather0["main"]).lower()
        temp_c = float(main["temp"])
        feels = float(main["feels_like"])
        wind_speed = float(wind["speed"])
        air_record = air_data["list"][0]
        pm10 = float(air_record["components"]["pm10"])
        aqi = int(air_record["main"]["aqi"])
        observed_at = _observation_time(d["dt"], "OpenWeather 날씨")
        air_observed_at = _observation_time(
            air_record["dt"],
            "OpenWeather 대기질",
        )
    except (KeyError, IndexError, TypeError, ValueError) as exc:
        raise ValueError("OpenWeather 응답에 필수 관측값이 없습니다.") from exc
    if aqi not in {1, 2, 3, 4, 5}:
        raise ValueError("OpenWeather AQI 값이 유효하지 않습니다.")
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
        # 현재 시점 관측만으로 일 최고기온 지속 조건인 폭염/한파 특보를 만들지 않는다.
        is_heatwave=None,
        is_coldwave=None,
        wind_ms=round(wind_speed, 1),
        pm10=round(pm10, 1),
        sky=sky,                          # type: ignore[arg-type]
        air={1: "good", 2: "moderate", 3: "bad", 4: "very_bad", 5: "very_bad"}[aqi],
        observed_at=observed_at,
        air_quality_observed_at=air_observed_at,
    )


async def get_current_weather(scenario: str | None) -> WeatherCondition:
    if not settings.live_weather:
        return get_weather(scenario)
    try:
        center = DISTRICT["center"]
        async with httpx.AsyncClient(timeout=settings.request_timeout) as client:
            weather_res, air_res = await asyncio.gather(
                client.get(
                    OPENWEATHER_URL,
                    params={
                        "lat": center["lat"],
                        "lon": center["lng"],
                        "appid": settings.openweather_api_key,
                        "units": "metric",
                        "lang": "kr",
                    },
                ),
                client.get(
                    OPENWEATHER_AIR_URL,
                    params={
                        "lat": center["lat"],
                        "lon": center["lng"],
                        "appid": settings.openweather_api_key,
                    },
                ),
            )
            weather_res.raise_for_status()
            air_res.raise_for_status()
            return _map_openweather(weather_res.json(), air_res.json())
    except (httpx.HTTPError, ValueError, TypeError, KeyError) as exc:
        # 키가 URL 쿼리에 포함되므로 상세 응답/URL은 로그에 쓰지 않는다.
        log.warning("실시간 날씨 조회 실패(%s)", type(exc).__name__)
        raise RuntimeError("OpenWeather current weather or air quality request failed") from exc
