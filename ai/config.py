"""
AI 파이프라인 환경설정. API 키는 ai/.env 또는 환경변수에서만 읽는다.
ODsay/TMAP 키가 없으면 해당 수집기는 명시적으로 미설정 상태를 반환한다.
OSMnx 보행 네트워크 보완은 느린 외부 네트워크 작업이므로 명시적으로
활성화한 환경에서만 동작한다.
"""
from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

_ENV_FILE = Path(__file__).resolve().parent / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=_ENV_FILE, env_file_encoding="utf-8", env_ignore_empty=True, extra="ignore"
    )

    ODSAY_API_KEY: str = ""
    TMAP_API_KEY: str = ""
    OSMNX_WALK_GEOMETRY_ENABLED: bool = False
    # Judge baseline은 명시적으로 선택한 환경에서만 제공한다.
    # 기본값은 실제 사용자 라벨로 검증된 운영 모델이다.
    RANKER_TIER: Literal["human_validated", "judge_baseline"] = "human_validated"


settings = Settings()
