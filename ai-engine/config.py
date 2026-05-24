from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import ConfigDict, Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
        populate_by_name=True,
    )

    app_name: str = "EarningWhisperer AI Engine"
    app_version: str = "9.5.9"
    environment: Literal["dev", "staging", "prod"] = "dev"
    log_level: str = "INFO"

    gemini_api_key: str = Field(default="", alias="GEMINI_API_KEY")
    openai_api_key: str = Field(default="", alias="OPENAI_API_KEY")
    redis_url: str = Field(default="redis://localhost:6379", alias="REDIS_URL")
    database_url: str = Field(default="postgresql://postgres:postgres@localhost:5432/earningwhisperer", alias="DATABASE_URL")
    database_connect_timeout_seconds: int = Field(default=2, alias="DATABASE_CONNECT_TIMEOUT_SECONDS")
    database_failure_cooldown_seconds: int = Field(default=15, alias="DATABASE_FAILURE_COOLDOWN_SECONDS")
    db_schema_path: str = Field(default="sql/ai_engine_event_store_schema.sql", alias="DB_SCHEMA_PATH")

    openai_model_fast: str = Field(default="gpt-5-mini", alias="OPENAI_MODEL_FAST")
    gemini_model_fast: str = Field(default="gemini-3.1-flash-lite", alias="GEMINI_MODEL_FAST")

    gemini_primary_model: str | None = Field(default="gemini-3.1-flash-lite", alias="GEMINI_PRIMARY_MODEL")
    gemini_review_model: str | None = Field(default="gemini-3.1-pro-preview", alias="GEMINI_REVIEW_MODEL")
    gemini_review_model_candidates: str = Field(
        default="gemini-3.1-pro-preview,gemini-3-flash-preview,gemini-3.1-flash-lite,gemini-2.5-pro",
        alias="GEMINI_REVIEW_MODEL_CANDIDATES",
    )
    enable_review_pass: bool = Field(default=True, alias="ENABLE_REVIEW_PASS")

    # legacy aliases still accepted
    gemini_fast_model: str | None = None
    gemini_model: str | None = None

    gemini_primary_max_output_tokens: int = Field(default=384, alias="GEMINI_PRIMARY_MAX_OUTPUT_TOKENS")
    gemini_standard_max_output_tokens: int = Field(default=640, alias="GEMINI_STANDARD_MAX_OUTPUT_TOKENS")
    gemini_review_max_output_tokens: int = Field(default=960, alias="GEMINI_REVIEW_MAX_OUTPUT_TOKENS")
    analysis_prompt_budget_economy: int = Field(default=384, alias="ANALYSIS_PROMPT_BUDGET_ECONOMY")
    analysis_prompt_budget_standard: int = Field(default=640, alias="ANALYSIS_PROMPT_BUDGET_STANDARD")
    analysis_prompt_budget_review: int = Field(default=960, alias="ANALYSIS_PROMPT_BUDGET_REVIEW")
    gemini_primary_thinking_level: str = Field(default="minimal", alias="GEMINI_PRIMARY_THINKING_LEVEL")
    gemini_standard_thinking_level: str = Field(default="low", alias="GEMINI_STANDARD_THINKING_LEVEL")
    gemini_review_thinking_level: str = Field(default="medium", alias="GEMINI_REVIEW_THINKING_LEVEL")
    gemini_response_mime_type: str = "application/json"
    gemini_temperature: float = Field(default=0.15, alias="GEMINI_TEMPERATURE")
    gemini_max_tokens: int = Field(default=2048, alias="GEMINI_MAX_TOKENS")
    gemini_max_retries: int = Field(default=3, alias="GEMINI_MAX_RETRIES")
    gemini_base_retry_delay: float = Field(default=1.5, alias="GEMINI_BASE_RETRY_DELAY")
    gemini_consensus_samples: int = Field(default=3, alias="GEMINI_CONSENSUS_SAMPLES")
    gemini_consensus_min_confidence: float = Field(default=0.78, alias="GEMINI_CONSENSUS_MIN_CONFIDENCE")
    gemini_consensus_disagreement_threshold: float = Field(default=0.35, alias="GEMINI_CONSENSUS_DISAGREEMENT_THRESHOLD")
    gemini_response_cache_enabled: bool = True
    gemini_response_cache_max_entries: int = 256
    llm_cost_primary_input_per_million: float = Field(default=0.0, alias="LLM_COST_PRIMARY_INPUT_PER_MILLION")
    llm_cost_primary_output_per_million: float = Field(default=0.0, alias="LLM_COST_PRIMARY_OUTPUT_PER_MILLION")
    llm_cost_review_input_per_million: float = Field(default=0.0, alias="LLM_COST_REVIEW_INPUT_PER_MILLION")
    llm_cost_review_output_per_million: float = Field(default=0.0, alias="LLM_COST_REVIEW_OUTPUT_PER_MILLION")

    llm_router_max_calls_per_chunk: int = Field(default=2, alias="LLM_ROUTER_MAX_CALLS_PER_CHUNK")
    llm_router_novelty_threshold: float = Field(default=0.18, alias="LLM_ROUTER_NOVELTY_THRESHOLD")
    llm_router_high_signal_raw_threshold: float = Field(default=0.45, alias="LLM_ROUTER_HIGH_SIGNAL_RAW_THRESHOLD")
    llm_router_high_priority: int = Field(default=8, alias="LLM_ROUTER_HIGH_PRIORITY")
    llm_router_review_confidence_threshold: float = Field(default=0.68, alias="LLM_ROUTER_REVIEW_CONFIDENCE_THRESHOLD")

    phase1_provider: Literal["finbert", "mock"] = Field(default="finbert", alias="PHASE1_PROVIDER")
    phase1_finbert_model_name: str = Field(default="ProsusAI/finbert", alias="PHASE1_FINBERT_MODEL_NAME")
    phase1_finbert_device: str = Field(default="auto", alias="PHASE1_FINBERT_DEVICE")
    phase1_finbert_max_length: int = Field(default=256, alias="PHASE1_FINBERT_MAX_LENGTH")
    phase1_max_chars: int = Field(default=3000, alias="PHASE1_MAX_CHARS")
    phase1_cache_size: int = Field(default=1024, alias="PHASE1_CACHE_SIZE")
    phase1_warmup_on_startup: bool = Field(default=True, alias="PHASE1_WARMUP_ON_STARTUP")

    composite_threshold: float = Field(default=0.45, alias="COMPOSITE_THRESHOLD")
    confidence_threshold: float = Field(default=0.70, alias="CONFIDENCE_THRESHOLD")
    raw_score_threshold: float = Field(default=0.35, alias="RAW_SCORE_THRESHOLD")
    max_euphemism_count: int = Field(default=3, alias="MAX_EUPHEMISM_COUNT")
    min_volume_ratio: float = Field(default=1.50, alias="MIN_VOLUME_RATIO")
    max_vix: float = Field(default=28.0, alias="MAX_VIX")
    kelly_max_position: float = Field(default=0.12, alias="KELLY_MAX_POSITION")
    execution_target_win_rate: float = Field(default=0.50, alias="EXECUTION_TARGET_WIN_RATE")
    backtest_round_trip_cost_pct: float = Field(default=0.30, alias="BACKTEST_ROUND_TRIP_COST_PCT")
    slippage_bps_default: float = Field(default=8.0, alias="SLIPPAGE_BPS_DEFAULT")
    execution_latency_bps_default: float = Field(default=5.0, alias="EXECUTION_LATENCY_BPS_DEFAULT")
    conservative_execution_cost_limit_pct: float = Field(default=0.55, alias="CONSERVATIVE_EXECUTION_COST_LIMIT_PCT")

    w_sentiment: float = Field(default=0.28, alias="W_SENTIMENT")
    w_sue: float = Field(default=0.22, alias="W_SUE")
    w_momentum: float = Field(default=0.18, alias="W_MOMENTUM")
    w_volume: float = Field(default=0.10, alias="W_VOLUME")
    w_gap: float = Field(default=0.08, alias="W_GAP")
    w_reversal: float = Field(default=0.08, alias="W_REVERSAL")
    w_short_interest: float = Field(default=0.06, alias="W_SHORT_INTEREST")

    whisper_play_horizon_days: int = 2
    short_squeeze_horizon_days: int = 3
    pead_horizon_days: int = 5
    iv_crush_horizon_days: int = 2
    reversal_catalyst_horizon_days: int = 2
    gap_and_go_horizon_days: int = 2
    gap_fill_horizon_days: int = 2
    news_breakout_horizon_days: int = 3
    momentum_carry_horizon_days: int = 4

    yfinance_timeout_seconds: float = Field(default=10.0, alias="YFINANCE_TIMEOUT_SECONDS")
    yfinance_repair_enabled: bool = Field(default=True, alias="YFINANCE_REPAIR_ENABLED")
    yfinance_auto_adjust: bool = Field(default=False, alias="YFINANCE_AUTO_ADJUST")
    yfinance_cache_ttl_seconds: int = Field(default=300, alias="YFINANCE_CACHE_TTL_SECONDS")
    yfinance_news_limit: int = Field(default=8, alias="YFINANCE_NEWS_LIMIT")
    alphavantage_api_key: str = Field(default="demo", alias="ALPHAVANTAGE_API_KEY")

    rag_enabled: bool = Field(default=True, alias="RAG_ENABLED")
    rag_top_k: int = Field(default=5, alias="RAG_TOP_K")
    rag_min_relevance_score: float = Field(default=0.05, alias="RAG_MIN_RELEVANCE_SCORE")
    rag_bm25_k1: float = Field(default=1.2, alias="RAG_BM25_K1")
    rag_bm25_b: float = Field(default=0.75, alias="RAG_BM25_B")
    rag_score_dense_weight: float = Field(default=0.35, alias="RAG_SCORE_DENSE_WEIGHT")
    rag_score_lexical_weight: float = Field(default=0.45, alias="RAG_SCORE_LEXICAL_WEIGHT")
    rag_score_business_weight: float = Field(default=0.20, alias="RAG_SCORE_BUSINESS_WEIGHT")
    rag_external_default_lookback_days: int = Field(default=30, alias="RAG_EXTERNAL_DEFAULT_LOOKBACK_DAYS")
    rag_external_max_lookback_days: int = Field(default=365, alias="RAG_EXTERNAL_MAX_LOOKBACK_DAYS")
    rag_max_rewrites: int = Field(default=1, alias="RAG_MAX_REWRITES")
    vector_store_backend: str = Field(default="memory", alias="VECTOR_STORE_BACKEND")
    qdrant_url: str = Field(default="", alias="QDRANT_URL")
    qdrant_path: str = Field(default="", alias="QDRANT_PATH")
    qdrant_collection_name: str = Field(default="earningwhisperer_evidence", alias="QDRANT_COLLECTION_NAME")
    embedding_provider: str = Field(default="hash", alias="EMBEDDING_PROVIDER")
    embedding_model: str = Field(default="text-embedding-3-small", alias="EMBEDDING_MODEL")
    embedding_dimension: int = Field(default=256, alias="EMBEDDING_DIMENSION")
    external_chunk_size_chars: int = Field(default=1200, alias="EXTERNAL_CHUNK_SIZE_CHARS")
    external_chunk_overlap_chars: int = Field(default=160, alias="EXTERNAL_CHUNK_OVERLAP_CHARS")
    external_evidence_retention_days: int = Field(default=365, alias="EXTERNAL_EVIDENCE_RETENTION_DAYS")

    redis_channel: str = Field(default="trading-signals", alias="REDIS_CHANNEL")
    redis_enriched_channel: str = Field(default="trading-signals-enriched", alias="REDIS_ENRICHED_CHANNEL")
    legacy_redis_publish_enabled: bool = Field(default=True, alias="LEGACY_REDIS_PUBLISH_ENABLED")
    redis_enriched_publish_enabled: bool = Field(default=True, alias="REDIS_ENRICHED_PUBLISH_ENABLED")
    redis_backup_queue_size: int = Field(default=100, alias="REDIS_BACKUP_QUEUE_SIZE")
    redis_reconnect_delay: float = Field(default=2.0, alias="REDIS_RECONNECT_DELAY")
    redis_socket_timeout_seconds: float = Field(default=1.0, alias="REDIS_SOCKET_TIMEOUT_SECONDS")

    app_host: str = Field(default="0.0.0.0", alias="APP_HOST")
    app_port: int = Field(default=8000, alias="APP_PORT")

    discord_webhook_url: str = Field(default="", alias="DISCORD_WEBHOOK_URL")
    telegram_bot_token: str = Field(default="", alias="TELEGRAM_BOT_TOKEN")
    telegram_chat_id: str = Field(default="", alias="TELEGRAM_CHAT_ID")
    notification_tier: Literal["free", "premium"] = Field(default="free", alias="NOTIFICATION_TIER")
    notification_free_delay_seconds: int = Field(default=300, alias="NOTIFICATION_FREE_DELAY_SECONDS")

    scorecard_enabled: bool = Field(default=True, alias="SCORECARD_ENABLED")
    scorecard_store_path: str = Field(default="data/scorecard.json", alias="SCORECARD_STORE_PATH")

    portfolio_store_path: str = Field(default="data/portfolio_snapshot.json", alias="PORTFOLIO_STORE_PATH")
    portfolio_intraday_refresh_enabled: bool = Field(default=False, alias="PORTFOLIO_INTRADAY_REFRESH_ENABLED")
    portfolio_intraday_refresh_interval_minutes: int = Field(default=10, alias="PORTFOLIO_INTRADAY_REFRESH_INTERVAL_MINUTES")
    portfolio_kis_mock_payload_path: str = Field(default="", alias="PORTFOLIO_KIS_MOCK_PAYLOAD_PATH")
    portfolio_kis_positions_url: str = Field(default="", alias="PORTFOLIO_KIS_POSITIONS_URL")
    kis_account_number: str = Field(default="", alias="KIS_ACCOUNT_NUMBER")
    kis_app_key: str = Field(default="", alias="KIS_APP_KEY")
    kis_app_secret: str = Field(default="", alias="KIS_APP_SECRET")

    options_advisor_enabled: bool = Field(default=True, alias="OPTIONS_ADVISOR_ENABLED")
    options_iv_rank_high_threshold: float = Field(default=60.0, alias="OPTIONS_IV_RANK_HIGH_THRESHOLD")
    options_iv_rank_low_threshold: float = Field(default=30.0, alias="OPTIONS_IV_RANK_LOW_THRESHOLD")

    mdd_circuit_breaker_enabled: bool = Field(default=True, alias="MDD_CIRCUIT_BREAKER_ENABLED")
    mdd_warning_threshold: float = Field(default=-0.10, alias="MDD_WARNING_THRESHOLD")
    mdd_pause_threshold: float = Field(default=-0.15, alias="MDD_PAUSE_THRESHOLD")
    mdd_liquidate_threshold: float = Field(default=-0.25, alias="MDD_LIQUIDATE_THRESHOLD")
    mdd_recovery_grace_days: int = Field(default=3, alias="MDD_RECOVERY_GRACE_DAYS")

    evasion_score_max: float = Field(default=0.40, alias="EVASION_SCORE_MAX")
    prosody_min_confidence: float = Field(default=0.55, alias="PROSODY_MIN_CONFIDENCE")
    call_quality_min_score: float = Field(default=0.45, alias="CALL_QUALITY_MIN_SCORE")

    @property
    def review_model_candidates_list(self) -> list[str]:
        return [part.strip() for part in self.gemini_review_model_candidates.split(",") if part.strip()]

    @model_validator(mode="before")
    @classmethod
    def _apply_legacy_model_mapping(cls, data):
        if isinstance(data, dict):
            has_primary = bool(data.get("gemini_primary_model") or data.get("GEMINI_PRIMARY_MODEL"))
            has_review = bool(data.get("gemini_review_model") or data.get("GEMINI_REVIEW_MODEL"))
            if not has_primary and (data.get("gemini_fast_model") or data.get("GEMINI_FAST_MODEL")):
                data["gemini_primary_model"] = data.get("gemini_fast_model") or data.get("GEMINI_FAST_MODEL")
            if not has_review and (data.get("gemini_model") or data.get("GEMINI_MODEL")):
                data["gemini_review_model"] = data.get("gemini_model") or data.get("GEMINI_MODEL")
        return data

    @model_validator(mode="after")
    def _validate_thresholds(self) -> "Settings":
        if not (0 <= self.composite_threshold <= 1):
            raise ValueError("COMPOSITE_THRESHOLD must be between 0 and 1")
        if not (0 <= self.confidence_threshold <= 1):
            raise ValueError("CONFIDENCE_THRESHOLD must be between 0 and 1")
        if self.llm_router_max_calls_per_chunk < 1:
            raise ValueError("LLM_ROUTER_MAX_CALLS_PER_CHUNK must be >= 1")
        if not (self.mdd_warning_threshold > self.mdd_pause_threshold > self.mdd_liquidate_threshold):
            raise ValueError("MDD thresholds must be descending in severity")
        return self


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
