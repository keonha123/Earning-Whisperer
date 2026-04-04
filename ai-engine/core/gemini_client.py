"""Gemini transport layer with compatibility support for old and new SDKs."""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from ..config import get_settings
from ..models.signal_models import GeminiAnalysisResult
from .prompt_builder import SYSTEM_PROMPT

logger = logging.getLogger(__name__)

try:  # Preferred modern SDK used by the hyeongyu branch.
    from google import genai as modern_genai
    from google.genai import types as modern_types
except ImportError:  # pragma: no cover - depends on local environment
    modern_genai = None
    modern_types = None

try:  # Legacy SDK kept for backwards compatibility.
    import google.generativeai as legacy_genai
except ImportError:  # pragma: no cover - depends on local environment
    legacy_genai = None


@dataclass
class GeminiStats:
    """Basic request statistics for monitoring."""

    call_count: int = 0
    error_count: int = 0
    total_latency_ms: float = 0.0
    route_counts: Dict[str, int] = field(default_factory=dict)

    @property
    def avg_latency_ms(self) -> float:
        if self.call_count == 0:
            return 0.0
        return round(self.total_latency_ms / self.call_count, 1)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "call_count": self.call_count,
            "error_count": self.error_count,
            "avg_latency_ms": self.avg_latency_ms,
            "route_counts": dict(sorted(self.route_counts.items())),
        }


class GeminiClient:
    """Gemini API client with a raw transport and parsed-analysis wrapper."""

    def __init__(self) -> None:
        self._stats = GeminiStats()
        self._stats_lock = asyncio.Lock()
        self._modern_client: Any = None
        self._modern_client_api_key: str | None = None

    async def analyze(self, prompt: str) -> GeminiAnalysisResult:
        """Legacy convenience wrapper that keeps older callers working."""

        settings = get_settings()
        config = self._default_config(settings)
        last_exc: Optional[Exception] = None

        for attempt in range(settings.gemini_max_retries):
            try:
                raw = await self.generate_content(
                    model=settings.gemini_primary_model,
                    contents=prompt,
                    config=config,
                )
                result = self.parse_response_text(raw)
                result.model_route = result.model_route or settings.gemini_primary_model
                return result
            except (json.JSONDecodeError, ValueError, KeyError) as exc:
                logger.warning("Gemini response parse failed (attempt %d): %s", attempt + 1, exc)
                last_exc = exc
            except Exception as exc:  # pragma: no cover - network / SDK failures
                logger.warning("Gemini request failed (attempt %d): %s", attempt + 1, exc)
                last_exc = exc

            if attempt < settings.gemini_max_retries - 1:
                delay = settings.gemini_base_retry_delay * (2**attempt)
                await asyncio.sleep(delay)

        logger.error("Gemini analyze failed after retries: %s", last_exc)
        return self._fallback_result()

    async def generate_content(self, *, model: str, contents: str, config: dict) -> str:
        """Low-level raw text generation entrypoint used by the graph workflow."""

        if not isinstance(contents, str) or not contents.strip():
            raise ValueError("contents must be a non-empty string")
        if not model or not model.strip():
            raise ValueError("model must be a non-empty string")

        start = time.monotonic()
        try:
            raw_text = await asyncio.to_thread(self._generate_sync, model.strip(), contents, config or {})
        except Exception:
            await self._record_error(model)
            raise

        latency_ms = (time.monotonic() - start) * 1000
        await self._record_success(model, latency_ms)
        return (raw_text or "").strip()

    def parse_response_text(self, raw_text: str) -> GeminiAnalysisResult:
        """Parse a JSON response body into a typed GeminiAnalysisResult."""

        cleaned = re.sub(r"^```(?:json)?\s*", "", raw_text.strip(), flags=re.MULTILINE)
        cleaned = re.sub(r"\s*```$", "", cleaned, flags=re.MULTILINE).strip()
        if not cleaned:
            raise ValueError("Gemini response is empty")

        payload = json.loads(cleaned)
        result = GeminiAnalysisResult(**payload)
        return result

    async def get_stats(self) -> Dict[str, Any]:
        async with self._stats_lock:
            return self._stats.to_dict()

    def _generate_sync(self, model: str, contents: str, config: dict) -> str:
        settings = get_settings()
        if not settings.gemini_api_key:
            raise RuntimeError("GEMINI_API_KEY is not configured")

        if modern_genai is not None and modern_types is not None:
            return self._generate_with_modern_sdk(model, contents, config)
        if legacy_genai is not None:
            return self._generate_with_legacy_sdk(model, contents, config)
        raise RuntimeError("No supported Gemini SDK is installed")

    def _generate_with_modern_sdk(self, model: str, contents: str, config: dict) -> str:
        settings = get_settings()
        if self._modern_client is None or self._modern_client_api_key != settings.gemini_api_key:
            self._modern_client = modern_genai.Client(api_key=settings.gemini_api_key)
            self._modern_client_api_key = settings.gemini_api_key

        thinking_level = config.get("thinking_level")
        generate_config = self._build_modern_generate_config(
            system_instruction=config.get("system_instruction", SYSTEM_PROMPT),
            max_output_tokens=config.get("max_output_tokens", settings.gemini_max_tokens),
            response_mime_type=config.get(
                "response_mime_type",
                settings.gemini_response_mime_type,
            ),
            thinking_level=thinking_level,
        )

        try:
            response = self._modern_client.models.generate_content(
                model=model,
                contents=contents,
                config=generate_config,
            )
        except TypeError as exc:
            if "thinking" not in str(exc).lower():
                raise
            logger.warning("Modern Gemini SDK rejected thinking config, retrying without it: %s", exc)
            generate_config = self._build_modern_generate_config(
                system_instruction=config.get("system_instruction", SYSTEM_PROMPT),
                max_output_tokens=config.get("max_output_tokens", settings.gemini_max_tokens),
                response_mime_type=config.get(
                    "response_mime_type",
                    settings.gemini_response_mime_type,
                ),
                thinking_level=None,
            )
            response = self._modern_client.models.generate_content(
                model=model,
                contents=contents,
                config=generate_config,
            )
        return getattr(response, "text", None) or ""

    def _generate_with_legacy_sdk(self, model: str, contents: str, config: dict) -> str:
        settings = get_settings()
        legacy_genai.configure(api_key=settings.gemini_api_key)
        model_client = legacy_genai.GenerativeModel(
            model_name=model,
            system_instruction=config.get("system_instruction", SYSTEM_PROMPT),
        )
        response = model_client.generate_content(
            contents,
            generation_config=legacy_genai.types.GenerationConfig(
                max_output_tokens=config.get("max_output_tokens", settings.gemini_max_tokens),
                temperature=0.1,
            ),
        )
        return getattr(response, "text", None) or ""

    @staticmethod
    def _default_config(settings) -> dict:
        return {
            "system_instruction": SYSTEM_PROMPT,
            "max_output_tokens": settings.gemini_standard_max_output_tokens,
            "response_mime_type": settings.gemini_response_mime_type,
            "thinking_level": settings.gemini_standard_thinking_level,
        }

    @staticmethod
    def _fallback_result() -> GeminiAnalysisResult:
        return GeminiAnalysisResult(
            direction="NEUTRAL",
            magnitude=0.0,
            confidence=0.0,
            rationale="Gemini analysis failed. Falling back to HOLD.",
            catalyst_type="MACRO_COMMENTARY",
            euphemism_count=0,
            negative_word_ratio=0.0,
            cot_reasoning=None,
            model_route="fallback",
        )

    async def _record_success(self, model: str, latency_ms: float) -> None:
        async with self._stats_lock:
            self._stats.call_count += 1
            self._stats.total_latency_ms += latency_ms
            self._stats.route_counts[model] = self._stats.route_counts.get(model, 0) + 1

    async def _record_error(self, model: str) -> None:
        async with self._stats_lock:
            self._stats.call_count += 1
            self._stats.error_count += 1
            self._stats.route_counts[model] = self._stats.route_counts.get(model, 0) + 1

    @staticmethod
    def _build_modern_generate_config(
        *,
        system_instruction: str,
        max_output_tokens: int,
        response_mime_type: str,
        thinking_level: str | None,
    ) -> Any:
        payload = {
            "system_instruction": system_instruction,
            "max_output_tokens": max_output_tokens,
            "response_mime_type": response_mime_type,
        }

        thinking_config = GeminiClient._build_modern_thinking_config(thinking_level)
        if thinking_config is not None:
            payload["thinking_config"] = thinking_config

        if modern_types is None or not hasattr(modern_types, "GenerateContentConfig"):
            return payload

        try:
            return modern_types.GenerateContentConfig(**payload)
        except TypeError:
            payload.pop("thinking_config", None)
            return modern_types.GenerateContentConfig(**payload)

    @staticmethod
    def _build_modern_thinking_config(thinking_level: str | None) -> Any:
        if not thinking_level or modern_types is None or not hasattr(modern_types, "ThinkingConfig"):
            return None

        builders = (
            lambda: modern_types.ThinkingConfig(thinking_level=thinking_level),
            lambda: modern_types.ThinkingConfig(level=thinking_level),
        )
        for build in builders:
            try:
                return build()
            except TypeError:
                continue
        logger.warning("Modern Gemini SDK does not support explicit thinking_level; omitting it")
        return None


gemini_client = GeminiClient()
