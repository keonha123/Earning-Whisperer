# models/signal_models.py
# Redis trading-signals 채널로 발행하는 출력 페이로드 구조
# Contract 2: AI Engine → Backend
from pydantic import BaseModel, Field
from typing import Optional, List


class GeminiAnalysisResult(BaseModel):
    """
    Gemini API JSON 응답을 파싱하는 내부 전용 모델.
    외부(Redis)로 직접 발행되지 않음 — TradingSignalV3로 변환 후 발행.
    """
    # ── 핵심 감성 점수 ───────────────────────────────────────────────────────
    direction:             str           # "POSITIVE" | "NEUTRAL" | "NEGATIVE"
    magnitude:             float         # 0.0~1.0 (예상 가격 이동 강도)
    confidence:            float         # 0.0~1.0 (Gemini 자체 신뢰도)
    euphemisms:            List[dict]    # [{"phrase":"...","true_signal":"...","penalty":-0.15}]
    negative_word_ratio:   float = 0.0  # Loughran-McDonald 부정어 밀도 (Tetlock 2007)

    # ── 분류 및 해설 ─────────────────────────────────────────────────────────
    catalyst_type:         str   = "MACRO_COMMENTARY"  # 신호 촉발 유형
    rationale:             str                          # 한국어 2~3문장 해설
    cot_reasoning:         str   = ""                  # CoT 추론 요약 (감사용)
    key_terms:             List[str] = []               # 핵심 키워드

    # ── 위스퍼 분석 (전략 7) ─────────────────────────────────────────────────
    whisper_signal:        str   = "UNKNOWN"   # "ABOVE_WHISPER"|"AT_WHISPER"|"BELOW_WHISPER"
    whisper_evidence:      str   = ""          # 위스퍼 판단 근거 (한국어)

    # ── 과잉반응 감지 (전략 3) ────────────────────────────────────────────────
    overreaction_detected: bool  = False
    overreaction_direction:Optional[str] = None  # "LONG" | "SHORT" | null

    # ── 섹터 파급 (전략 5) ───────────────────────────────────────────────────
    sector_impact:         dict  = {}   # {"contagion_risk": bool, "affected_direction": str}


class TradingSignalV3(BaseModel):
    """
    Contract 2: AI Engine → Redis → Java Backend
    ────────────────────────────────────────────────
    기존 5개 필드: Java Backend 필수 파싱 (변경 금지)
    확장 필드: Optional — Java Backend에서 null 허용으로 파싱
    """
    # ══ 기존 Contract 2 필드 (Java Backend 필수, 절대 변경 금지) ══════════════
    ticker:     str
    raw_score:  float = Field(..., ge=-1.0, le=1.0)   # 기본 감성 점수
    rationale:  str                                    # 한국어 2~3문장
    text_chunk: str                                    # 원문 텍스트 (Frontend 타이핑용)
    timestamp:  int                                    # UTC Unix Epoch Second

    # ══ 확장 점수 필드 ═══════════════════════════════════════════════════════
    composite_score:   Optional[float] = None   # 퀀트 복합 점수 -1.0~+1.0
    sue_score:         Optional[float] = None   # PEAD SUE 점수 -5.0~+5.0
    momentum_score:    Optional[float] = None   # 기술적 모멘텀 -1.0~+1.0

    # ══ 트레이딩 실행 필드 ═══════════════════════════════════════════════════
    trade_approved:    Optional[bool]  = None   # 5-Gate 전체 통과 여부
    primary_strategy:  Optional[str]   = None   # 주 전략명
    signal_strength:   Optional[str]   = None   # "STRONG" | "MODERATE" | "WEAK"
    position_pct:      Optional[float] = None   # Kelly 포지션 비율 0.0~0.25
    market_regime:     Optional[str]   = None   # 시장 국면
    catalyst_type:     Optional[str]   = None   # 신호 촉발 유형

    # ══ 리스크 관리 필드 ════════════════════════════════════════════════════
    stop_loss_price:   Optional[float] = None   # 손절가 (절대 금액)
    take_profit_price: Optional[float] = None   # 익절가 (절대 금액)
    stop_loss_pct:     Optional[float] = None   # 손절 비율 %
    take_profit_pct:   Optional[float] = None   # 익절 비율 %
    profit_factor:     Optional[float] = None   # 수익비 (목표: ≥1.67)
    hold_days_max:     Optional[int]   = None   # 최대 보유 기간 (일)

    # ══ 추가 분석 필드 ══════════════════════════════════════════════════════
    failed_gates:      Optional[List[str]] = None  # 실패한 게이트 목록
    whisper_signal:    Optional[str]   = None
    sector_contagion:  Optional[bool]  = None
    cot_reasoning:     Optional[str]   = None
