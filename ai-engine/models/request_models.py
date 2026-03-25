# ═══════════════════════════════════════════════════════════════════════════
# models/request_models.py
# POST /api/v1/analyze 요청 바디 구조 정의
# Data Pipeline → AI 엔진으로 오는 데이터 계약 (Contract 1)
# ═══════════════════════════════════════════════════════════════════════════
from pydantic import BaseModel, Field
from typing import Optional


class MarketData(BaseModel):
    """
    yfinance + AlphaVantage + 옵션 데이터 등 시장 데이터 묶음.
    모든 필드 Optional → 없어도 AI 엔진 동작 (감성 분석만으로 fallback)
    """
    # ── 가격 데이터 ─────────────────────────────────────────────────────────
    prev_close:            Optional[float] = None   # 전일 종가
    current_price:         Optional[float] = None   # 현재가
    price_change_pct:      Optional[float] = None   # 뉴스 발표 후 가격 변화율 %

    # ── 기술 지표 (ta 라이브러리로 계산) ────────────────────────────────────
    rsi_14:        Optional[float] = Field(None, ge=0, le=100)   # RSI (0~100)
    macd_signal:   Optional[float] = None    # MACD 히스토그램 (양수=상승 모멘텀)
    bb_position:   Optional[float] = Field(None, ge=0, le=1)    # 볼린저밴드 (0=하단,1=상단)
    atr_14:        Optional[float] = None    # ATR14 (손절/익절 계산에 사용)
    volume_ratio:  Optional[float] = None    # 거래량 배율 (현재 / 20일 평균)
    ma20:          Optional[float] = None    # 20일 이동평균
    high_52w:      Optional[float] = None    # 52주 최고가

    # ── 시장 환경 ────────────────────────────────────────────────────────────
    vix:           Optional[float] = None    # CBOE VIX 공포지수

    # ── EPS 데이터 (AlphaVantage) ───────────────────────────────────────────
    earnings_surprise_pct: Optional[float] = None   # (실제-예상)/|예상| × 100
    avg_analyst_est:       Optional[float] = None   # 컨센서스 EPS 추정치
    whisper_eps:           Optional[float] = None   # 어닝 위스퍼 EPS

    # ── Pre-Market 데이터 ────────────────────────────────────────────────────
    gap_pct:                 Optional[float] = None  # 전일 대비 갭 %
    premarket_volume_ratio:  Optional[float] = None  # 프리마켓 거래량 배율

    # ── 옵션 데이터 (선택) ───────────────────────────────────────────────────
    put_call_ratio:    Optional[float] = None   # Put/Call 거래량 비율
    current_iv:        Optional[float] = None   # 현재 내재변동성
    iv_rank:           Optional[float] = None   # IV Rank (0~100)
    hours_to_earnings: Optional[float] = None   # 어닝 발표까지 남은 시간

    # ── 공매도 데이터 (선택) ─────────────────────────────────────────────────
    short_interest_pct:Optional[float] = None   # 유통주식 대비 공매도 비율 %
    days_to_cover:     Optional[float] = None   # 공매도 청산에 필요한 평균 일수

    # ── 기타 ────────────────────────────────────────────────────────────────
    hours_since_news:  Optional[float] = None   # 뉴스 발표 후 경과 시간
    first_5min_close:  Optional[float] = None   # 뉴스 후 첫 5분봉 종가
    first_5min_open:   Optional[float] = None   # 뉴스 후 첫 5분봉 시가


class AnalyzeRequest(BaseModel):
    """
    Contract 1: Data Pipeline → AI Engine
    기존 5개 필드 100% 유지 + market_data 확장 필드 추가
    """
    # ── 기존 Contract 1 필드 (변경 금지) ────────────────────────────────────
    ticker:     str  = Field(..., description="종목 심볼. 예: NVDA")
    text_chunk: str  = Field(..., min_length=1, description="STT 텍스트 청크 (10~15초)")
    sequence:   int  = Field(..., description="청크 순서 번호 (0부터 증가)")
    timestamp:  int  = Field(..., description="UTC Unix Epoch Second")
    is_final:   bool = Field(..., description="어닝콜 세션 완전 종료 여부")

    # ── v3.0 확장 ────────────────────────────────────────────────────────────
    market_data: Optional[MarketData] = Field(None, description="퀀트 지표 묶음")

    class Config:
        json_schema_extra = {
            "example": {
                "ticker": "NVDA",
                "text_chunk": "Our data center revenue grew 409% year-over-year...",
                "sequence": 12,
                "timestamp": 1741827000,
                "is_final": False,
                "market_data": {
                    "rsi_14": 62.3,
                    "macd_signal": 0.025,
                    "volume_ratio": 2.8,
                    "vix": 16.4,
                    "earnings_surprise_pct": 15.2
                }
            }
        }
