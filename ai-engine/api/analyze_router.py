"""Legacy analysis endpoint with the upgraded hyeongyu-style analysis service."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, HTTPException

from config import get_settings
from core.analysis_service import analysis_service
from core.composite_scorer import calculate_composite_score
from core.contract_adapter import to_backend_redis_signal
from core.context_manager import ChunkRecord, ContextManager
from core.five_gate_filter import FiveGateFilter
from core.integration_state import IntegrationStateStore
from core.pead_calculator import calculate_sue_score
from core.phase1_scorer import blend_raw_scores, fallback_gemini_result, phase1_scorer
from core.redis_publisher import RedisPublisher
from core.regime_classifier import apply_regime_multiplier, classify_regime
from core.risk_manager import calculate_risk_parameters
from core.score_normalizer import compute_raw_score
from models.request_models import AnalyzeBatchRequest, AnalyzeRequest, MarketData
from models.signal_models import StrategyName, TradingSignalV3
from strategies.orchestrator import StrategyOrchestrator

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1", tags=["analysis"])

_context_manager: Optional[ContextManager] = None
_gate_filter: Optional[FiveGateFilter] = None
_redis_publisher: Optional[RedisPublisher] = None
_integration_state: Optional[IntegrationStateStore] = None
_orchestrator = StrategyOrchestrator()


def init_dependencies(
    context_manager: ContextManager,
    gate_filter: FiveGateFilter,
    redis_publisher: RedisPublisher,
    integration_state: Optional[IntegrationStateStore] = None,
) -> None:
    """Inject shared runtime dependencies during FastAPI startup."""

    global _context_manager, _gate_filter, _redis_publisher, _integration_state
    _context_manager = context_manager
    _gate_filter = gate_filter
    _redis_publisher = redis_publisher
    _integration_state = integration_state


@router.post("/analyze", status_code=202)
async def analyze_text_chunk(
    request: AnalyzeRequest,
    background_tasks: BackgroundTasks,
) -> dict:
    """Receive a chunk, enqueue async analysis, and return immediately."""

    return enqueue_analysis_request(request, background_tasks)


@router.post("/analyze/batch", status_code=202)
async def analyze_batch(
    request: AnalyzeBatchRequest,
    background_tasks: BackgroundTasks,
) -> dict:
    """Accept a batch of transcript fragments for concurrent async processing."""

    if not request.items:
        raise HTTPException(status_code=400, detail="items must not be empty")

    background_tasks.add_task(_run_batch_pipeline, request)
    return {
        "status": "accepted",
        "accepted_count": len(request.items),
        "tickers": sorted({item.ticker for item in request.items}),
        "batch_label": request.batch_label,
    }


async def _run_pipeline(request: AnalyzeRequest) -> None:
    """Run the full analysis and signal generation flow."""

    _require_dependencies()

    ticker = request.ticker
    session_key = _build_session_key(request)
    start_time = time.monotonic()

    try:
        chunk_record = ChunkRecord(
            sequence=request.sequence,
            text_chunk=request.text_chunk,
            timestamp=request.timestamp,
        )
        await _context_manager.update(session_key, chunk_record, request.is_final)
        context_chunks = await _context_manager.get_context(session_key)

        md = request.market_data
        if _integration_state is not None:
            md = await _integration_state.merge_market_data(ticker, request.market_data)

        phase1_result = await asyncio.to_thread(phase1_scorer.analyze_text, request.text_chunk)

        llm_available = True
        try:
            gemini_result = await analysis_service.analyze(
                ticker=ticker,
                current_chunk=request.text_chunk,
                context_chunks=context_chunks[:-1],
                market_data=md,
                section_type=request.section_type,
                chunk_timestamp=request.timestamp,
                request_priority=request.request_priority,
                is_final=request.is_final,
                phase1_result=phase1_result,
            )
        except Exception as exc:
            llm_available = False
            logger.warning("LLM analysis unavailable for %s, using phase-1 fallback: %s", ticker, exc)
            gemini_result = fallback_gemini_result(request.text_chunk, phase1_result)

        llm_raw_score = compute_raw_score(gemini_result)
        raw_score = blend_raw_scores(
            phase1_score=phase1_result.raw_score,
            llm_score=llm_raw_score,
            llm_available=llm_available,
        )

        sue_score = calculate_sue_score(md)
        momentum_score = _compute_momentum_score(md)
        composite_score = calculate_composite_score(
            raw_score=raw_score,
            sue_score=sue_score,
            momentum_score=momentum_score,
            volume_ratio=md.volume_ratio if md else None,
        )

        regime = classify_regime(md)
        adj_composite = apply_regime_multiplier(composite_score, regime)

        filter_result = _gate_filter.apply(
            composite_score=composite_score,
            raw_score=raw_score,
            confidence=gemini_result.confidence,
            euphemism_count=gemini_result.euphemism_count,
            sue_score=sue_score,
            momentum_score=momentum_score,
            market_data=md,
            gemini_result=gemini_result,
            regime=regime,
            adj_composite=adj_composite,
        )

        primary_strategy, hold_days, whisper_signal, sector_contagion = (
            _orchestrator.select_strategy(md, gemini_result, raw_score)
        )

        risk_params = calculate_risk_parameters(
            adj_composite=adj_composite,
            confidence=gemini_result.confidence,
            market_data=md,
        )

        signal = TradingSignalV3(
            ticker=ticker,
            raw_score=round(raw_score, 4),
            rationale=gemini_result.rationale,
            text_chunk=request.text_chunk,
            timestamp=request.timestamp,
            composite_score=round(composite_score, 4),
            sue_score=round(sue_score, 4) if sue_score is not None else None,
            momentum_score=round(momentum_score, 4) if momentum_score is not None else None,
            trade_approved=filter_result.trade_approved,
            primary_strategy=primary_strategy,
            signal_strength=risk_params.signal_strength,
            position_pct=round(risk_params.position_pct, 4) if filter_result.trade_approved else 0.0,
            market_regime=regime,
            catalyst_type=gemini_result.catalyst_type,
            stop_loss_price=risk_params.stop_loss_price,
            take_profit_price=risk_params.take_profit_price,
            stop_loss_pct=risk_params.stop_loss_pct,
            take_profit_pct=risk_params.take_profit_pct,
            profit_factor=risk_params.profit_factor,
            hold_days_max=hold_days,
            failed_gates=filter_result.failed_gates or None,
            whisper_signal=whisper_signal,
            sector_contagion=sector_contagion,
            cot_reasoning=gemini_result.cot_reasoning,
        )

        backend_signal = to_backend_redis_signal(signal, is_session_end=request.is_final)
        await _redis_publisher.publish(signal, backend_signal=backend_signal)
        if _integration_state is not None:
            await _integration_state.record_signal(
                session_key=session_key,
                signal=signal,
                call_id=request.call_id,
                event_id=request.event_id,
                source_type=request.source_type.value if request.source_type else None,
                section_type=request.section_type.value if request.section_type else None,
                speaker_role=request.speaker_role,
                speaker_name=request.speaker_name,
            )

        elapsed_ms = (time.monotonic() - start_time) * 1000
        logger.info(
            "Pipeline completed ticker=%s seq=%d approved=%s strength=%s elapsed=%.0fms",
            ticker,
            request.sequence,
            filter_result.trade_approved,
            risk_params.signal_strength.value,
            elapsed_ms,
        )
    except Exception as exc:  # pragma: no cover - defensive
        logger.exception("Pipeline failed for %s: %s", ticker, exc)
        await _publish_error_signal(request, str(exc))


def _require_dependencies() -> None:
    if _context_manager is None or _gate_filter is None or _redis_publisher is None:
        raise RuntimeError("analyze_router dependencies were not initialized")


def enqueue_analysis_request(
    request: AnalyzeRequest,
    background_tasks: BackgroundTasks,
) -> dict:
    """Share the same analysis enqueue logic across multiple API surfaces."""

    if not request.text_chunk.strip():
        raise HTTPException(status_code=400, detail="text_chunk must not be empty")

    background_tasks.add_task(_run_pipeline, request)
    return {
        "status": "accepted",
        "sequence": request.sequence,
        "ticker": request.ticker,
        "call_id": request.call_id,
        "event_id": request.event_id,
    }


async def _run_batch_pipeline(request: AnalyzeBatchRequest) -> None:
    settings = get_settings()
    max_concurrency = min(request.max_concurrency, settings.analysis_batch_concurrency)
    semaphore = asyncio.Semaphore(max_concurrency)

    async def _run_one(item: AnalyzeRequest) -> None:
        async with semaphore:
            await _run_pipeline(item)

    await asyncio.gather(*[_run_one(item) for item in request.items])


def _build_session_key(request: AnalyzeRequest) -> str:
    if request.call_id:
        return f"{request.ticker}:{request.call_id}"
    if request.event_id:
        return f"{request.ticker}:{request.event_id}"
    if request.batch_id:
        return f"{request.ticker}:{request.batch_id}"
    return request.ticker

def _compute_momentum_score(md: Optional[MarketData]) -> Optional[float]:
    """Calculate a lightweight momentum score from technical inputs."""

    if md is None:
        return None

    score = 0.0
    weight_sum = 0.0

    if md.macd_signal is not None:
        macd_norm = max(-1.0, min(1.0, md.macd_signal * 10))
        score += 0.50 * macd_norm
        weight_sum += 0.50

    if md.rsi_14 is not None:
        rsi_norm = (md.rsi_14 - 50.0) / 50.0
        score += 0.30 * rsi_norm
        weight_sum += 0.30

    if md.bb_position is not None:
        bb_norm = (md.bb_position - 0.5) * 2.0
        score += 0.20 * bb_norm
        weight_sum += 0.20

    if weight_sum < 0.01:
        return None

    return float(max(-1.0, min(1.0, score / weight_sum)))


async def _publish_error_signal(request: AnalyzeRequest, error_msg: str) -> None:
    """Publish a fallback HOLD-style signal when the pipeline crashes."""

    try:
        error_signal = TradingSignalV3(
            ticker=request.ticker,
            raw_score=0.0,
            rationale=f"Pipeline error: {error_msg[:200]}",
            text_chunk=request.text_chunk,
            timestamp=request.timestamp,
            trade_approved=False,
            primary_strategy=StrategyName.ERROR_FALLBACK,
        )
        backend_signal = to_backend_redis_signal(error_signal, is_session_end=request.is_final)
        await _redis_publisher.publish(error_signal, backend_signal=backend_signal)
    except Exception:  # pragma: no cover - defensive
        logger.exception("Failed to publish fallback error signal")
