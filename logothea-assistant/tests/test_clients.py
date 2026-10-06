import json

import httpx
import pytest

from assistant.clients import AiEngineClient, BackendClient, SourceUnavailable


def _http(handler):
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def test_segments_sends_secret_and_encoded_call_id():
    seen = {}

    def handler(request):
        seen["url"] = str(request.url)
        seen["secret"] = request.headers.get("X-Internal-Secret")
        return httpx.Response(200, json={"call_id": "a/b", "last_sequence": 5, "segments": []})

    async with _http(handler) as http:
        body = await BackendClient(http, base_url="http://backend:8082/", secret="s3cret").segments(
            call_id="a/b", until_sequence=5)

    assert body["last_sequence"] == 5
    assert seen["url"] == "http://backend:8082/api/v1/internal/assistant/calls/a%2Fb/segments?until_sequence=5"
    assert seen["secret"] == "s3cret"


async def test_segments_and_estimates_return_none_on_404():
    async with _http(lambda request: httpx.Response(404, json={"error": "x"})) as http:
        client = BackendClient(http, base_url="http://backend", secret="s")
        assert await client.segments(call_id="c1", until_sequence=1) is None
        assert await client.estimates(ticker="ZZZ", as_of_epoch=1) is None


async def test_estimates_query_params():
    seen = {}

    def handler(request):
        seen["url"] = str(request.url)
        return httpx.Response(200, json={"ticker": "WMT"})

    async with _http(handler) as http:
        await BackendClient(http, base_url="http://backend", secret="s").estimates(ticker="WMT", as_of_epoch=1787227218)
    assert seen["url"] == "http://backend/api/v1/internal/assistant/stocks/WMT/estimates?as_of_epoch=1787227218"


async def test_glossary_404_is_unavailable():
    async with _http(lambda request: httpx.Response(404)) as http:
        with pytest.raises(SourceUnavailable) as error:
            await BackendClient(http, base_url="http://backend", secret="s").glossary()
    assert error.value.source == "glossary"
    assert error.value.reason == "http_404"


@pytest.mark.parametrize(
    ("handler", "reason"),
    [
        (lambda request: httpx.Response(500), "http_500"),
        (lambda request: httpx.Response(401), "http_401"),
        (lambda request: httpx.Response(200, content=b"<html>"), "invalid_json"),
    ],
)
async def test_backend_failures_raise_source_unavailable(handler, reason):
    async with _http(handler) as http:
        with pytest.raises(SourceUnavailable) as error:
            await BackendClient(http, base_url="http://backend", secret="s").segments(call_id="c1", until_sequence=1)
    assert error.value.source == "segments"
    assert error.value.reason == reason


async def test_network_error_raises_source_unavailable():
    def handler(request):
        raise httpx.ConnectError("refused", request=request)

    async with _http(handler) as http:
        with pytest.raises(SourceUnavailable) as error:
            await AiEngineClient(http, base_url="http://engine").prior_call_statements(ticker="WMT", before_epoch=1)
    assert error.value.source == "prior_call"
    assert error.value.reason == "ConnectError"


async def test_news_search_posts_json_body():
    seen = {}

    def handler(request):
        seen["method"] = request.method
        seen["url"] = str(request.url)
        seen["body"] = json.loads(request.content)
        seen["secret"] = request.headers.get("X-Internal-Secret")
        return httpx.Response(200, json={"hits": [], "warnings": []})

    async with _http(handler) as http:
        await AiEngineClient(http, base_url="http://engine").news_search(
            ticker="WMT", query="guidance", as_of_epoch=1787227218, lookback_days=30, top_k=6)

    assert seen["method"] == "POST"
    assert seen["url"] == "http://engine/v1/engine/assistant/news-search"
    assert seen["body"] == {"ticker": "WMT", "query": "guidance", "as_of_epoch": 1787227218,
                            "lookback_days": 30, "top_k": 6}
    assert seen["secret"] is None


async def test_prior_call_statements_query_params():
    seen = {}

    def handler(request):
        seen["url"] = str(request.url)
        return httpx.Response(200, json={"available": False, "warnings": ["prior_call_not_found"]})

    async with _http(handler) as http:
        body = await AiEngineClient(http, base_url="http://engine").prior_call_statements(ticker="WMT", before_epoch=100)
    assert body["available"] is False
    assert seen["url"] == "http://engine/v1/engine/assistant/prior-call-statements?ticker=WMT&before_epoch=100"
