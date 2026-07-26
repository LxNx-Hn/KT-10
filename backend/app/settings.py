"""
환경설정. API 키는 .env 또는 환경변수에서만 읽으며 코드/로그에 노출하지 않는다.
운영자가 명시한 모드와 키 상태를 함께 검사하며, 선택한 실공급자가 준비되지
않으면 mock으로 바꾸지 않고 명시적으로 실패한다.
"""
from __future__ import annotations

from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

_ENV_FILE = Path(__file__).resolve().parents[1] / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=_ENV_FILE, env_file_encoding="utf-8", env_ignore_empty=True, extra="ignore"
    )

    app_env: Literal["development", "production", "test"] = "development"

    # 외부 API 키 — 서버 전용, 클라이언트로 전달되지 않음
    kakao_rest_api_key: str = ""        # Kakao 장소검색(REST)
    openweather_api_key: str = ""       # 실시간 날씨
    bus_service_key: str = ""           # 공공데이터 저상버스 도착(정류장 데이터셋 필요)
    odsay_api_key: str = ""             # 실제 대중교통 후보 생성(서버 전용)

    # 키 존재 여부가 아니라 운영자가 선택한 모드로 경로 공급자를 결정한다.
    # demo: 검증된 고정 OD, live: ODsay, ai: 경로 수집+학습 순위화 서버
    route_mode: Literal["demo", "live", "ai"] = "demo"

    # 건물 footprint + 높이 공급자. vworld는 LT_C_BLDGINFO WFS를 사용한다.
    building_source: Literal["demo", "vworld"] = "demo"
    vworld_api_key: str = ""
    vworld_api_domain: str = "http://localhost:8002"
    vworld_cache_dir: str = ""
    vworld_cache_ttl_hours: int = Field(default=168, ge=1, le=24 * 365)
    shade_cache_dir: str = ""
    shade_cache_ttl_seconds: int = Field(
        default=86_400,
        ge=60,
        le=7 * 24 * 3600,
    )

    # ai/ 파이프라인 서버(경로 수집+XGB 순위화). 설정 시 /api/routes/recommend가
    # 자체 scoring 엔진 대신 이 서버로 위임한다.
    ai_server_url: str = ""

    # PostgreSQL + Kakao 로그인. 실제 값은 배포 환경변수로만 주입한다.
    database_url: str = ""
    session_secret: str = ""
    labeling_api_token: str = ""
    kakao_oauth_client_secret: str = ""
    kakao_oauth_redirect_uri: str = "http://localhost:8002/api/auth/kakao/callback"
    frontend_url: str = "http://localhost:5173"

    # CORS 허용 오리진(콤마 구분)
    allowed_origins: str = (
        "http://localhost:5173,http://127.0.0.1:5173,http://localhost:4173"
    )

    # 운영 기본 추천 후보 수. 요청 body의 topN이 없을 때만 적용하며,
    # 변경은 서비스 재시작 후 새 검색부터 반영된다(기존 route-set 소급 없음).
    route_default_top_n: int = Field(default=5, ge=1, le=10)

    # 외부 호출 타임아웃(초)
    request_timeout: float = Field(default=4.0, gt=0, le=60)
    # 부산 전역이 공유하는 현재 날씨·대기질 성공 응답의 서버 캐시.
    # 0은 캐시 비활성 상태다.
    weather_cache_ttl_seconds: int = Field(default=300, ge=0, le=3600)
    # 모든 경로 유형에 동일하게 적용하는 총 도보거리 하드 상한.
    max_supported_total_walk_m: int = Field(default=15_000, ge=100, le=50_000)

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
        return bool(self.kakao_rest_api_key.strip())

    @property
    def live_weather(self) -> bool:
        return bool(self.openweather_api_key.strip())

    @property
    def live_bus(self) -> bool:
        return bool(self.bus_service_key.strip())

    @property
    def live_routes(self) -> bool:
        return self.route_mode == "live" and bool(self.ai_server_url.strip())

    @property
    def live_ai_pipeline(self) -> bool:
        return self.route_mode == "ai" and bool(self.ai_server_url.strip())

    @property
    def live_buildings(self) -> bool:
        return self.building_source == "vworld" and bool(
            self.vworld_api_key.strip()
        )

    @property
    def database_configured(self) -> bool:
        return self.database_url.strip().startswith("postgresql+psycopg://")

    @property
    def session_signing_configured(self) -> bool:
        """서명키는 생성 스크립트와 동일하게 최소 32자 이상만 허용한다."""
        return len(self.session_secret.strip()) >= 32

    @staticmethod
    def _parsed_http_url(value: str, *, origin_only: bool):
        try:
            parsed = urlsplit(value)
            # 잘못된 포트는 .port 접근 시 ValueError가 발생한다.
            _ = parsed.port
        except ValueError:
            return None
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
            or (origin_only and parsed.path not in {"", "/"})
        ):
            return None
        return parsed

    @property
    def origin_security_configured(self) -> bool:
        parsed_origins = [
            self._parsed_http_url(origin, origin_only=True)
            for origin in self.origins
        ]
        frontend = self._parsed_http_url(
            self.frontend_url,
            origin_only=True,
        )
        redirect = self._parsed_http_url(
            self.kakao_oauth_redirect_uri,
            origin_only=False,
        )
        if (
            not parsed_origins
            or any(origin is None for origin in parsed_origins)
            or frontend is None
            or redirect is None
            or redirect.path != "/api/auth/kakao/callback"
        ):
            return False
        normalized_origins = {
            f"{origin.scheme}://{origin.netloc}".rstrip("/")
            for origin in parsed_origins
            if origin is not None
        }
        frontend_origin = (
            f"{frontend.scheme}://{frontend.netloc}".rstrip("/")
        )
        redirect_origin = (
            f"{redirect.scheme}://{redirect.netloc}".rstrip("/")
        )
        if (
            frontend_origin not in normalized_origins
        ):
            return False
        if self.app_env == "production":
            if redirect_origin != frontend_origin:
                return False
            if any(
                parsed.scheme != "https"
                for parsed in (*parsed_origins, frontend, redirect)
                if parsed is not None
            ):
                return False
        return True

    @property
    def kakao_login_configured(self) -> bool:
        return bool(
            self.kakao_rest_api_key.strip()
            and self.kakao_oauth_client_secret.strip()
            and self.session_signing_configured
            and self.database_configured
            and self.origin_security_configured
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

    def deployment_readiness(self) -> dict[str, bool]:
        """키 값은 노출하지 않고 운영에 필요한 연결 설정의 충족 여부만 반환한다."""
        live_route_candidates = (
            (self.route_mode == "live" and self.live_routes)
            or (self.route_mode == "ai" and self.live_ai_pipeline)
        )
        return {
            "live_route_candidates": live_route_candidates,
            "live_building_shade": self.building_source == "vworld" and self.live_buildings,
            "kakao_place_search": self.live_places,
            "live_weather": self.live_weather,
            "live_bus_arrivals": self.live_bus,
            "postgresql": self.database_configured,
            "session_signing": self.session_signing_configured,
            "origin_security": self.origin_security_configured,
            "kakao_login": self.kakao_login_configured,
            "personalization_policy": self.personalization_configured,
            "labeling_batch_auth": len(self.labeling_api_token.strip()) >= 32,
        }

    def active_sources(self) -> dict[str, str]:
        """기동 로그용. 키 값은 절대 포함하지 않고 live/mock 여부만 표시."""
        return {
            "places": "kakao(live)" if self.live_places else "mock",
            "weather": "openweather(live)" if self.live_weather else "mock",
            "bus": "live" if self.live_bus else "mock",
            "routes": {
                "demo": "verified-demo",
                "live": (
                    "ai-candidates(live)"
                    if self.live_routes
                    else "ai-candidates(missing-url)"
                ),
                "ai": "ai-pipeline(live)" if self.live_ai_pipeline else "ai-pipeline(missing-url)",
            }[self.route_mode],
            "ai_pipeline": "connected" if self.live_ai_pipeline else "inactive",
            "buildings": (
                "vworld(live)"
                if self.live_buildings
                else "vworld(missing-key)"
                if self.building_source == "vworld"
                else "synthetic-demo"
            ),
            "database": "postgresql(configured)" if self.database_configured else "not configured",
            "auth": "kakao(configured)" if self.kakao_login_configured else "not configured",
        }


settings = Settings()
