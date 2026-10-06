import asyncio
import threading
from types import SimpleNamespace

import pytest

from config import Settings
from core.gemini_client import GeminiClient, GenerationUsage


@pytest.fixture
def client(monkeypatch):
    settings = Settings(_env_file=None, GEMINI_RESPONSE_CACHE_ENABLED=False, GEMINI_BASE_RETRY_DELAY=0)
    monkeypatch.setattr("core.gemini_client.get_settings", lambda: settings)
    return GeminiClient()


class ProviderError(Exception):
    def __init__(self, code, retry_after=0):
        self.code = code
        self.response = SimpleNamespace(headers={"retry-after": str(retry_after)})
        super().__init__("untrusted provider error content")


def test_transient_error_retries_and_preserves_usage(client, monkeypatch):
    calls = []
    def provider(model, prompt, config):
        calls.append(config)
        if len(calls) == 1:
            raise ProviderError(503)
        return "{}", {"prompt_tokens": 2, "output_tokens": 3, "total_tokens": 5, "estimated_cost_usd": .01}
    monkeypatch.setattr(client, "_generate_with_modern_sdk", provider)
    result = client._generate_sync("model", "prompt", {"timeout_seconds": 4})
    assert not result.is_fallback and result.attempts == 2
    assert result.estimated_cost_usd == .01
    assert 0 < calls[1]["_attempt_timeout_seconds"] <= calls[0]["_attempt_timeout_seconds"] <= 4


@pytest.mark.parametrize("status", [400, 401, 403, 404])
def test_permanent_error_does_not_retry_or_claim_token_usage(client, monkeypatch, status):
    calls = []
    def provider(*args):
        calls.append(args)
        raise ProviderError(status)
    monkeypatch.setattr(client, "_generate_with_modern_sdk", provider)
    result = client._generate_sync("model", "prompt", {})
    assert result.is_fallback and result.error_code == f"http_{status}"
    assert len(calls) == result.attempts == 1
    assert result.total_tokens == result.estimated_cost_usd == 0


def test_retry_after_beyond_remaining_budget_does_not_retry(client, monkeypatch):
    calls = []
    def provider(*args):
        calls.append(args)
        raise ProviderError(429, retry_after=60)
    monkeypatch.setattr(client, "_generate_with_modern_sdk", provider)
    result = client._generate_sync("model", "prompt", {"timeout_seconds": .5})
    assert len(calls) == 1 and result.error_code == "http_429"


def test_default_translation_budget_can_recover_after_six_second_timeout(client, monkeypatch):
    now = [0.0]
    attempts = []
    monkeypatch.setattr("core.gemini_client.time.monotonic", lambda: now[0])
    def provider(model, prompt, config):
        attempts.append(config["_attempt_timeout_seconds"])
        if len(attempts) == 1:
            now[0] += 6.0
            raise TimeoutError()
        if config["_attempt_timeout_seconds"] < 4.0:
            raise TimeoutError()
        now[0] += 4.0
        return "{}", {"prompt_tokens": 1, "output_tokens": 1, "total_tokens": 2}
    monkeypatch.setattr(client, "_generate_with_modern_sdk", provider)
    result = client._generate_sync("model", "translation", {
        "timeout_seconds": Settings(_env_file=None).transcript_translation_timeout_seconds})
    assert not result.is_fallback and result.attempts == 2


def test_sdk_request_timeout_and_single_attempt_are_explicit(client):
    config = client._build_modern_config({"_attempt_timeout_seconds": 2.25})
    assert config.http_options.timeout == 2250
    assert config.http_options.retry_options.attempts == 1
    assert config.http_options.headers["X-Server-Timeout"] == "10"


def test_thinking_compatibility_retry_uses_remaining_attempt_budget(client, monkeypatch):
    now = [0.0]
    monkeypatch.setattr("core.gemini_client.time.monotonic", lambda: now[0])
    calls = []
    def generate(**kwargs):
        calls.append(kwargs["config"])
        if len(calls) == 1:
            now[0] = 3
            error = ProviderError(400)
            error.args = ("thinking unsupported",)
            raise error
        return SimpleNamespace(text="{}", usage_metadata=None)
    monkeypatch.setattr(client, "_get_modern_client", lambda: SimpleNamespace(models=SimpleNamespace(generate_content=generate)))
    client._generate_with_modern_sdk("model", "prompt", {"thinking_level": "minimal", "_attempt_timeout_seconds": 4})
    assert calls[0].http_options.timeout == 4000
    assert calls[1].http_options.timeout == 1000
    assert calls[1].http_options.headers["X-Server-Timeout"] == "10"


@pytest.mark.parametrize("cancelled_index", [0, 1])
def test_cancelled_caller_does_not_cancel_shared_work(client, monkeypatch, cancelled_index):
    started, release = threading.Event(), threading.Event()
    calls = []
    def provider(*args):
        calls.append(args)
        started.set()
        assert release.wait(2)
        return GenerationUsage(text="valid")
    monkeypatch.setattr(client, "_generate_sync", provider)
    async def scenario():
        request = dict(model="model", prompt="shared", config={})
        tasks = [asyncio.create_task(client.generate_content_with_metadata(**request)) for _ in range(3)]
        try:
            assert await asyncio.to_thread(started.wait, 1)
            tasks[cancelled_index].cancel()
            with pytest.raises(asyncio.CancelledError):
                await tasks[cancelled_index]
            assert len(client._inflight_requests) == 1
            release.set()
            results = await asyncio.wait_for(asyncio.gather(*(t for i, t in enumerate(tasks) if i != cancelled_index)), 1)
            assert all(r.text == "valid" for r in results)
            assert len(calls) == 1 and not client._inflight_requests
        finally:
            release.set()
    asyncio.run(scenario())


def test_unexpected_worker_exception_settles_all_waiters(client, monkeypatch):
    def broken(*args):
        raise RuntimeError("worker failure")
    monkeypatch.setattr(client, "_generate_sync", broken)
    async def scenario():
        request = dict(model="model", prompt="shared", config={})
        results = await asyncio.wait_for(asyncio.gather(
            client.generate_content_with_metadata(**request), client.generate_content_with_metadata(**request),
            return_exceptions=True), 1)
        assert all(isinstance(result, RuntimeError) for result in results)
        assert not client._inflight_requests
    asyncio.run(scenario())

@pytest.mark.parametrize("requested,expected", [(None,20.0),(4.0,4.0),(15.0,15.0),(90.0,90.0),(1000.0,120.0)])
def test_explicit_caller_budget_is_not_clamped_to_default(client, monkeypatch, requested, expected):
    now = [0.0]
    calls = []
    monkeypatch.setattr("core.gemini_client.time.monotonic", lambda: now[0])
    def provider(model, prompt, config):
        calls.append(config["_attempt_timeout_seconds"])
        if len(calls) == 1:
            now[0] = expected - 1
            raise TimeoutError()
        return "{}", {}
    monkeypatch.setattr(client, "_generate_with_modern_sdk", provider)
    result = client._generate_sync("model", "prompt", {} if requested is None else {"timeout_seconds":requested})
    assert not result.is_fallback and result.attempts == 2
    assert calls[1] == 1.0


@pytest.mark.parametrize("timeout", [0,-1,float("nan"),float("inf")])
def test_invalid_caller_timeout_never_starts_provider(client, monkeypatch, timeout):
    monkeypatch.setattr(client, "_generate_with_modern_sdk", lambda *args: pytest.fail("provider must not run"))
    with pytest.raises(ValueError, match="finite and positive"):
        client._generate_sync("model", "prompt", {"timeout_seconds": timeout})


def test_default_attempt_allows_observed_nine_second_response(client, monkeypatch):
    calls = []
    def provider(model, prompt, config):
        calls.append(config["_attempt_timeout_seconds"])
        if config["_attempt_timeout_seconds"] < 9.0:
            raise TimeoutError()
        return "{}", {}
    monkeypatch.setattr(client, "_generate_with_modern_sdk", provider)
    result = client._generate_sync("model", "prompt", {})
    assert not result.is_fallback and result.attempts == 1
    assert calls == [10.0]
