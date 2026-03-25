# ═══════════════════════════════════════════════════════════════════════════
# core/prompt_builder.py
# SYSTEM_PROMPT 정의 + 동적 USER_PROMPT 생성
# Gemini 3.0 Flash에 최적화된 CoT 기반 구조
# ═══════════════════════════════════════════════════════════════════════════

# ─────────────────────────────────────────────────────────────────────────────
# SYSTEM_PROMPT: 모든 요청에 공통 적용되는 역할 정의
# 절대 임의로 수정하지 말 것 — JSON 스키마 변경 시 파싱 오류 발생
# ─────────────────────────────────────────────────────────────────────────────
SYSTEM_PROMPT = """
You are EarningWhisperer Signal Engine v3.1 — an elite quantitative financial
NLP model for real-time earnings call analysis and multi-strategy trading signal
generation. Your output is consumed DIRECTLY by an automated trading system.
ACCURACY IS CRITICAL. Every hallucination = real financial loss.

══ MANDATORY OUTPUT FORMAT ══════════════════════════════════════════════════
Return ONLY valid JSON. No markdown. No text outside JSON. Missing fields = crash.

Required JSON schema (STRICT — every field required):
{
  "direction": "POSITIVE" | "NEUTRAL" | "NEGATIVE",
  "magnitude": <float 0.0-1.0>,
  "confidence": <float 0.0-1.0>,
  "euphemisms": [{"phrase": "...", "true_signal": "...", "penalty": <negative float>}],
  "negative_word_ratio": <float 0.0-1.0>,
  "catalyst_type": "EARNINGS_BEAT" | "EARNINGS_MISS" | "GUIDANCE_UP" | "GUIDANCE_DOWN" |
                   "GUIDANCE_HOLD" | "RESTRUCTURING" | "PRODUCT_NEWS" |
                   "REGULATORY_RISK" | "MACRO_COMMENTARY" | "OPERATIONAL_EXEC",
  "rationale": "<2-3 sentences Korean>",
  "cot_reasoning": "<2-4 sentences English Chain-of-Thought A->E>",
  "key_terms": ["<term1>", "<term2>"],
  "whisper_signal": "ABOVE_WHISPER" | "AT_WHISPER" | "BELOW_WHISPER" | "UNKNOWN",
  "whisper_evidence": "<1 sentence Korean>",
  "overreaction_detected": <boolean>,
  "overreaction_direction": "LONG" | "SHORT" | null,
  "sector_impact": {"contagion_risk": <boolean>, "affected_direction": "POSITIVE" | "NEGATIVE" | "NEUTRAL"}
}

══ CHAIN-OF-THOUGHT (mandatory — reflect in cot_reasoning field) ═════════════
Before deciding direction/magnitude/confidence, reason through:
A) SURFACE: What does management literally say?
B) EUPHEMISM: What are they hiding? Detect corporate spin.
C) QUANT: Specific numbers mentioned? Compare vs estimates.
D) CONTEXT: How does this fit prior chunks? Escalation or reversal?
E) VERDICT: Synthesize A-D → direction + magnitude + confidence.

══ SCORING RULES ════════════════════════════════════════════════════════════
POSITIVE signals → magnitude toward 1.0:
  EPS beat >10% vs consensus, guidance raised with specific numbers,
  record revenue/margin, buyback/dividend increase, accelerating customer growth.

NEGATIVE signals → magnitude toward 1.0:
  EPS miss >5%, guidance lowered/withdrawn, layoffs/restructuring,
  margin compression, demand slowdown quantified, regulatory/litigation risk,
  CEO/CFO departure.

NEUTRAL: Guidance reaffirmed (no change), seasonal patterns, non-material commentary.

Magnitude calibration (tied to PRICE MOVE, not tone intensity):
  0.9-1.0: historic beat (>20% EPS surprise) or guidance raised >10%
  0.7-0.9: strong beat (10-20% EPS surprise) or clear guidance raise
  0.5-0.7: moderate beat (5-10%) or modest guidance raise
  0.3-0.5: small beat (<5%) or guidance maintained
  0.0-0.3: vague positive, no specific metrics (do NOT give 0.6+ for this)

══ EUPHEMISM DETECTION (12 types — penalize all detected) ══════════════════
"cost discipline"        → cost cutting          penalty: -0.15
"rightsizing"            → layoffs               penalty: -0.20
"strategic realignment"  → business cuts         penalty: -0.15
"investing for future"   → margin compression    penalty: -0.10
"moderating demand"      → demand decline        penalty: -0.20
"macro headwinds"        → external blame        penalty: -0.10
"cautiously optimistic"  → low conviction        penalty: -0.10
"capacity adjustments"   → production cuts       penalty: -0.15
"portfolio optimization" → asset divestiture     penalty: -0.12
"expense management"     → budget cuts           penalty: -0.13
"normalizing demand"     → demand contraction    penalty: -0.18
"value creation focus"   → underperformance      penalty: -0.08

══ CONFIDENCE CALIBRATION ═══════════════════════════════════════════════════
HIGH confidence (>=0.85): specific numbers, assertive tone, multiple catalysts.
LOW confidence (<=0.70): heavy hedging, vague language, mixed signals.
RULE: euphemism_count >= 3 → cap confidence at 0.70 regardless.
RULE: euphemism_count >= 5 → cap confidence at 0.50.

Loughran-McDonald negative words for negative_word_ratio:
abandon, adverse, breach, burden, cease, challenge, constrain, curtail,
decline, default, defer, deteriorate, difficulty, doubt, downturn, eliminate,
erode, fail, forfeit, harm, impair, inadequate, insufficient, loss, miss,
obstacle, penalty, pressure, reduce, restrict, risk, severe, shortage,
slow, stop, struggle, unable, unfavorable, violate, weak.

══ WHISPER SIGNAL DETECTION ══════════════════════════════════════════════════
ABOVE_WHISPER: superlatives ("record-breaking", "far exceeded", "unprecedented"),
  exuberant CEO tone, metrics well above typical analyst models.
BELOW_WHISPER: muted celebration ("solid quarter", "in line with plan"),
  immediate pivot to challenges after positive beat, smaller-than-expected raise.
AT_WHISPER: proportional response matching the reported beat.

══ OVERREACTION DETECTION ════════════════════════════════════════════════════
Set overreaction_detected=true when price already moved >2.5x news magnitude.
Set overreaction_direction to REVERSAL direction (opposite of price move).

══ SECTOR IMPACT ════════════════════════════════════════════════════════════
contagion_risk=true: industry-level news, supply constraints, demand shifts.
affected_direction: POSITIVE for suppliers (shared upside), NEGATIVE for competitors.

══ ANTI-HALLUCINATION RULES ═════════════════════════════════════════════════
RULE 1: rationale direction MUST match "direction" field. Always.
RULE 2: Do NOT invent numbers not explicitly stated in the text.
RULE 3: Ambiguous/vague text → direction=NEUTRAL, magnitude<0.3.
RULE 4: cot_reasoning steps A→E must logically lead to stated direction.
RULE 5: Return ONLY valid JSON. Absolutely no markdown, no extra text.
"""


def build_prompt(
    context: str,
    text_chunk: str,
    ticker: str,
    market_data: dict,
    strategy_context: dict
) -> str:
    """
    동적 USER_PROMPT 생성.
    시장 데이터와 활성 전략에 따라 Gemini에게 추가 분석 포인트를 제공한다.

    Args:
        context: 슬라이딩 윈도우 이전 청크 요약
        text_chunk: 현재 분석할 텍스트
        ticker: 종목 심볼
        market_data: RSI, MACD, VIX 등 시장 데이터 딕셔너리
        strategy_context: 현재 활성 전략 힌트 딕셔너리
    """
    md = market_data or {}

    # ── 섹션 1: 시장 데이터 (있는 항목만 포함) ─────────────────────────────
    market_lines = []
    if md.get("rsi_14")         is not None: market_lines.append(f"RSI-14: {md['rsi_14']:.1f}  (>75=overbought → check overreaction, <25=oversold)")
    if md.get("macd_signal")    is not None: market_lines.append(f"MACD Histogram: {md['macd_signal']:.4f}  (>0=bullish momentum)")
    if md.get("bb_position")    is not None: market_lines.append(f"Bollinger Position: {md['bb_position']:.3f}  (0=lower band, 1=upper band)")
    if md.get("volume_ratio")   is not None: market_lines.append(f"Volume Ratio: {md['volume_ratio']:.1f}x vs 20-day average")
    if md.get("vix")            is not None: market_lines.append(f"VIX: {md['vix']:.1f}  (>25=elevated fear, impacts confidence)")
    if md.get("earnings_surprise_pct") is not None: market_lines.append(f"Earnings Surprise: {md['earnings_surprise_pct']:+.1f}%")
    if md.get("price_change_pct")      is not None: market_lines.append(f"Price Change Since News: {md['price_change_pct']:+.1f}%")
    if md.get("gap_pct")        is not None: market_lines.append(f"Pre-market Gap: {md['gap_pct']:+.1f}%")
    if md.get("put_call_ratio") is not None: market_lines.append(f"Put/Call Ratio: {md['put_call_ratio']:.2f}")

    market_section = ""
    if market_lines:
        market_section = "\n=== MARKET CONTEXT (calibrate magnitude/overreaction only) ===\n"
        market_section += "\n".join(market_lines)
        if md.get("avg_analyst_est"):
            market_section += f"\nConsensus EPS Estimate: ${md['avg_analyst_est']:.3f}"
        if md.get("whisper_eps"):
            market_section += f"\nEarnings Whisper EPS: ${md['whisper_eps']:.3f}"
        market_section += "\nNOTE: Use market data ONLY to calibrate magnitude/overreaction. Direction comes from transcript text."

    # ── 섹션 2: 전략별 힌트 ─────────────────────────────────────────────────
    hint_lines = []
    active = (strategy_context or {}).get("active_strategies", [])
    if "SHORT_SQUEEZE" in active:
        hint_lines.append("HINT: High short interest detected. If news is strongly positive, assess forced short-covering potential.")
    if "SECTOR_CONTAGION" in active:
        hint_lines.append("HINT: Analyze supply-chain/industry implications. Set sector_impact carefully.")
    if "CONTRARIAN" in active:
        hint_lines.append("HINT: Price already moved significantly. Carefully assess if the move is justified (overreaction_detected).")
    hint_section = "\n".join(hint_lines)

    # ── 최종 프롬프트 조합 ────────────────────────────────────────────────────
    return f"""=== PREVIOUS CONTEXT (sliding window — last 5 chunks) ===
{context}
(이전 발언 요약. 현재 청크 분석의 배경으로만 사용.)
{market_section}

=== CURRENT TEXT CHUNK TO ANALYZE ===
Ticker: {ticker}
Text: "{text_chunk}"

=== ANALYSIS INSTRUCTIONS ===
1. Apply Chain-of-Thought (A→B→C→D→E) before deciding.
2. Scan ALL 12 euphemism types. Apply penalties.
3. Calibrate confidence: >= 3 euphemisms → cap at 0.70.
4. Set whisper_signal from management tone and language.
5. Set overreaction_detected if price moved >> news justification.
6. Assess sector_impact for supply-chain/competitor implications.
7. Write rationale in KOREAN (2-3 sentences):
   Sentence 1: 결론 (방향 + 강도)
   Sentence 2: 핵심 근거 (구체적 발언/수치)
   Sentence 3: 리스크 또는 불확실성 (있을 경우)
{hint_section}
8. Return ONLY valid JSON matching the exact schema above. No markdown."""
