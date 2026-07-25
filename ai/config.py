"""
AI 파이프라인 환경설정. API 키는 ai/.env 또는 환경변수에서만 읽는다.
ODsay/TMAP 키가 없으면 해당 수집기는 명시적으로 미설정 상태를 반환한다.
OSMnx 보행 네트워크 보완은 느린 외부 네트워크 작업이므로 명시적으로
활성화한 환경에서만 동작한다.
"""
from pathlib import Path
from typing import Literal

from pydantic import AnyHttpUrl, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

_ENV_FILE = Path(__file__).resolve().parent / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=_ENV_FILE, env_file_encoding="utf-8", env_ignore_empty=True, extra="ignore"
    )

    ODSAY_API_KEY: str = ""
    ODSAY_CACHE_DIR: str = ""
    ODSAY_CACHE_TTL_SECONDS: int = Field(
        default=1800,
        ge=60,
        le=31_536_000,
    )
    ODSAY_TIMEOUT_SECONDS: int = Field(default=20, ge=5, le=600)
    # 일반 서비스는 ODsay loadLane 정밀 선형을 유지한다. 오프라인 보행망을
    # 쓰는 배치 수집은 정류장 연결선을 estimated로 기록하는 모드를 선택할 수 있다.
    ODSAY_LOAD_LANE_ENABLED: bool = True
    ELEVATION_CACHE_DIR: str = ""
    ELEVATION_CACHE_TTL_SECONDS: int = Field(
        default=2_592_000,
        ge=3600,
        le=31_536_000,
    )
    # 비어 있으면 Open-Meteo API를 사용한다. 배포 환경은 공개 GLO-90 COG를
    # 한 번만 내려받아 재사용할 수 있는 영속 캐시 경로를 지정한다.
    ELEVATION_DEM_DIR: str = ""
    TMAP_API_KEY: str = ""
    OSMNX_WALK_GEOMETRY_ENABLED: bool = False
    # 일반 요청은 캐시 누락 시 백그라운드 준비 후 즉시 estimated를 반환한다.
    # 장시간 학습 수집 전용 컨테이너만 동기 준비를 명시적으로 선택한다.
    OSMNX_WALK_GEOMETRY_BLOCKING: bool = False
    OSMNX_OVERPASS_URL: AnyHttpUrl = "https://lambert.openstreetmap.de/api"
    OSMNX_REQUEST_TIMEOUT_SECONDS: int = Field(default=12, ge=3, le=60)
    OSMNX_WALK_GEOMETRY_TIMEOUT_SECONDS: int = Field(default=15, ge=3, le=60)
    # 초기 평가 baseline은 명시적으로 선택한 환경에서만 제공한다.
    # 기본값은 실제 사용자 라벨로 검증된 운영 모델이다.
    RANKER_TIER: Literal[
        "human_validated",
        "bootstrap_baseline",
    ] = "human_validated"


settings = Settings()
