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
    odsay_api_key: str = ""             # 실제 대중교통 후보 생성(서버 전용)

    # PostgreSQL + Kakao 로그인. 실제 값은 배포 환경변수로만 주입한다.
    database_url: str = ""
    session_secret: str = ""
    kakao_oauth_client_secret: str = ""
    kakao_oauth_redirect_uri: str = "http://localhost:8000/api/auth/kakao/callback"
    frontend_url: str = "http://localhost:5173"
    ranking_model_path: str = ""       # 검증 완료된 초기 순위모델 JSON 경로

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

    @property
    def live_routes(self) -> bool:
        return bool(self.odsay_api_key)

    @property
    def database_configured(self) -> bool:
        return self.database_url.startswith("postgresql")

    @property
    def kakao_login_configured(self) -> bool:
        return bool(
            self.kakao_rest_api_key
            and self.kakao_oauth_client_secret
            and self.session_secret
            and self.database_configured
        )

    def active_sources(self) -> dict[str, str]:
        """기동 로그용. 키 값은 절대 포함하지 않고 live/mock 여부만 표시."""
        return {
            "places": "kakao(live)" if self.live_places else "mock",
            "weather": "openweather(live)" if self.live_weather else "mock",
            "bus": "live" if self.live_bus else "mock",
            "routes": "odsay(live)" if self.live_routes else "demo/mock",
            "database": "postgresql(configured)" if self.database_configured else "not configured",
            "auth": "kakao(configured)" if self.kakao_login_configured else "not configured",
        }


settings = Settings()
