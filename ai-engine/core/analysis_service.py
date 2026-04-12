"""Analysis orchestration service with Gemini 3.x cost-aware routing."""

from __future__ import annotations

import asyncio
import logging
import warnings
from dataclasses import dataclass, field
from typing import Sequence

from config import get_settings
from models.request_models import MarketData, SectionType
from models.signal_models import GeminiAnalysisResult
from src.graph.workflow import agent
from .context_manager import ChunkRecord
from .gemini_client import gemini_client
from .phase1_scorer import Phase1ScoreResult
from .prompt_builder import SYSTEM_PROMPT, build_prompt

logger = logging.getLogger(__name__)


@dataclass
class RoutingStats:
    total_chunks: int = 0
    flash_only_chunks: int = 0
    pro_escalations: int = 0
    economy_prompts: int = 0
    total_prompt_tokens: int = 0
    total_output_tokens: int = 0
    route_counts: dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict[str, object]:
        total = max(self.total_chunks, 1)
        return {
            "route_counts": dict(sorted(self.route_counts.items())),
            "flash_only_rate": round(self.flash_only_chunks / total, 4),
            "pro_escalation_rate": round(self.pro_escalations / total, 4),
            "avg_estimated_prompt_tokens": round(self.total_prompt_tokens / total, 1),
            "avg_estimated_output_tokens": round(self.total_output_tokens / total, 1),
            "economy_prompt_rate": round(self.economy_prompts / total, 4),
        }


class AnalysisService:
    """Build prompts and execute the graph-based Gemini workflow."""

    def __init__(self) -> None:
        self._stats = RoutingStats()
        self._stats_lock = asyncio.Lock()

    def build_prompt(
        self,
        *,
        ticker: str,
        current_chunk: str,
        context_chunks: Sequence[ChunkRecord],
        market_data: MarketData | None,
        prompt_profile: str = "standard",
        context_policy: str = "rolling",
        phase1_score: float | None = None,
        previous_result: GeminiAnalysisResult | None = None,
        review_reason: str | None = None,
    ) -> str:
        return build_prompt(
            ticker=ticker,
            current_chunk=current_chunk,
            context_chunks=list(context_chunks),
            market_data=market_data,
            prompt_profile=prompt_profile,
            context_policy=context_policy,
            phase1_score=phase1_score,
            previous_result=previous_result,
            review_reason=review_reason,
        )

    async def _analyze_prompt_direct(
        self,
        prompt: str,
        *,
        model: str | None = None,
        max_output_tokens: int | None = None,
        thinking_level: str | None = None,
    ) -> GeminiAnalysisResult:
        settings = get_settings()
        target_model = model or settings.gemini_primary_model
        config = {
            "system_instruction": SYSTEM_PROMPT,
            "max_output_tokens": max_output_tokens or settings.gemini_standard_max_output_tokens,
            "response_mime_type": settings.gemini_response_mime_type,
            "thinking_level": thinking_level or settings.gemini_standard_thinking_level,
        }
        raw = await gemini_client.generate_content(
            model=target_model,
            contents=prompt,
            config=config,
        )
        result = gemini_client.parse_response_text(raw)
        result.model_route = result.model_route or target_model
        return result

    async def analyze_prompt(
        self,
        prompt: str,
        *,
        model: str | None = None,
        max_output_tokens: int | None = None,
        thinking_level: str | None = None,
        allow_direct_prompt: bool = False,
    ) -> GeminiAnalysisResult:
        """Deprecated direct-prompt helper.

        This bypasses the live routing graph and should only be used for
        explicit research or debugging workflows.
        """

        if not allow_direct_prompt:
            raise RuntimeError(
                "Direct prompt analysis bypasses live routing. "
                "Use AnalysisService.analyze() for production flows or pass "
                "allow_direct_prompt=True for explicit research usage."
            )

        warnings.warn(
            "AnalysisService.analyze_prompt() is deprecated because it bypasses "
            "the live routing graph. Prefer AnalysisService.analyze().",
            DeprecationWarning,
            stacklevel=2,
        )
        return await self._analyze_prompt_direct(
            prompt,
            model=model,
            max_output_tokens=max_output_tokens,
            thinking_level=thinking_level,
        )

    async def analyze(
        self,
        *,
        ticker: str,
        current_chunk: str,
        context_chunks: Sequence[ChunkRecord],
        market_data: MarketData | None,
        section_type: SectionType | None,
        chunk_timestamp: int,
        request_priority: int,
        is_final: bool,
        phase1_result: Phase1ScoreResult,
    ) -> GeminiAnalysisResult:
        state = {
            "ticker": ticker,
            "current_chunk": current_chunk,
            "current_market_data": market_data,
            "context_chunks": list(context_chunks),
            "section_type": section_type,
            "chunk_timestamp": chunk_timestamp,
            "request_priority": request_priority,
            "is_final": is_final,
            "phase1_raw_score": phase1_result.raw_score,
            "phase1_confidence": phase1_result.confidence,
        }
        response_state = await agent.ainvoke(state)
        if not isinstance(response_state, dict) or "result" not in response_state:
            raise RuntimeError("Gemini routing workflow did not return a result")

        result: GeminiAnalysisResult = response_state["result"]
        await self._record_route_stats(response_state)
        return result

    async def get_stats(self) -> dict[str, object]:
        async with self._stats_lock:
            return self._stats.to_dict()

    async def _record_route_stats(self, state: dict) -> None:
        route_profile = state.get("route_profile", "unknown")
        used_review = bool(state.get("review_result_text"))
        prompt_tokens = int(state.get("estimated_prompt_tokens", 0) or 0)
        output_tokens = int(state.get("estimated_output_tokens", 0) or 0)

        async with self._stats_lock:
            self._stats.total_chunks += 1
            self._stats.total_prompt_tokens += prompt_tokens
            self._stats.total_output_tokens += output_tokens
            self._stats.route_counts[route_profile] = self._stats.route_counts.get(route_profile, 0) + 1
            if route_profile == "economy":
                self._stats.economy_prompts += 1
            if used_review:
                self._stats.pro_escalations += 1
                self._stats.route_counts["review_escalation"] = (
                    self._stats.route_counts.get("review_escalation", 0) + 1
                )
            else:
                self._stats.flash_only_chunks += 1


analysis_service = AnalysisService()
