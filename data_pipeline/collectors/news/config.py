from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover - optional local dependency
    load_dotenv = None


M7_TICKERS = ["AAPL", "MSFT", "NVDA", "AMZN", "META", "GOOGL", "TSLA"]
DATA_PIPELINE_ROOT = Path(__file__).resolve().parents[2]


def _load_env() -> None:
    if load_dotenv is not None:
        load_dotenv()


def _parse_tickers(raw: str | None) -> list[str]:
    if not raw:
        return list(M7_TICKERS)
    tickers = [ticker.strip().upper() for ticker in raw.split(",") if ticker.strip()]
    return tickers or list(M7_TICKERS)


def _int_env(name: str, default: int, *, minimum: int = 1) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except ValueError:
        value = default
    return max(minimum, value)


@dataclass(frozen=True)
class NewsCollectorSettings:
    finnhub_api_key: str
    ai_engine_url: str
    tickers: list[str]
    lookback_days: int
    interval_minutes: int
    state_path: Path
    request_timeout_seconds: float


def get_news_settings() -> NewsCollectorSettings:
    _load_env()
    state_path = Path(
        os.getenv(
            "FINNHUB_NEWS_STATE_PATH",
            str(DATA_PIPELINE_ROOT / ".state" / "finnhub_news_seen.json"),
        )
    )
    return NewsCollectorSettings(
        finnhub_api_key=os.getenv("FINNHUB_API_KEY", "").strip(),
        ai_engine_url=os.getenv("AI_ENGINE_URL", "http://localhost:8000").rstrip("/"),
        tickers=_parse_tickers(os.getenv("FINNHUB_NEWS_TICKERS")),
        lookback_days=_int_env("FINNHUB_NEWS_LOOKBACK_DAYS", 1),
        interval_minutes=_int_env("FINNHUB_NEWS_INTERVAL_MINUTES", 10),
        state_path=state_path,
        request_timeout_seconds=float(os.getenv("FINNHUB_NEWS_TIMEOUT_SECONDS", "30")),
    )
