"""logothea-assistant 환경 설정. 값은 환경변수 또는 logothea-assistant/.env 에서 읽는다."""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    openai_api_key: str = ""
    assistant_model: str = "gpt-6-luna"
    # gpt-6-luna 는 추론 강도 기본값이 medium 이라, 지정하지 않으면 추론 토큰 과금과 첫 토큰 지연이 늘어난다.
    classify_reasoning_effort: str = "none"
    generate_reasoning_effort: str = "none"
    openai_timeout_seconds: float = 30.0

    # backend 의 INTERNAL_SECRET 과 같은 값. backend → assistant 요청 확인과 assistant → backend 내부 API 호출에 함께 쓴다.
    internal_secret: str = ""
    backend_base_url: str = "http://127.0.0.1:8082"
    ai_engine_base_url: str = "http://127.0.0.1:8000"

    context_timeout_seconds: float = 3.0
    news_top_k: int = 6
    news_lookback_days: int = 30


@lru_cache
def get_settings() -> Settings:
    return Settings()
