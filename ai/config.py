"""
AI 파이프라인 환경설정. API 키는 ai/.env 또는 환경변수에서만 읽는다.
키가 없거나 플레이스홀더("YOUR_"로 시작)이면 각 수집기가 자동으로 폴백한다.
"""
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

_ENV_FILE = Path(__file__).resolve().parent / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=_ENV_FILE, env_file_encoding="utf-8", extra="ignore"
    )

    ODSAY_API_KEY: str = ""
    TMAP_API_KEY: str = ""


settings = Settings()
