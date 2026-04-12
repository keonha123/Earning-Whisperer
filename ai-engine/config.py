"""Runtime configuration for the EarningWhisperer AI engine."""

from __future__ import annotations

from functools import lru_cache
import warnings
from typing import Literal

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Environment-driven settings with safe local defaults."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    gemini_api_key: str = Field(default="")

    # Legacy model settings kept for compatibility with older env files.
    gemini_model: str | None = Field(default=None)
    gemini_fast_model: str | None = Field(default=None)
    gemini_consensus_model: str | None = Field(default=None)

    # New Gemini 3.x routing defaults.
    gemini_primary_model: str = Field(default="gemini-3-flash-preview")
    gemini_review_model: str = Field(default="gemini-3-pro-preview")
    gemini_primary_max_output_tokens: int = Field(default=384, ge=128, le=8192)
    gemini_standard_max_output_tokens: int = Field(default=640, ge=128, le=8192)
    gemini_review_max_output_tokens: int = Field(default=960, ge=128, le=8192)
    gemini_primary_thinking_level: Literal["minimal", "low", "medium", "high"] = Field(
        default="minimal"
    )
    gemini_standard_thinking_level: Literal["minimal", "low", "medium", "high"] = Field(
        default="low"
    )
    gemini_review_thinking_level: Literal["minimal", "low", "medium", "high"] = Field(
        default="medium"
    )
    gemini_max_tokens: int = Field(default=2048, ge=512, le=8192)
    gemini_thinking_level: Literal["minimal", "low", "medium", "high"] = Field(
        default="minimal"
    )
    gemini_max_retries: int = Field(default=3, ge=1, le=5)
    gemini_base_retry_delay: float = Field(default=1.5, ge=0.5, le=5.0)
    gemini_response_mime_type: str = Field(default="application/json")
    gemini_consensus_samples: int = Field(default=3, ge=1, le=7)
    gemini_consensus_min_confidence: float = Field(default=0.78, ge=0.0, le=1.0)
    gemini_consensus_disagreement_threshold: float = Field(default=0.35, ge=0.0, le=1.0)

    llm_router_max_calls_per_chunk: int = Field(default=6, ge=1, le=6)
    llm_router_novelty_threshold: float = Field(default=0.18, ge=0.0, le=1.0)
    llm_router_high_signal_raw_threshold: float = Field(default=0.45, ge=0.0, le=1.0)
    llm_router_high_priority: int = Field(default=8, ge=1, le=10)
    llm_router_review_confidence_threshold: float = Field(default=0.68, ge=0.0, le=1.0)

    phase1_provider: Literal["finbert", "lexical"] = Field(default="finbert")
    phase1_finbert_model_name: str = Field(default="ProsusAI/finbert")
    phase1_finbert_device: Literal["auto", "cpu", "cuda"] = Field(default="auto")
    phase1_finbert_max_length: int = Field(default=256, ge=64, le=512)
    phase1_max_chars: int = Field(default=3000, ge=256, le=12000)
    phase1_cache_size: int = Field(default=1024, ge=64, le=10000)
    phase1_warmup_on_startup: bool = Field(default=True)

    alphavantage_api_key: str = Field(default="demo")

    redis_url: str = Field(default="redis://localhost:6379")
    redis_channel: str = Field(default="trading-signals")
    redis_enriched_channel: str = Field(default="trading-signals-enriched")
    redis_backup_queue_size: int = Field(default=100, ge=10, le=1000)
    redis_reconnect_delay: float = Field(default=2.0, ge=0.5, le=30.0)

    app_host: str = Field(default="0.0.0.0")
    app_port: int = Field(default=8000, ge=1024, le=65535)
    app_version: str = Field(default="3.5.2")
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = Field(default="INFO")

    context_history_size: int = Field(default=5, ge=1, le=20)
    context_session_ttl_seconds: int = Field(default=3600, ge=300)
    analysis_max_prompt_tokens: int = Field(default=12000, ge=1024, le=128000)
    analysis_target_chunk_tokens: int = Field(default=2500, ge=256, le=16000)
    analysis_batch_concurrency: int = Field(default=4, ge=1, le=32)
    analysis_consensus_max_parallel: int = Field(default=2, ge=1, le=8)
    rag_enabled: bool = Field(default=True)
    rag_top_k: int = Field(default=3, ge=1, le=8)
    rag_max_rewrites: int = Field(default=1, ge=0, le=3)
    rag_min_relevance_score: float = Field(default=0.18, ge=0.0, le=1.0)
    rag_context_chars_per_doc: int = Field(default=320, ge=80, le=2000)
    rag_decision_max_output_tokens: int = Field(default=256, ge=64, le=1024)
    rag_decision_thinking_level: Literal["minimal", "low", "medium", "high"] = Field(
        default="minimal"
    )
    rag_external_default_lookback_days: int = Field(default=7, ge=1, le=30)
    rag_external_max_lookback_days: int = Field(default=30, ge=1, le=30)

    composite_threshold: float = Field(default=0.55, ge=0.0, le=1.0)
    confidence_threshold: float = Field(default=0.82, ge=0.0, le=1.0)
    raw_score_threshold: float = Field(default=0.45, ge=0.0, le=1.0)
    max_euphemism_count: int = Field(default=2, ge=0, le=10)
    min_volume_ratio: float = Field(default=1.80, ge=0.0, le=10.0)
    max_vix: float = Field(default=25.0, ge=10.0, le=80.0)

    kelly_max_position: float = Field(default=0.25, ge=0.01, le=0.50)
    execution_target_win_rate: float = Field(default=0.50, ge=0.0, le=1.0)

    w_sentiment: float = Field(default=0.40, ge=0.0, le=1.0)
    w_sue: float = Field(default=0.25, ge=0.0, le=1.0)
    w_momentum: float = Field(default=0.20, ge=0.0, le=1.0)
    w_volume: float = Field(default=0.15, ge=0.0, le=1.0)

    @field_validator("gemini_api_key")
    @classmethod
    def _normalize_api_key(cls, value: str) -> str:
        return (value or "").strip()

    @field_validator("gemini_consensus_samples")
    @classmethod
    def _validate_consensus_samples(cls, value: int) -> int:
        if value > 1 and value % 2 == 0:
            raise ValueError("gemini_consensus_samples must be odd")
        return value

    @model_validator(mode="after")
    def _apply_legacy_model_mapping(self) -> "Settings":
        explicitly_set = set(self.model_fields_set)

        if self.gemini_fast_model and "gemini_primary_model" not in explicitly_set:
            self.gemini_primary_model = self.gemini_fast_model
            warnings.warn(
                "GEMINI_FAST_MODEL is deprecated; prefer GEMINI_PRIMARY_MODEL.",
                DeprecationWarning,
                stacklevel=2,
            )
        if self.gemini_model and "gemini_review_model" not in explicitly_set:
            self.gemini_review_model = self.gemini_model
            warnings.warn(
                "GEMINI_MODEL is deprecated; prefer GEMINI_REVIEW_MODEL.",
                DeprecationWarning,
                stacklevel=2,
            )
        return self

    @model_validator(mode="after")
    def _validate_weights(self) -> "Settings":
        total = round(
            self.w_sentiment + self.w_sue + self.w_momentum + self.w_volume,
            6,
        )
        if abs(total - 1.0) > 1e-5:
            raise ValueError(
                "Composite weights must sum to 1.0: "
                f"{self.w_sentiment} + {self.w_sue} + "
                f"{self.w_momentum} + {self.w_volume} = {total}"
            )
        return self


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
