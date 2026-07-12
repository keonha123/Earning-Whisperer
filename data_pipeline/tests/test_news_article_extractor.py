from __future__ import annotations

import sys
from pathlib import Path


DATA_PIPELINE_ROOT = Path(__file__).resolve().parents[1]
if str(DATA_PIPELINE_ROOT) not in sys.path:
    sys.path.insert(0, str(DATA_PIPELINE_ROOT))

from collectors.news.article_extractor import ArticleTextExtractor


def test_article_extractor_adds_content_and_success_metadata() -> None:
    item = {"url": "https://example.test/article", "metadata": {"category": "company news"}}
    extractor = ArticleTextExtractor(
        fetch_html=lambda url: "<html><article>NVIDIA full article body.</article></html>",
        extract_text=lambda html, url: "NVIDIA full article body.",
    )

    stats = extractor.enrich_items([item])

    assert stats == {"success": 1}
    assert item["content"] == "NVIDIA full article body."
    assert item["metadata"]["content_extraction_status"] == "success"
    assert item["metadata"]["content_length"] == len("NVIDIA full article body.")
    assert "content_fetched_at" in item["metadata"]
    assert "content_extractor" not in item["metadata"]


def test_article_extractor_skips_missing_url() -> None:
    item = {"url": "", "metadata": {}}
    extractor = ArticleTextExtractor(fetch_html=lambda url: "unused", extract_text=lambda html, url: "unused")

    status = extractor.enrich_item(item)

    assert status == "skipped_no_url"
    assert item["content"] == ""
    assert item["metadata"]["content_extraction_status"] == "skipped_no_url"


def test_article_extractor_keeps_item_on_fetch_error() -> None:
    def _raise_fetch(url: str) -> str:
        raise RuntimeError("network failed")

    item = {"url": "https://example.test/article", "metadata": {}}
    extractor = ArticleTextExtractor(fetch_html=_raise_fetch, extract_text=lambda html, url: "unused")

    status = extractor.enrich_item(item)

    assert status == "fetch_error"
    assert item["content"] == ""
    assert item["metadata"]["content_extraction_status"] == "fetch_error"


def test_article_extractor_records_empty_extraction() -> None:
    item = {"url": "https://example.test/article", "metadata": {}}
    extractor = ArticleTextExtractor(fetch_html=lambda url: "<html></html>", extract_text=lambda html, url: None)

    status = extractor.enrich_item(item)

    assert status == "empty"
    assert item["content"] == ""
    assert item["metadata"]["content_extraction_status"] == "empty"
