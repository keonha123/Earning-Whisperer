# ═══════════════════════════════════════════════════════════════════════════
# strategies/orchestrator.py
# 7대 전략 자동 선택 오케스트레이터
# 어닝콜 1건 → 조건 충족 전략 우선순위순 자동 반환
# ═══════════════════════════════════════════════════════════════════════════
from strategies.s1_breakout          import evaluate_breakout
from strategies.s2_premarket_gap     import evaluate_premarket_gap
from strategies.s3_contrarian        import detect_overreaction
from strategies.s4_short_squeeze     import detect_short_squeeze_setup
from strategies.s5_sector_contagion  import evaluate_sector_contagion
from strategies.s6_iv_crush          import evaluate_iv_crush
from strategies.s7_whisper           import apply_whisper_adjustment


class StrategyOrchestrator:
    """
    7대 전략을 우선순위대로 평가하여 조건 충족 전략 목록 반환.

    우선순위 (강도 + 빈도 기준):
      1. SHORT_SQUEEZE   — 방향+강도 최강, 드물지만 큰 수익
      2. GAP_AND_GO      — 가장 자주 발생
      3. GAP_FILL        — 갭 과잉 역추세
      4. NEWS_BREAKOUT   — 저항선 돌파
      5. SECTOR_CONTAGION— 2차 기업 선점
      6. IV_CRUSH        — 옵션 환경 필요
      7. WHISPER_PLAY    — 위스퍼 데이터 필요
      8. CONTRARIAN      — 역추세 (보수적)
    """

    PRIORITY = [
        "SHORT_SQUEEZE", "GAP_AND_GO", "GAP_FILL",
        "NEWS_BREAKOUT", "SECTOR_CONTAGION", "IV_CRUSH",
        "WHISPER_PLAY", "CONTRARIAN",
    ]

    def select_strategies(
        self,
        gemini_result,        # GeminiAnalysisResult
        market_data: dict,
        price_data: dict,
        composite_score: float,
        raw_score: float,
        portfolio_state: dict,
    ) -> list:
        """
        모든 전략 평가 → 조건 충족 전략 우선순위순 반환.
        최대 2개 전략 동시 실행 (포트폴리오 집중 방지).
        """
        selected = []
        md = market_data or {}
        pd = price_data   or {}

        # ── 전략 4: Short Squeeze ──────────────────────────────────────────
        r4 = detect_short_squeeze_setup(
            raw_score        = raw_score,
            catalyst_type    = gemini_result.catalyst_type,
            volume_ratio     = md.get("volume_ratio", 1.0),
            price_change_pct = pd.get("change_pct", 0),
            bb_position      = md.get("bb_position"),
            days_to_cover    = pd.get("days_to_cover"),
            short_interest_pct = pd.get("short_interest_pct"),
        )
        if r4.get("approved"):
            selected.append(r4)

        # ── 전략 2: Pre-Market 갭 ─────────────────────────────────────────
        if pd.get("gap_pct") is not None:
            r2 = evaluate_premarket_gap(
                gap_pct                = pd["gap_pct"],
                raw_score              = raw_score,
                rsi_14                 = md.get("rsi_14"),
                premarket_volume_ratio = pd.get("premarket_volume_ratio", 1.0),
                prev_close             = md.get("prev_close", 0),
            )
            if r2.get("approved"):
                selected.append(r2)

        # ── 전략 1: 뉴스 돌파매매 ─────────────────────────────────────────
        if pd.get("current") and pd.get("ma20"):
            r1 = evaluate_breakout(
                raw_score        = raw_score,
                catalyst_type    = gemini_result.catalyst_type,
                volume_ratio     = md.get("volume_ratio", 1.0),
                current_price    = pd["current"],
                ma20             = pd["ma20"],
                high_52w         = pd.get("high_52w", 0),
                first_5min_close = pd.get("first_5min_close", 0),
                first_5min_open  = pd.get("first_5min_open", 0),
                atr14            = md.get("atr_14", 0),
            )
            if r1.get("approved"):
                selected.append(r1)

        # ── 전략 6: IV Crush ──────────────────────────────────────────────
        if md.get("put_call_ratio") or md.get("iv_rank"):
            r6 = evaluate_iv_crush(
                raw_score         = raw_score,
                put_call_ratio    = md.get("put_call_ratio"),
                iv_rank           = md.get("iv_rank"),
                current_iv        = md.get("current_iv"),
                hours_to_earnings = md.get("hours_to_earnings"),
            )
            if r6.get("approved"):
                selected.append(r6)

        # ── 전략 3: 역추세 ────────────────────────────────────────────────
        r3 = detect_overreaction(
            raw_score        = raw_score,
            price_change_pct = pd.get("change_pct", 0),
            rsi_14           = md.get("rsi_14"),
            bb_position      = md.get("bb_position"),
            volume_ratio     = md.get("volume_ratio"),
            hours_since_news = pd.get("hours_since_news", 0),
        )
        if r3.get("approved"):
            selected.append(r3)

        # ── 전략 7: 위스퍼 조정 적용 (공통) ──────────────────────────────
        whisper_adj = apply_whisper_adjustment(
            raw_score             = raw_score,
            whisper_signal        = gemini_result.whisper_signal,
            earnings_surprise_pct = md.get("earnings_surprise_pct"),
        )
        # 위스퍼 미달 → 기존 매수 전략 제거 + 역추세 신호 추가
        if whisper_adj.get("whisper_penalty"):
            selected = [s for s in selected if s.get("direction") != "LONG"]
            if whisper_adj.get("contrarian_signal"):
                selected.insert(0, {
                    "approved":  True,
                    "strategy":  "WHISPER_PLAY",
                    "direction": whisper_adj["contrarian_signal"],
                    "hold_days_max": 1,
                    "note": whisper_adj["note"],
                })

        # ── 포트폴리오 여유 확인 ──────────────────────────────────────────
        open_positions = portfolio_state.get("open_positions", 0)
        max_new        = max(1, 3 - open_positions)  # 최대 3포지션

        # 우선순위 정렬
        def priority_key(s):
            strat = s.get("strategy", "UNKNOWN")
            return self.PRIORITY.index(strat) if strat in self.PRIORITY else 99

        selected.sort(key=priority_key)
        return selected[:max_new]


# 싱글턴
orchestrator = StrategyOrchestrator()
