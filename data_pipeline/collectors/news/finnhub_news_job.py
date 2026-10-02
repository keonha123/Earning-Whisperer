from __future__ import annotations

import logging

from .article_extractor import ArticleTextExtractor
from .ai_engine_client import AiEngineNewsClient
from .config import get_news_settings
from .finnhub import FinnhubCompanyNewsStrategy, FinnhubRateLimitError
from .state_store import NewsStateStore


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)
logger = logging.getLogger("finnhub-news-scheduler")


def _doc_key(item: dict) -> str:
    return f"{item['provider']}:{item['ticker']}:{item['provider_id']}"


class FinnhubNewsJob:
    def __init__(self) -> None:
        self.settings = get_news_settings()
        self.collector = FinnhubCompanyNewsStrategy(
            api_key=self.settings.finnhub_api_key,
            lookback_days=self.settings.lookback_days,
            timeout_seconds=self.settings.request_timeout_seconds,
        )
        self.ai_engine = AiEngineNewsClient(
            self.settings.ai_engine_url,
            timeout_seconds=self.settings.request_timeout_seconds,
        )
        self.article_extractor = ArticleTextExtractor(
            timeout_seconds=self.settings.full_text_timeout_seconds,
            user_agent=self.settings.full_text_user_agent,
        )
        self.state = NewsStateStore(self.settings.state_path)

    def run_once(self) -> None:
        if not self.settings.finnhub_api_key:
            logger.error("FINNHUB_API_KEY is not configured; skipping news collection")
            return

        logger.info("Collecting Finnhub news for tickers=%s", ",".join(self.settings.tickers))
        try:
            collected = self.collector.collect(self.settings.tickers)
        except FinnhubRateLimitError as exc:
            logger.warning("Finnhub rate limit reached; next scheduled run will retry: %s", exc)
            return
        except Exception:
            logger.exception("Finnhub news collection failed")
            return

        new_items: list[dict] = []
        new_keys: list[str] = []
        for item in collected:
            key = _doc_key(item)
            if self.state.is_seen(key):
                continue
            new_items.append(item)
            new_keys.append(key)

        if not new_items:
            logger.info("No new Finnhub news items found")
            return

        if self.settings.full_text_enabled:
            stats = self.article_extractor.enrich_items(new_items)
            logger.info("Full-text extraction completed for %d news items: %s", len(new_items), stats)

        try:
            response = self.ai_engine.ingest_news(new_items)
        except Exception:
            logger.exception("Failed to deliver Finnhub news to ai-engine")
            return

        self.state.mark_many(new_keys)
        self.state.save()
        logger.info(
            "Delivered %d Finnhub news items to ai-engine: %s",
            len(new_items),
            response,
        )


def get_finnhub_news_interval_minutes() -> int:
    return get_news_settings().interval_minutes


def run_finnhub_news_once() -> None:
    FinnhubNewsJob().run_once()
