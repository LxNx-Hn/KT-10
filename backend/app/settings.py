"""
환경설정. API 키는 .env 또는 환경변수에서만 읽으며 코드/로그에 노출하지 않는다.
키가 있으면 해당 소스를 라이브로 사용하고, 없으면 mock 으로 자동 폴백한다.
"""
from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    # 외부 API 키 (없으면 mock 폴백) — 서버 전용, 클라이언트로 전달되지 않음
    kakao_rest_api_key: str = ""        # Kakao 장소검색(REST)
    openweather_api_key: str = ""       # 실시간 날씨
    bus_service_key: str = ""           # 공공데이터 저상버스 도착(정류장 데이터셋 필요)

    # CORS 허용 오리진(콤마 구분)
    allowed_origins: str = (
        "http://localhost:5173,http://127.0.0.1:5173,http://localhost:4173"
    )

    # 외부 호출 타임아웃(초)
    request_timeout: float = 4.0

    @property
    def origins(self) -> list[str]:
        return [o.strip() for o in self.allowed_origins.split(",") if o.strip()]

    @property
    def live_places(self) -> bool:
        return bool(self.kakao_rest_api_key)

    @property
    def live_weather(self) -> bool:
        return bool(self.openweather_api_key)

    @property
    def live_bus(self) -> bool:
        return bool(self.bus_service_key)

    def active_sources(self) -> dict[str, str]:
        """기동 로그용. 키 값은 절대 포함하지 않고 live/mock 여부만 표시."""
        return {
            "places": "kakao(live)" if self.live_places else "mock",
            "weather": "openweather(live)" if self.live_weather else "mock",
            "bus": "live" if self.live_bus else "mock",
            "routes": "mock(synthesized)",
        }


settings = Settings()
