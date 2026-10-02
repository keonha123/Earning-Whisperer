from __future__ import annotations

from collections import Counter
import logging
import time
from typing import Any, Callable

import httpx


logger = logging.getLogger(__name__)


FetchHtml = Callable[[str], str | None]
ExtractText = Callable[[str, str], str | None]


class ArticleTextExtractor:
    """Fetch article URLs and attach trafilatura-extracted full text to news items."""

    def __init__(
        self,
        *,
        timeout_seconds: float = 10.0,
        user_agent: str = "EarningWhispererNewsCollector/0.1",
        fetch_html: FetchHtml | None = None,
        extract_text: ExtractText | None = None,
    ) -> None:
        self.timeout_seconds = max(1.0, float(timeout_seconds))
        self.user_agent = user_agent.strip() or "EarningWhispererNewsCollector/0.1"
        self._fetch_html = fetch_html or self._default_fetch_html
        self._extract_text = extract_text or self._default_extract_text

    def enrich_items(self, items: list[dict[str, Any]]) -> dict[str, int]:
        counts: Counter[str] = Counter()
        for item in items:
            status = self.enrich_item(item)
            counts[status] += 1
        return dict(counts)

    def enrich_item(self, item: dict[str, Any]) -> str:
        metadata = dict(item.get("metadata") or {})
        item["metadata"] = metadata
        url = str(item.get("url") or "").strip()
        if not url:
            return self._mark(item, status="skipped_no_url", content="")

        try:
            html = self._fetch_html(url)
        except Exception as exc:
            logger.debug("Failed to fetch article URL %s: %s", url, exc)
            return self._mark(item, status="fetch_error", content="")
        if not html:
            return self._mark(item, status="fetch_error", content="")

        try:
            content = self._extract_text(html, url)
        except Exception as exc:
            logger.debug("Failed to extract article text from %s: %s", url, exc)
            return self._mark(item, status="extract_error", content="")
        if not content or not content.strip():
            return self._mark(item, status="empty", content="")
        return self._mark(item, status="success", content=" ".join(content.split()))

    def _mark(self, item: dict[str, Any], *, status: str, content: str) -> str:
        item["content"] = content
        metadata = dict(item.get("metadata") or {})
        metadata["content_extraction_status"] = status
        metadata["content_length"] = len(content)
        metadata["content_fetched_at"] = int(time.time())
        item["metadata"] = metadata
        return status

    def _default_fetch_html(self, url: str) -> str | None:
        headers = {"User-Agent": self.user_agent}
        with httpx.Client(timeout=self.timeout_seconds, follow_redirects=True, headers=headers) as client:
            response = client.get(url)
            response.raise_for_status()
            return response.text

    @staticmethod
    def _default_extract_text(html: str, url: str) -> str | None:
        try:
            from trafilatura import extract
        except ImportError as exc:  # pragma: no cover - dependency guard
            raise RuntimeError("trafilatura is required for full-text news extraction") from exc
        return extract(
            html,
            url=url,
            include_comments=False,
            include_tables=False,
            favor_precision=True,
        )


__all__ = ["ArticleTextExtractor"]
