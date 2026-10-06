"""근거 조회 클라이언트. backend 내부 API 와 ai-engine 검색 API(api-spec 10장)를 읽는다.

실패는 SourceUnavailable 하나로 모은다. 어느 정보원을 빼고 진행할지는 context.py 가 정한다.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import quote

import httpx

_SECRET_HEADER = "X-Internal-Secret"


class SourceUnavailable(Exception):
    def __init__(self, source: str, reason: str) -> None:
        super().__init__(f"{source}: {reason}")
        self.source = source
        self.reason = reason


async def _send(
    http: httpx.AsyncClient,
    source: str,
    method: str,
    url: str,
    *,
    allow_not_found: bool = False,
    **kwargs: Any,
) -> dict[str, Any] | None:
    try:
        response = await http.request(method, url, **kwargs)
    except httpx.HTTPError as exc:
        raise SourceUnavailable(source, type(exc).__name__) from exc
    if response.status_code == 404 and allow_not_found:
        return None
    if response.status_code != 200:
        raise SourceUnavailable(source, f"http_{response.status_code}")
    try:
        return response.json()
    except ValueError as exc:
        raise SourceUnavailable(source, "invalid_json") from exc


class BackendClient:
    def __init__(self, http: httpx.AsyncClient, *, base_url: str, secret: str) -> None:
        self._http = http
        self._base_url = base_url.rstrip("/")
        self._headers = {_SECRET_HEADER: secret}

    async def segments(self, *, call_id: str, until_sequence: int) -> dict[str, Any] | None:
        url = f"{self._base_url}/api/v1/internal/assistant/calls/{quote(call_id, safe='')}/segments"
        return await _send(self._http, "segments", "GET", url, allow_not_found=True,
                           params={"until_sequence": until_sequence}, headers=self._headers)

    async def estimates(self, *, ticker: str, as_of_epoch: int) -> dict[str, Any] | None:
        url = f"{self._base_url}/api/v1/internal/assistant/stocks/{quote(ticker, safe='')}/estimates"
        return await _send(self._http, "estimates", "GET", url, allow_not_found=True,
                           params={"as_of_epoch": as_of_epoch}, headers=self._headers)

    async def glossary(self) -> dict[str, Any]:
        url = f"{self._base_url}/api/v1/internal/assistant/glossary"
        return await _send(self._http, "glossary", "GET", url, headers=self._headers)


class AiEngineClient:
    """ai-engine 은 127.0.0.1 에만 바인딩되어 있어 별도 인증 헤더가 없다."""

    def __init__(self, http: httpx.AsyncClient, *, base_url: str) -> None:
        self._http = http
        self._base_url = base_url.rstrip("/")

    async def news_search(
        self, *, ticker: str, query: str, as_of_epoch: int, lookback_days: int, top_k: int
    ) -> dict[str, Any]:
        url = f"{self._base_url}/v1/engine/assistant/news-search"
        body = {"ticker": ticker, "query": query, "as_of_epoch": as_of_epoch,
                "lookback_days": lookback_days, "top_k": top_k}
        return await _send(self._http, "news", "POST", url, json=body)

    async def prior_call_statements(self, *, ticker: str, before_epoch: int) -> dict[str, Any]:
        url = f"{self._base_url}/v1/engine/assistant/prior-call-statements"
        return await _send(self._http, "prior_call", "GET", url,
                           params={"ticker": ticker, "before_epoch": before_epoch})
