from __future__ import annotations

import asyncio
from dataclasses import dataclass
import json
import math
import os
from typing import Any

try:
    from google import genai as modern_genai  # type: ignore
    from google.genai import types as modern_types  # type: ignore
except Exception:  # pragma: no cover
    modern_genai = None
    modern_types = None

try:
    from config import get_settings
    from core.token_budgeter import TokenBudgeter
except ImportError:  # pragma: no cover
    from ..config import get_settings
    from .token_budgeter import TokenBudgeter


@dataclass(slots=True)
class GenerationUsage:
    text: str = ""
    prompt_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    estimated_cost_usd: float = 0.0
    cached: bool = False
    coalesced: bool = False


@dataclass(slots=True)
class ResponseMetadata:
    text: str
    usage: dict[str, int | float]
    cached: bool = False
    coalesced: bool = False


class GeminiClient:
    def __init__(self) -> None:
        self._modern_client = None
        self._modern_client_api_key: str | None = None
        self._response_cache: dict[tuple[str, str, str], GenerationUsage] = {}
        self._inflight_requests: dict[tuple[str, str, str], asyncio.Future] = {}
        self._token_budgeter = TokenBudgeter()

    def _get_modern_client(self):
        api_key = os.getenv("GEMINI_API_KEY") or get_settings().gemini_api_key
        if not api_key or modern_genai is None:
            return None
        if self._modern_client is None or self._modern_client_api_key != api_key:
            self._modern_client = modern_genai.Client(api_key=api_key)
            self._modern_client_api_key = api_key
        return self._modern_client

    def _build_modern_config(self, config: dict[str, Any], *, include_thinking: bool = True):
        if modern_types is None:
            return config
        kwargs = {
            "system_instruction": config.get("system_instruction"),
            "max_output_tokens": config.get("max_output_tokens"),
            "response_mime_type": config.get("response_mime_type", "application/json"),
        }
        if include_thinking and config.get("thinking_level"):
            kwargs["thinking_config"] = modern_types.ThinkingConfig(level=config["thinking_level"])
        return modern_types.GenerateContentConfig(**{k: v for k, v in kwargs.items() if v is not None})

    @staticmethod
    def _cache_key(model: str, prompt: str, config: dict[str, Any]) -> tuple[str, str, str]:
        return (model, prompt, json.dumps(config, sort_keys=True, default=str))

    def _route_profile_for(self, *, model: str, config: dict[str, Any]) -> str:
        route_profile = str(config.get("route_profile") or "").strip().lower()
        if route_profile:
            return route_profile
        settings = get_settings()
        if model == (settings.gemini_review_model or ""):
            return "review"
        return "standard"

    def _usage_from_text(self, text: str, *, model: str = "", config: dict[str, Any] | None = None) -> GenerationUsage:
        tokens = max(2, math.ceil(len(text or "") / 4))
        prompt_tokens = max(1, tokens // 2)
        output_tokens = max(1, tokens - prompt_tokens)
        route_profile = self._route_profile_for(model=model, config=config or {})
        estimated_cost_usd = self._token_budgeter.estimate_cost_usd(
            route_profile=route_profile,
            prompt_tokens=prompt_tokens,
            output_tokens=output_tokens,
        )
        return GenerationUsage(
            text=text,
            prompt_tokens=prompt_tokens,
            output_tokens=output_tokens,
            total_tokens=tokens,
            estimated_cost_usd=estimated_cost_usd,
        )

    def _generate_with_modern_sdk(self, model: str, prompt: str, config: dict[str, Any]):
        client = self._get_modern_client()
        if client is None:
            raise RuntimeError("Gemini client unavailable")
        try:
            response = client.models.generate_content(model=model, contents=prompt, config=self._build_modern_config(config, include_thinking=True))
        except Exception as exc:
            if not config.get("thinking_level"):
                raise
            message = f"{type(exc).__name__}: {exc}".lower()
            if "thinking" not in message:
                raise
            response = client.models.generate_content(model=model, contents=prompt, config=self._build_modern_config(config, include_thinking=False))
        text = getattr(response, "text", response)
        usage = getattr(response, "usage_metadata", None)
        route_profile = self._route_profile_for(model=model, config=config)
        usage_dict: dict[str, int | float] = {
            "prompt_tokens": getattr(usage, "prompt_token_count", 0),
            "output_tokens": getattr(usage, "candidates_token_count", 0),
            "total_tokens": getattr(usage, "total_token_count", 0),
        }
        if not usage_dict["total_tokens"]:
            estimated = self._usage_from_text(str(text), model=model, config=config)
            usage_dict = {
                "prompt_tokens": estimated.prompt_tokens,
                "output_tokens": estimated.output_tokens,
                "total_tokens": estimated.total_tokens,
                "estimated_cost_usd": estimated.estimated_cost_usd,
            }
        else:
            usage_dict["estimated_cost_usd"] = self._token_budgeter.estimate_cost_usd(
                route_profile=route_profile,
                prompt_tokens=int(usage_dict["prompt_tokens"] or 0),
                output_tokens=int(usage_dict["output_tokens"] or 0),
            )
        return text, usage_dict

    def _generate_sync(self, model: str, prompt: str, config: dict[str, Any]) -> GenerationUsage:
        try:
            out = self._generate_with_modern_sdk(model, prompt, config)
            if isinstance(out, GenerationUsage):
                return out
            if isinstance(out, tuple):
                text, usage = out
                return GenerationUsage(text=text, prompt_tokens=usage.get("prompt_tokens", 0), output_tokens=usage.get("output_tokens", 0), total_tokens=usage.get("total_tokens", 0))
        except Exception:
            pass
        text = json.dumps(
            {
                "direction": "NEUTRAL",
                "magnitude": 0.0,
                "confidence": 0.0,
                "rationale": "Gemini fallback response",
                "catalyst_type": "UNCLASSIFIED",
                "euphemism_count": 0,
                "negative_word_ratio": 0.0,
                "cot_reasoning": "fallback",
            }
        )
        return self._usage_from_text(text, model=model, config=config)

    async def generate_content_with_metadata(self, *, model: str, prompt: str | None = None, contents: str | None = None, config: dict[str, Any]) -> GenerationUsage:
        actual_prompt = contents if contents is not None else prompt or ""
        settings = get_settings()
        key = self._cache_key(model, actual_prompt, config)
        if settings.gemini_response_cache_enabled and key in self._response_cache:
            cached = self._response_cache[key]
            return GenerationUsage(
                text=cached.text,
                prompt_tokens=cached.prompt_tokens,
                output_tokens=cached.output_tokens,
                total_tokens=cached.total_tokens,
                estimated_cost_usd=cached.estimated_cost_usd,
                cached=True,
                coalesced=False,
            )

        if key in self._inflight_requests:
            awaited = await self._inflight_requests[key]
            return GenerationUsage(
                text=awaited.text,
                prompt_tokens=awaited.prompt_tokens,
                output_tokens=awaited.output_tokens,
                total_tokens=awaited.total_tokens,
                estimated_cost_usd=awaited.estimated_cost_usd,
                cached=awaited.cached,
                coalesced=True,
            )

        loop = asyncio.get_running_loop()
        future: asyncio.Future = loop.create_future()
        self._inflight_requests[key] = future
        try:
            generated = await asyncio.to_thread(self._generate_sync, model, actual_prompt, config)
            if isinstance(generated, tuple):
                text, usage = generated
                usage_obj = GenerationUsage(
                    text=text,
                    prompt_tokens=int(usage.get("prompt_tokens", 0)),
                    output_tokens=int(usage.get("completion_tokens", usage.get("output_tokens", 0))),
                    total_tokens=int(usage.get("total_tokens", 0)),
                    estimated_cost_usd=float(
                        usage.get(
                            "estimated_cost_usd",
                            self._token_budgeter.estimate_cost_usd(
                                route_profile=self._route_profile_for(model=model, config=config),
                                prompt_tokens=int(usage.get("prompt_tokens", 0)),
                                output_tokens=int(usage.get("completion_tokens", usage.get("output_tokens", 0))),
                            ),
                        )
                    ),
                )
            elif isinstance(generated, GenerationUsage):
                usage_obj = generated
            elif isinstance(generated, str):
                usage_obj = self._usage_from_text(generated, model=model, config=config)
            else:
                usage_obj = self._usage_from_text(str(generated), model=model, config=config)
            if settings.gemini_response_cache_enabled:
                self._response_cache[key] = usage_obj
                if len(self._response_cache) > settings.gemini_response_cache_max_entries:
                    oldest_key = next(iter(self._response_cache))
                    self._response_cache.pop(oldest_key, None)
            future.set_result(usage_obj)
            return usage_obj
        finally:
            self._inflight_requests.pop(key, None)

    async def generate_content(self, *, model: str, contents: str, config: dict[str, Any]) -> str:
        metadata = await self.generate_content_with_metadata(model=model, contents=contents, config=config)
        return metadata.text

    @staticmethod
    def parse_response_text(raw_text: str) -> dict[str, Any]:
        return json.loads(raw_text)


gemini_client = GeminiClient()
