"""
환경설정. API 키는 .env 또는 환경변수에서만 읽으며 코드/로그에 노출하지 않는다.
키가 있으면 해당 소스를 라이브로 사용하고, 없으면 mock 으로 자동 폴백한다.
"""
from __future__ import annotations

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

_ENV_FILE = Path(__file__).resolve().parents[1] / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=_ENV_FILE, env_file_encoding="utf-8", env_ignore_empty=True, extra="ignore"
    )

    # 외부 API 키 (없으면 mock 폴백) — 서버 전용, 클라이언트로 전달되지 않음
    kakao_rest_api_key: str = ""        # Kakao 장소검색(REST)
    openweather_api_key: str = ""       # 실시간 날씨
    bus_service_key: str = ""           # 공공데이터 저상버스 도착(정류장 데이터셋 필요)
    odsay_api_key: str = ""             # 실제 대중교통 후보 생성(서버 전용)

    # ai/ 파이프라인 서버(경로 수집+XGB 순위화). 설정 시 /api/routes/recommend가
    # 자체 scoring 엔진 대신 이 서버로 위임한다.
    ai_server_url: str = ""

    # PostgreSQL + Kakao 로그인. 실제 값은 배포 환경변수로만 주입한다.
    database_url: str = ""
    session_secret: str = ""
    kakao_oauth_client_secret: str = ""
    kakao_oauth_redirect_uri: str = "http://localhost:8002/api/auth/kakao/callback"
    frontend_url: str = "http://localhost:5173"

    # CORS 허용 오리진(콤마 구분)
    allowed_origins: str = (
        "http://localhost:5173,http://127.0.0.1:5173,http://localhost:4173"
    )

    # 외부 호출 타임아웃(초)
    request_timeout: float = 4.0

    # 후기 개인화 정책. 실제 검증 전 임의 기본값을 넣지 않고 운영자가 명시한다.
    personalization_learning_rate: float | None = Field(default=None, gt=0, le=1)
    personalization_regularization: float | None = Field(default=None, ge=0, le=1)
    personalization_max_share: float | None = Field(default=None, gt=0, lt=1)
    personalization_prior_reviews: float | None = Field(default=None, gt=0)
    personalization_usable_weight: float | None = Field(default=None, ge=0, le=1)
    personalization_rating_weight: float | None = Field(default=None, ge=0, le=1)
    personalization_reuse_weight: float | None = Field(default=None, ge=0, le=1)

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
    def live_ai_pipeline(self) -> bool:
        return bool(self.ai_server_url)

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

    @property
    def personalization_configured(self) -> bool:
        values = (
            self.personalization_learning_rate,
            self.personalization_regularization,
            self.personalization_max_share,
            self.personalization_prior_reviews,
            self.personalization_usable_weight,
            self.personalization_rating_weight,
            self.personalization_reuse_weight,
        )
        return all(value is not None for value in values) and sum((
            self.personalization_usable_weight or 0,
            self.personalization_rating_weight or 0,
            self.personalization_reuse_weight or 0,
        )) > 0

    def active_sources(self) -> dict[str, str]:
        """기동 로그용. 키 값은 절대 포함하지 않고 live/mock 여부만 표시."""
        return {
            "places": "kakao(live)" if self.live_places else "mock",
            "weather": "openweather(live)" if self.live_weather else "mock",
            "bus": "live" if self.live_bus else "mock",
            "routes": "odsay(live)" if self.live_routes else "demo/mock",
            "ai_pipeline": "connected" if self.live_ai_pipeline else "not configured",
            "database": "postgresql(configured)" if self.database_configured else "not configured",
            "auth": "kakao(configured)" if self.kakao_login_configured else "not configured",
        }


settings = Settings()
