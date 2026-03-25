# ═══════════════════════════════════════════════════════════════════════════
# api/analyze_router.py
# POST /api/v1/analyze — 메인 엔드포인트
# ═══════════════════════════════════════════════════════════════════════════
import time
import logging

from fastapi import APIRouter, BackgroundTasks, HTTPException

from models.request_models  import AnalyzeRequest
from models.signal_models   import TradingSignalV3, GeminiAnalysisResult
from core.gemini_client     import gemini_client
from core.prompt_builder    import build_prompt
from core.context_manager   import context_manager
from core.score_normalizer  import normalize_score
from core.pead_calculator   import calculate_sue
from core.composite_scorer  import calculate_momentum_score, calculate_composite_score
from core.five_gate_filter  import apply_5gate_filter
from core.risk_manager      import calculate_exit_levels, calculate_kelly_position
from core.regime_classifier import classify_regime
from core.integrity_validator import validate_direction_consistency
from core.redis_publisher   import redis_publisher
from strategies.orchestrator import orchestrator

router = APIRouter()
logger = logging.getLogger("analyze_router")


@router.post("/api/v1/analyze", status_code=202)
async def analyze(request: AnalyzeRequest, bg: BackgroundTasks):
    """
    텍스트 청크 수신 → 즉시 202 반환, 분석은 백그라운드 실행.
    """
    # 기본 유효성 검사
    if not request.text_chunk.strip():
        raise HTTPException(status_code=400, detail="text_chunk가 비어있습니다")

    bg.add_task(_process_signal, request)
    return {
        "status":   "accepted",
        "sequence": request.sequence,
        "ticker":   request.ticker,
    }


@router.get("/health")
async def health():
    from config import settings
    return {
        "status":  "ok",
        "model":   settings.gemini_model,
        "version": "3.0.0",
    }


@router.get("/stats")
async def stats():
    return {
        "active_tickers": context_manager.get_all_tickers(),
    }


async def _process_signal(request: AnalyzeRequest):
    """백그라운드 분석 파이프라인."""
    try:
        md = request.market_data.model_dump() if request.market_data else {}

        # 1. 슬라이딩 윈도우 컨텍스트
        context = context_manager.get_context(request.ticker)

        # 2. 프롬프트 생성 & Gemini 호출
        prompt        = build_prompt(context, request.text_chunk, request.ticker, md, {})
        gemini_result = await gemini_client.analyze(prompt)

        # 3. raw_score 계산
        raw_score = normalize_score(
            direction           = gemini_result.direction,
            magnitude           = gemini_result.magnitude,
            confidence          = gemini_result.confidence,
            euphemisms          = gemini_result.euphemisms,
            negative_word_ratio = gemini_result.negative_word_ratio,
        )

        # 4. 무결성 검증 (환각 감지 → 재호출 1회)
        if not validate_direction_consistency(raw_score, gemini_result.rationale):
            logger.warning(f"방향 불일치 감지 ({request.ticker}) — 재호출")
            gemini_result = await gemini_client.analyze(prompt)
            raw_score = normalize_score(
                gemini_result.direction, gemini_result.magnitude,
                gemini_result.confidence, gemini_result.euphemisms,
            )

        # 5. 퀀트 점수 계산
        raw_sign       = 1.0 if raw_score > 0 else -1.0
        sue_score      = calculate_sue(md.get("earnings_surprise_pct"), raw_sign)
        momentum_score = calculate_momentum_score(
            md.get("macd_signal"), md.get("rsi_14"), md.get("bb_position")
        )
        composite_score = calculate_composite_score(
            raw_score, sue_score, momentum_score,
            md.get("volume_ratio", 1.0), md.get("vix"),
        )

        # 6. 시장 국면 & 5-Gate
        market_regime = classify_regime(md.get("vix"), md.get("bb_position"))
        gate_result   = apply_5gate_filter(
            cs       = composite_score,
            rs       = raw_score,
            conf     = gemini_result.confidence,
            euph_cnt = len(gemini_result.euphemisms),
            sue      = sue_score,
            macd     = md.get("macd_signal"),
            rsi      = md.get("rsi_14"),
            vol_ratio= md.get("volume_ratio"),
            catalyst = gemini_result.catalyst_type,
            vix      = md.get("vix"),
            regime   = market_regime,
        )

        # 7. 전략 선택
        price_data = {
            "current":           md.get("current_price", 0),
            "change_pct":        md.get("price_change_pct", 0),
            "ma20":              md.get("ma20", 0),
            "high_52w":          md.get("high_52w", 0),
            "atr14":             md.get("atr_14", 0),
            "first_5min_close":  md.get("first_5min_close", 0),
            "first_5min_open":   md.get("first_5min_open", 0),
            "gap_pct":           md.get("gap_pct"),
            "premarket_volume_ratio": md.get("premarket_volume_ratio"),
            "days_to_cover":     md.get("days_to_cover"),
            "short_interest_pct":md.get("short_interest_pct"),
            "hours_since_news":  md.get("hours_since_news", 0),
        }
        selected   = orchestrator.select_strategies(
            gemini_result   = gemini_result,
            market_data     = md,
            price_data      = price_data,
            composite_score = composite_score,
            raw_score       = raw_score,
            portfolio_state = {"open_positions": 0},
        )
        primary_strategy = selected[0]["strategy"] if selected else "SENTIMENT_ONLY"

        # 8. 포지션 사이징 & 손절/익절
        adj_comp    = gate_result["adj_composite"]
        position_pct = (
            calculate_kelly_position(adj_comp, gemini_result.confidence, md.get("vix"))
            if gate_result["trade_approved"] else 0.0
        )
        direction = "LONG" if composite_score >= 0 else "SHORT"
        exits = calculate_exit_levels(
            entry_price     = md.get("current_price", 0),
            atr_14          = md.get("atr_14", 0),
            composite_score = adj_comp,
            signal_strength = gate_result["strength"],
            direction       = direction,
        )

        # 9. 시그널 조립 & Redis 발행
        signal = TradingSignalV3(
            ticker            = request.ticker,
            raw_score         = raw_score,
            rationale         = gemini_result.rationale,
            text_chunk        = request.text_chunk,
            timestamp         = int(time.time()),
            composite_score   = composite_score,
            sue_score         = sue_score,
            momentum_score    = momentum_score,
            trade_approved    = gate_result["trade_approved"],
            primary_strategy  = primary_strategy,
            signal_strength   = gate_result["strength"],
            position_pct      = position_pct,
            market_regime     = market_regime,
            catalyst_type     = gemini_result.catalyst_type,
            stop_loss_price   = exits.get("stop_loss"),
            take_profit_price = exits.get("take_profit"),
            stop_loss_pct     = exits.get("risk_pct"),
            take_profit_pct   = exits.get("reward_pct"),
            profit_factor     = exits.get("profit_factor"),
            hold_days_max     = selected[0].get("hold_days_max") if selected else None,
            failed_gates      = gate_result["failed"] or None,
            whisper_signal    = gemini_result.whisper_signal,
            sector_contagion  = gemini_result.sector_impact.get("contagion_risk", False),
            cot_reasoning     = gemini_result.cot_reasoning,
        )
        await redis_publisher.publish(signal)

        # 10. 컨텍스트 업데이트 & 세션 종료
        context_manager.update(request.ticker, request.text_chunk)
        if request.is_final:
            context_manager.clear(request.ticker)
            logger.info(f"세션 종료: {request.ticker}")

    except Exception as e:
        logger.error(
            f"분석 오류 ({request.ticker} seq={request.sequence}): {e}",
            exc_info=True,
        )
        # HOLD 폴백 시그널 발행
        try:
            fallback = TradingSignalV3(
                ticker           = request.ticker,
                raw_score        = 0.0,
                rationale        = "분석 오류 — HOLD 처리합니다.",
                text_chunk       = request.text_chunk,
                timestamp        = int(time.time()),
                trade_approved   = False,
                signal_strength  = "WEAK",
                primary_strategy = "ERROR_FALLBACK",
            )
            await redis_publisher.publish(fallback)
        except Exception as pub_err:
            logger.error(f"폴백 발행 실패: {pub_err}")
