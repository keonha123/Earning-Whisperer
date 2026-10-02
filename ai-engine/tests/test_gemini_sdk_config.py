from core.gemini_client import GeminiClient
import asyncio
from config import Settings


def test_thinking_level_and_structured_schema_reach_sdk():
    schema = {"type": "object", "properties": {"items": {"type": "array", "items": {"type": "string"}}}}
    value = GeminiClient()._build_modern_config({"thinking_level": "minimal", "response_json_schema": schema, "temperature": 0.1})
    assert value.thinking_config.thinking_level.value.lower() == "minimal"
    assert value.response_json_schema == schema
    assert value.temperature == 0.1
    fallback = GeminiClient()._build_modern_config({"thinking_level": "minimal", "response_json_schema": schema}, include_thinking=False)
    assert fallback.thinking_config is None
    assert fallback.response_json_schema == schema


def test_provider_failure_does_not_poison_response_cache(monkeypatch):
    monkeypatch.setattr("core.gemini_client.get_settings", lambda: Settings(_env_file=None, GEMINI_RESPONSE_CACHE_ENABLED=True, GEMINI_MAX_RETRIES=0))
    client = GeminiClient()
    calls = []

    def provider(*args):
        calls.append(args)
        if len(calls) == 1:
            raise ConnectionError("temporary provider outage")
        return '{"answer":"recovered"}', {"prompt_tokens": 2, "output_tokens": 2, "total_tokens": 4}

    monkeypatch.setattr(client, "_generate_with_modern_sdk", provider)

    async def scenario():
        request = dict(model="test", prompt="same question", config={})
        first = await client.generate_content_with_metadata(**request)
        second = await client.generate_content_with_metadata(**request)
        third = await client.generate_content_with_metadata(**request)
        assert first.is_fallback and not first.cached
        assert second.text == '{"answer":"recovered"}' and not second.is_fallback and not second.cached
        assert third.text == second.text and third.cached
        assert len(calls) == 2

    asyncio.run(scenario())
