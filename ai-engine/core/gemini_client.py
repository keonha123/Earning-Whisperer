from __future__ import annotations

import asyncio
from dataclasses import dataclass, replace
import json
import logging
import math
import os
import random
import time
from typing import Any

import httpx

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


logger = logging.getLogger(__name__)


@dataclass(slots=True)
class GenerationUsage:
    text: str = ""
    prompt_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    estimated_cost_usd: float = 0.0
    cached: bool = False
    coalesced: bool = False
    is_fallback: bool = False
    error_code: str | None = None
    attempts: int = 1


class GeminiUnavailableError(RuntimeError):
    """Safe, machine-readable provider failure without credentials or prompt text."""

    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def _failure_code(error: Exception) -> tuple[str, bool]:
    status = getattr(error, "code", None)
    if isinstance(status, int):
        return f"http_{status}", status in {408, 429, 500, 502, 503, 504}
    if isinstance(error, (TimeoutError, httpx.TimeoutException)):
        return "timeout", True
    if isinstance(error, (ConnectionError, httpx.TransportError)):
        return "transport", True
    return "unavailable", False


def _retry_after_seconds(error: Exception) -> float:
    headers = getattr(getattr(error, "response", None), "headers", {}) or {}
    try:
        return max(0.0, float(headers.get("retry-after", 0)))
    except (TypeError, ValueError):
        return 0.0


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
        self._inflight_requests: dict[tuple[str, str, str], asyncio.Task] = {}
        self._token_budgeter = TokenBudgeter()

    def _get_modern_client(self):
        api_key = os.getenv("GEMINI_API_KEY") or get_settings().gemini_api_key
        if not api_key or modern_genai is None:
            return None
        if self._modern_client is None or self._modern_client_api_key != api_key:
            self._modern_client = modern_genai.Client(api_key=api_key, http_options=self._http_options(
                get_settings().gemini_attempt_timeout_seconds))
            self._modern_client_api_key = api_key
        return self._modern_client

    @staticmethod
    def _http_options(seconds: float):
        # SDK 1.70 derives X-Server-Timeout from the transport timeout unless
        # explicitly supplied. Gemini rejects server deadlines below 10s, but
        # the client may still stop waiting sooner for an interactive request.
        return modern_types.HttpOptions(
            timeout=max(1, int(seconds * 1000)),
            headers={"X-Server-Timeout": str(max(10, math.ceil(seconds)))},
            retry_options=modern_types.HttpRetryOptions(attempts=1),
        )

    def _build_modern_config(self, config: dict[str, Any], *, include_thinking: bool = True):
        if modern_types is None:
            return config
        kwargs = {
            "system_instruction": config.get("system_instruction"),
            "max_output_tokens": config.get("max_output_tokens"),
            "response_mime_type": config.get("response_mime_type", "application/json"),
            "response_json_schema": config.get("response_json_schema"),
            "temperature": config.get("temperature"),
        }
        if include_thinking and config.get("thinking_level"):
            kwargs["thinking_config"] = modern_types.ThinkingConfig(thinking_level=config["thinking_level"])
        if config.get("_attempt_timeout_seconds") is not None:
            kwargs["http_options"] = self._http_options(config["_attempt_timeout_seconds"])
        return modern_types.GenerateContentConfig(**{k: v for k, v in kwargs.items() if v is not None})

    @staticmethod
    def _cache_key(model: str, prompt: str, config: dict[str, Any]) -> tuple[str, str, str]:
        semantic_config = {k: v for k, v in config.items() if k not in {"timeout_seconds", "_attempt_timeout_seconds"}}
        return (model, prompt, json.dumps(semantic_config, sort_keys=True, default=str))

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
        started = time.monotonic()
        try:
            response = client.models.generate_content(model=model, contents=prompt, config=self._build_modern_config(config, include_thinking=True))
        except Exception as exc:
            if not config.get("thinking_level") or getattr(exc, "code", None) != 400:
                raise
            message = f"{type(exc).__name__}: {exc}".lower()
            if "thinking" not in message:
                raise
            retry_config = dict(config)
            if config.get("_attempt_timeout_seconds") is not None:
                remaining = config["_attempt_timeout_seconds"] - (time.monotonic() - started)
                if remaining <= 0:
                    raise TimeoutError("Thinking compatibility retry exceeded attempt budget") from exc
                retry_config["_attempt_timeout_seconds"] = remaining
            response = client.models.generate_content(model=model, contents=prompt, config=self._build_modern_config(retry_config, include_thinking=False))
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
        settings = get_settings()
        budget = min(float(config.get("timeout_seconds", settings.gemini_request_timeout_seconds)),
                     settings.gemini_request_timeout_seconds)
        deadline = time.monotonic() + max(0.001, budget)
        code = "timeout"
        attempts = 0
        for attempt in range(settings.gemini_max_retries + 1):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                code = "timeout"
                break
            attempts += 1
            attempt_config = {**config, "_attempt_timeout_seconds": min(remaining, settings.gemini_attempt_timeout_seconds)}
            try:
                out = self._generate_with_modern_sdk(model, prompt, attempt_config)
                if isinstance(out, GenerationUsage):
                    return replace(out, attempts=attempts)
                if isinstance(out, tuple):
                    text, usage = out
                    if not isinstance(text, str) or not text.strip():
                        raise ValueError("Empty provider response")
                    return GenerationUsage(text=text, prompt_tokens=usage.get("prompt_tokens", 0),
                        output_tokens=usage.get("output_tokens", 0), total_tokens=usage.get("total_tokens", 0),
                        estimated_cost_usd=usage.get("estimated_cost_usd", 0.0), attempts=attempts)
                raise ValueError("Invalid provider response")
            except Exception as exc:
                code, retryable = _failure_code(exc)
                # Log only classification: SDK exceptions can include request URLs.
                logger.warning("Gemini request failed model=%s code=%s attempt=%s", model, code, attempts)
                remaining = deadline - time.monotonic()
                delay = max(_retry_after_seconds(exc), settings.gemini_base_retry_delay * (2 ** attempt) * random.uniform(1.0, 1.25))
                if not retryable or attempt >= settings.gemini_max_retries or remaining <= delay + 0.25:
                    break
                time.sleep(delay)
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
        # A locally generated fallback is not paid model output.
        return GenerationUsage(text=text, is_fallback=True, error_code=code, attempts=attempts)

    async def generate_content_with_metadata(self, *, model: str, prompt: str | None = None, contents: str | None = None, config: dict[str, Any]) -> GenerationUsage:
        actual_prompt = contents if contents is not None else prompt or ""
        settings = get_settings()
        key = self._cache_key(model, actual_prompt, config)
        if settings.gemini_response_cache_enabled and key in self._response_cache:
            cached = self._response_cache[key]
            return replace(cached, cached=True, coalesced=False)

        shared = self._inflight_requests.get(key)
        coalesced = shared is not None
        if shared is None:
            shared = asyncio.create_task(self._run_generation(key, model, actual_prompt, dict(config)))
            self._inflight_requests[key] = shared
            # Retrieve late exceptions even when every HTTP caller has timed out.
            shared.add_done_callback(lambda task: task.exception() if not task.cancelled() else None)
        # A caller's timeout must not cancel other callers or launch duplicate
        # provider work. The shared operation has its own bounded SDK deadline.
        usage = await asyncio.shield(shared)
        return replace(usage, coalesced=coalesced)

    async def _run_generation(self, key, model, actual_prompt, config) -> GenerationUsage:
        settings = get_settings()
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
            if settings.gemini_response_cache_enabled and not usage_obj.is_fallback:
                self._response_cache[key] = usage_obj
                if len(self._response_cache) > settings.gemini_response_cache_max_entries:
                    oldest_key = next(iter(self._response_cache))
                    self._response_cache.pop(oldest_key, None)
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
