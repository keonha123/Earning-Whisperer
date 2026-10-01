from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Any

import httpx

from .base import NewsCollector


logger = logging.getLogger(__name__)


class FinnhubRateLimitError(RuntimeError):
    pass


class FinnhubCompanyNewsStrategy(NewsCollector):
    def __init__(
        self,
        api_key: str,
        *,
        base_url: str = "https://finnhub.io/api/v1",
        lookback_days: int = 1,
        timeout_seconds: float = 15.0,
    ) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.lookback_days = max(1, int(lookback_days))
        self.timeout_seconds = timeout_seconds

    def collect(self, tickers: list[str]) -> list[dict]:
        # 외부에서 호출하는 수집 진입점이다.
        # 여러 ticker를 순회하며 Finnhub 뉴스를 가져오고, ai-engine에 넘기기 쉬운
        # 공통 dict 형태로 정규화해서 반환한다.
        if not self.api_key:
            raise RuntimeError("FINNHUB_API_KEY is required")

        all_items: list[dict] = []
        with httpx.Client(timeout=self.timeout_seconds) as client:
            for ticker in tickers:
                try:
                    raw_items = self._fetch_ticker_news(client, ticker)
                except FinnhubRateLimitError:
                    # rate limit은 전체 job 차원에서 멈춰야 한다.
                    # 여기서 삼켜버리면 남은 ticker 호출로 제한을 더 악화시킬 수 있다.
                    raise
                except Exception as exc:
                    # 특정 ticker 하나가 실패해도 전체 M7 수집이 멈추지 않도록 건너뛴다.
                    logger.warning("Skipping %s after Finnhub news fetch failure: %s", ticker, exc)
                    continue
                all_items.extend(self._normalize_items(ticker, raw_items))
        return all_items

    def _fetch_ticker_news(self, client: httpx.Client, ticker: str) -> list[dict[str, Any]]:
        # Finnhub company-news API는 분/초 단위가 아니라 날짜 단위 from/to만 받는다.
        # 따라서 최근 N일 범위를 매번 조회하고, 중복 제거는 scheduler/state_store에서 처리한다.
        today = date.today()
        from_date = today - timedelta(days=self.lookback_days)
        response = client.get(
            f"{self.base_url}/company-news",
            params={
                "symbol": ticker,
                "from": from_date.isoformat(),
                "to": today.isoformat(),
                "token": self.api_key,
            },
        )
        if response.status_code == 429:
            # 429는 Finnhub 호출 한도 초과다. 즉시 재시도하지 않고 다음 스케줄 주기로 넘긴다.
            raise FinnhubRateLimitError("Finnhub rate limit exceeded")
        response.raise_for_status()
        payload = response.json()
        return payload if isinstance(payload, list) else []

    @staticmethod
    def _normalize_items(ticker: str, items: list[dict[str, Any]]) -> list[dict]:
        # Finnhub 원본 응답을 data-pipeline 내부 표준 뉴스 DTO로 변환한다.
        # 이 DTO는 ai-engine의 /api/v1/integration/collector/news endpoint로 그대로 전송된다.
        normalized: list[dict] = []
        for item in items:
            provider_id = item.get("id")
            headline = str(item.get("headline") or "").strip()
            summary = str(item.get("summary") or "").strip()
            url = str(item.get("url") or "").strip()
            published_at = item.get("datetime")

            if not provider_id or not headline or not published_at:
                # Qdrant 문서 id, 제목, 발행 시각을 만들 수 없는 데이터는 검색 품질이 낮고
                # 중복 제거도 어려우므로 저장 대상에서 제외한다.
                continue

            normalized.append(
                {
                    "provider": "finnhub",
                    "provider_id": str(provider_id),
                    "ticker": ticker.upper(),
                    "headline": headline,
                    "summary": summary,
                    "url": url,
                    "source": str(item.get("source") or "").strip(),
                    "published_at": int(published_at),
                    "metadata": {
                        "category": item.get("category") or "",
                        "related": item.get("related") or ticker.upper(),
                    },
                }
            )
        return normalized
