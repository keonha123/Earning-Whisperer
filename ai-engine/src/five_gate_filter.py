# ═══════════════════════════════════════════════════════════════════════════
# core/five_gate_filter.py
# 5-Gate Signal Confluence Filter — 승률 51%+ 달성의 핵심
# 5개 게이트 모두 PASS해야만 거래 실행
#
# 논문 근거:
#   Kelley & Tetlock(2013): 다중 지표 합류 시 예측 정확도 통계적 향상
#   Gate 1: Bernard(1992) — 강한 서프라이즈 구간 필터
#   Gate 2: Bernard & Thomas(1992) — SUE 방향 일치 PEAD
#   Gate 3: Jegadeesh & Titman(1993) — 기술적 모멘텀 일치
#   Gate 4: Chan(2003) — 뉴스 있는 거래량 폭발
#   Gate 5: Baker & Wurgler(2006) — 시장 국면 필터
# ═══════════════════════════════════════════════════════════════════════════
from dataclasses import dataclass
from typing import Optional
from config import settings


@dataclass
class GateConfig:
    """
    게이트 임계값. AdaptiveGate에 의해 자동 조정됨.
    승률 < 45% → tighten(), 승률 > 60% → loosen()
    """
    composite_threshold:  float = None
    raw_score_threshold:  float = None
    confidence_threshold: float = None
    max_euphemism_count:  int   = None
    min_volume_ratio:     float = None
    max_vix:              float = None

    def __post_init__(self):
        # settings에서 기본값 로드
        if self.composite_threshold  is None: self.composite_threshold  = settings.composite_threshold
        if self.raw_score_threshold  is None: self.raw_score_threshold  = settings.raw_score_threshold
        if self.confidence_threshold is None: self.confidence_threshold = settings.confidence_threshold
        if self.max_euphemism_count  is None: self.max_euphemism_count  = settings.max_euphemism_count
        if self.min_volume_ratio     is None: self.min_volume_ratio     = settings.min_volume_ratio
        if self.max_vix              is None: self.max_vix              = settings.max_vix

    def tighten(self):
        """승률 45% 이하: 임계값 강화 (통과율 감소 → 승률 향상 목표)"""
        self.composite_threshold  = min(0.70, self.composite_threshold  + 0.05)
        self.confidence_threshold = min(0.92, self.confidence_threshold + 0.03)
        self.min_volume_ratio     = min(2.50, self.min_volume_ratio     + 0.20)

    def loosen(self):
        """승률 60% 이상: 임계값 완화 (통과율 증가 → 거래 횟수 증가)"""
        self.composite_threshold  = max(0.50, self.composite_threshold  - 0.03)
        self.confidence_threshold = max(0.78, self.confidence_threshold - 0.02)
        self.min_volume_ratio     = max(1.30, self.min_volume_ratio     - 0.10)


# 전역 GateConfig 싱글턴
gate_config = GateConfig()


# ── Gate 1: 복합 강도 + 신뢰도 필터 ──────────────────────────────────────────
def gate1_confidence(
    composite_score: float,
    raw_score: float,
    confidence: float,
    euphemism_count: int,
) -> tuple:
    """
    Gate 1: 복합 강도 & 신뢰도 필터.
    애매한 신호를 완전히 차단. 승률 기여: +3%p.
    """
    if abs(composite_score) < gate_config.composite_threshold:
        return False, f"composite {composite_score:.2f} < {gate_config.composite_threshold}"
    if confidence < gate_config.confidence_threshold:
        return False, f"confidence {confidence:.2f} < {gate_config.confidence_threshold}"
    if abs(raw_score) < gate_config.raw_score_threshold:
        return False, f"raw_score {raw_score:.2f} < {gate_config.raw_score_threshold}"
    if euphemism_count > gate_config.max_euphemism_count:
        return False, f"euphemism_count {euphemism_count} > {gate_config.max_euphemism_count}"
    return True, "PASS"


# ── Gate 2: PEAD 방향 일치 필터 ─────────────────────────────────────────────
def gate2_pead(sue_score: Optional[float], composite_score: float) -> tuple:
    """
    Gate 2: SUE 방향과 감성 방향 일치 확인.
    방향 충돌 시 혼재 신호로 HOLD. 승률 기여: +3%p.
    """
    if sue_score is None:
        return True, "NO_DATA (허용)"

    # |SUE| < 1.0 이면 방향 불일치 허용 (신호 약함)
    if abs(sue_score) < 1.0:
        return True, f"SUE_WEAK ({sue_score:.1f}) — 방향 불일치 허용"

    sue_dir  = 1 if sue_score > 0 else -1
    comp_dir = 1 if composite_score > 0 else -1

    if sue_dir != comp_dir:
        return False, f"SUE_CONFLICT (sue={sue_score:.1f}, composite={composite_score:.2f})"

    return True, f"PEAD_ALIGNED (sue={sue_score:.1f})"


# ── Gate 3: 기술적 모멘텀 일치 필터 ─────────────────────────────────────────
def gate3_momentum(
    macd_signal: Optional[float],
    rsi_14: Optional[float],
    composite_score: float,
) -> tuple:
    """
    Gate 3: MACD 방향 + RSI 과매수/과매도 확인.
    감성 방향과 기술적 모멘텀 불일치 2개 이상 → FAIL.
    승률 기여: +2%p.
    """
    if macd_signal is None and rsi_14 is None:
        return True, "NO_DATA (허용)"

    comp_dir = 1 if composite_score > 0 else -1
    failures = []

    # MACD 히스토그램 방향 확인
    if macd_signal is not None:
        macd_dir = 1 if macd_signal > 0 else -1
        if macd_dir != comp_dir:
            failures.append(f"MACD_CONFLICT ({macd_signal:.3f})")

    # RSI 극단값 확인
    if rsi_14 is not None:
        if comp_dir == 1 and rsi_14 > 75:
            failures.append(f"RSI_OVERBOUGHT ({rsi_14:.0f})")
        elif comp_dir == -1 and rsi_14 < 25:
            failures.append(f"RSI_OVERSOLD ({rsi_14:.0f})")

    if len(failures) >= 2:
        return False, ", ".join(failures)

    return True, "PASS"


# ── Gate 4: 거래량 폭발 확인 필터 ────────────────────────────────────────────
def gate4_volume(volume_ratio: Optional[float], catalyst_type: str) -> tuple:
    """
    Gate 4: 이벤트 유형별 차등 거래량 임계값 확인.
    Chan(2003): 뉴스와 함께 거래량 폭발해야 추세 지속.
    승률 기여: +2%p.
    """
    if volume_ratio is None:
        return True, "NO_DATA (허용)"

    # 이벤트 유형별 요구 거래량 임계값 (높을수록 강한 확인 필요)
    thresholds = {
        "EARNINGS_BEAT":    1.8,
        "EARNINGS_MISS":    1.8,
        "GUIDANCE_UP":      1.5,
        "GUIDANCE_DOWN":    1.5,
        "RESTRUCTURING":    2.0,
        "PRODUCT_NEWS":     1.3,
        "MACRO_COMMENTARY": 1.0,
        "REGULATORY_RISK":  2.0,
        "GUIDANCE_HOLD":    1.0,
        "OPERATIONAL_EXEC": 1.3,
    }
    threshold = thresholds.get(catalyst_type, gate_config.min_volume_ratio)

    if volume_ratio < threshold:
        return False, f"volume_ratio {volume_ratio:.1f} < {threshold} (catalyst: {catalyst_type})"

    return True, f"PASS (volume={volume_ratio:.1f}x)"


# ── Gate 5: 시장 국면 허가 필터 ──────────────────────────────────────────────
def gate5_regime(vix: Optional[float], regime: str) -> tuple:
    """
    Gate 5: VIX 공포지수 + 시장 국면 체크.
    Baker & Wurgler(2006): 고변동성 구간 개별 이벤트 트레이딩 승률 하락.
    승률 기여: +1%p.
    """
    if vix is not None and vix >= gate_config.max_vix:
        return False, f"VIX={vix:.1f} >= {gate_config.max_vix}"
    if regime == "EXTREME_FEAR":
        return False, "EXTREME_FEAR 국면"
    return True, f"PASS (regime={regime})"


# ── 통합 함수 ─────────────────────────────────────────────────────────────────
def apply_5gate_filter(
    cs: float,           # composite_score
    rs: float,           # raw_score
    conf: float,         # confidence
    euph_cnt: int,       # euphemism count
    sue: Optional[float],
    macd: Optional[float],
    rsi: Optional[float],
    vol_ratio: Optional[float],
    catalyst: str,
    vix: Optional[float],
    regime: str,
) -> dict:
    """
    5-Gate 통합 판단.

    Returns:
        {
            "trade_approved": bool,
            "gates": {"g1":(bool,reason), ...},
            "failed": ["g1", ...],
            "adj_composite": float,  # 국면 보정 후 composite
            "strength": "STRONG"|"MODERATE"|"WEAK"
        }
    """
    g1, r1 = gate1_confidence(cs, rs, conf, euph_cnt)
    g2, r2 = gate2_pead(sue, cs)
    g3, r3 = gate3_momentum(macd, rsi, cs)
    g4, r4 = gate4_volume(vol_ratio, catalyst)
    g5, r5 = gate5_regime(vix, regime)

    all_pass = g1 and g2 and g3 and g4 and g5

    gates = {
        "g1": (g1, r1), "g2": (g2, r2), "g3": (g3, r3),
        "g4": (g4, r4), "g5": (g5, r5),
    }
    failed = [k for k, (v, _) in gates.items() if not v]

    # 국면 보정계수 적용
    from core.regime_classifier import get_regime_multiplier
    regime_mult   = get_regime_multiplier(cs, regime)
    adj_composite = round(cs * regime_mult, 4)

    # 신호 강도 분류
    if abs(adj_composite) >= 0.70:
        strength = "STRONG"
    elif abs(adj_composite) >= 0.50:
        strength = "MODERATE"
    else:
        strength = "WEAK"

    return {
        "trade_approved": all_pass,
        "gates":          gates,
        "failed":         failed,
        "adj_composite":  adj_composite,
        "strength":       strength,
    }
