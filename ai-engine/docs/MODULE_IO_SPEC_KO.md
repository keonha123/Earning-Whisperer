# AI Engine Module I/O Spec

## 목적

이 문서는 `ai_engine` 내부 모듈별 입력 구성, 입력 타입, 출력 구성, 출력 타입을 빠르게 확인하기 위한 I/O 계약 문서입니다.

## 1. 최상위 런타임 진입점

### `main.py`

| 항목 | 내용 |
|---|---|
| 역할 | FastAPI 앱 생성, lifespan 초기화, 공용 의존성 주입, `/health`, `/stats` 노출 |
| 주요 입력 | 환경변수 기반 `Settings` |
| 주요 출력 | `FastAPI` app 인스턴스 |
| 초기화 대상 | `ContextManager`, `FiveGateFilter`, `IntegrationStateStore`, `RedisPublisher`, `Phase1Scorer` |

### `config.py`

| 항목 | 내용 |
|---|---|
| 역할 | 전역 설정 로딩과 검증 |
| 입력 | `.env`, 환경변수 |
| 출력 | `Settings` |
| 핵심 타입 | `str`, `int`, `float`, `bool`, `Literal[...]` |

## 2. API Router

### `api/analyze_router.py`

| 함수/엔드포인트 | 입력 | 타입 | 출력 | 타입 |
|---|---|---|---|---|
| `POST /api/v1/analyze` | 분석 요청 | `AnalyzeRequest` | 접수 응답 | `dict` |
| `POST /api/v1/analyze/batch` | 배치 분석 요청 | `AnalyzeBatchRequest` | 접수 응답 | `dict` |
| `_run_pipeline()` | 단일 분석 요청 | `AnalyzeRequest` | 없음, 내부 publish | `None` |
| `_compute_momentum_score()` | 시장 데이터 | `MarketData \| None` | 모멘텀 점수 | `float \| None` |

#### `_run_pipeline()` 내부 단계별 I/O

| 단계 | 입력 | 출력 |
|---|---|---|
| 컨텍스트 적재 | `session_key`, `ChunkRecord` | 최근 `context_chunks` |
| phase-1 | `text_chunk` | `Phase1ScoreResult` |
| Gemini 분석 | `ticker`, `current_chunk`, `context_chunks`, `market_data`, `section_type`, `request_priority`, `is_final`, `phase1_result` | `GeminiAnalysisResult` |
| raw score 정규화 | `GeminiAnalysisResult` | `llm_raw_score: float` |
| raw score blend | `phase1_score`, `llm_score`, `llm_available` | `raw_score: float` |
| 정량 지표 계산 | `MarketData` | `sue_score`, `momentum_score`, `composite_score`, `regime`, `adj_composite` |
| 규칙 필터 | composite/market/LLM 결과 | `FilterResult` |
| 전략 선택 | `MarketData`, `GeminiAnalysisResult`, `raw_score` | `(StrategyName, hold_days, whisper_signal, sector_contagion)` |
| 리스크 산출 | `adj_composite`, `confidence`, `MarketData` | `RiskParameters` |
| 최종 신호 생성 | 위 모든 결과 | `TradingSignalV3` |
| Backend 계약 변환 | `TradingSignalV3`, `is_session_end` | `BackendRedisSignal` |
| 발행 | `TradingSignalV3`, `BackendRedisSignal` | `bool` |

### `api/integration_router.py`

| 엔드포인트 | 입력 | 타입 | 출력 | 타입 |
|---|---|---|---|---|
| `GET /api/v1/integration/capabilities` | 없음 | - | 현재 통합 가능 기능 | `dict` |
| `POST /collector/schedules` | 일정 배치 | `EarningsScheduleBatchRequest` | accepted 응답 | `dict` |
| `POST /collector/universe` | 종목 universe | `CompanyUniverseBatchRequest` | accepted 응답 | `dict` |
| `POST /collector/indicator-snapshots` | 종목 지표 스냅샷 | `IndicatorSnapshotBatchRequest` | accepted 응답 | `dict` |
| `POST /collector/market-context` | 시장 평가 스냅샷 | `MarketContextSnapshot` | accepted 응답 | `dict` |
| `POST /collector/transcript-chunk` | collector용 transcript ingest | `TranscriptChunkIngestRequest` | accepted 응답 | `dict` |
| `POST /desktop/execution-feedback` | desktop 체결 피드백 | `DesktopExecutionFeedbackRequest` | accepted 응답 | `dict` |
| `GET /live-room/{ticker}` | `ticker`, `call_id`, `event_id` | `str`, `Query` | 라이브룸 분석 뷰 | `LiveRoomSignalView -> dict` |
| `GET /collector/state/{ticker}` | `ticker` | `str` | ticker snapshot | `dict` |

### `api/research_router.py`

| 엔드포인트 | 입력 | 타입 | 출력 | 타입 |
|---|---|---|---|---|
| `POST /api/v1/research/backtest` | 백테스트 레코드 | `BacktestRequest` | 백테스트/게이트/운용모드 | `dict` |
| `POST /api/v1/research/style` | 스타일 추천 요청 | `StyleRecommendationRequest` | execution style 결과 | `dict` |

## 3. Core 분석/LLM 계층

### `core/analysis_service.py`

| 함수 | 입력 | 타입 | 출력 | 타입 |
|---|---|---|---|---|
| `build_prompt()` | ticker, chunk, context, market, profile, policy, review info | 혼합 | 프롬프트 문자열 | `str` |
| `analyze()` | `ticker`, `current_chunk`, `context_chunks`, `market_data`, `section_type`, `request_priority`, `is_final`, `phase1_result` | 혼합 | 최종 LLM 결과 | `GeminiAnalysisResult` |
| `analyze_prompt()` | 임의 프롬프트 | `str` | 직접 LLM 결과 | `GeminiAnalysisResult` |
| `get_stats()` | 없음 | - | 라우팅 통계 | `dict[str, object]` |

### `core/gemini_client.py`

| 함수 | 입력 | 타입 | 출력 | 타입 |
|---|---|---|---|---|
| `generate_content()` | `model`, `contents`, `config` | `str`, `str`, `dict` | raw 응답 텍스트 | `str` |
| `parse_response_text()` | raw 텍스트 | `str` | 구조화 결과 | `GeminiAnalysisResult` |
| `analyze()` | prompt | `str` | 구조화 결과 | `GeminiAnalysisResult` |
| `get_stats()` | 없음 | - | Gemini 호출 통계 | `dict[str, Any]` |

#### Gemini `config` 딕셔너리 구성

| key | 타입 | 설명 |
|---|---|---|
| `system_instruction` | `str` | 시스템 프롬프트 |
| `max_output_tokens` | `int` | 최대 출력 토큰 |
| `response_mime_type` | `str` | 기본 `application/json` |
| `thinking_level` | `str` | `minimal/low/medium/high` |

### `core/llm_router.py`

| 함수 | 입력 | 출력 |
|---|---|---|
| `decide_route()` | `current_chunk`, `context_chunks`, `market_data`, `section_type`, `request_priority`, `is_final`, `phase1_raw_score` | `RouteDecision` |
| `normalized_overlap_ratio()` | 이전 청크, 현재 청크 | `float` |
| `trim_transcript_overlap()` | 이전 청크, 현재 청크 | `str` |

#### `RouteDecision` 필드

| 필드 | 타입 |
|---|---|
| `route_profile` | `str` |
| `context_policy` | `str` |
| `primary_model` | `str` |
| `review_model` | `str` |
| `primary_max_output_tokens` | `int` |
| `review_max_output_tokens` | `int` |
| `primary_thinking_level` | `str` |
| `review_thinking_level` | `str` |
| `novelty_score` | `float` |
| `overlap_ratio` | `float` |
| `estimated_prompt_tokens` | `int` |
| `important_chunk` | `bool` |

### `core/prompt_builder.py`

| 함수 | 입력 | 출력 |
|---|---|---|
| `build_prompt()` | ticker, current_chunk, context_chunks, market_data, prompt_profile, context_policy, phase1_score, previous_result, review_reason | `str` |

#### prompt profile 종류

| 값 | 의미 |
|---|---|
| `economy` | 1문장 rationale, 최소 market field, 짧은 CoT |
| `standard` | 2문장 rationale, full rolling context |
| `adjudication` | 1차 결과 재판정, review reason 포함 |

#### context policy 종류

| 값 | 의미 |
|---|---|
| `delta` | 현재 청크에서 overlap 제거 + 직전 anchor |
| `rolling` | rolling context + 현재 청크 |
| `adjudication` | 현재 청크 + 1차 결과 + review 정보 |

### `core/llm_consistency.py`

| 함수 | 입력 | 출력 |
|---|---|---|
| `should_request_review()` | `primary_result`, `phase1_raw_score`, `phase1_confidence`, `important_chunk`, `section_type`, `current_chunk`, `integrity_valid`, `integrity_reason`, `primary_parse_failed` | `ReviewDecision` |
| `should_run_consensus()` | `GeminiAnalysisResult`, `prompt_tokens` | `bool` |
| `aggregate_consensus()` | `Iterable[GeminiAnalysisResult]` | `GeminiAnalysisResult` |

## 4. Core 점수화/필터 계층

### `core/phase1_scorer.py`

| 함수/메서드 | 입력 | 출력 |
|---|---|---|
| `analyze_text()` | `text: str` | `Phase1ScoreResult` |
| `warmup()` | 없음 | `None` |
| `status_snapshot()` | 없음 | `dict[str, object]` |
| `fallback_gemini_result()` | `text`, `phase1_result` | `GeminiAnalysisResult` |
| `blend_raw_scores()` | `phase1_score`, `llm_score`, `llm_available` | `float` |

#### `Phase1ScoreResult`

| 필드 | 타입 |
|---|---|
| `raw_score` | `float` |
| `confidence` | `float` |
| `provider` | `str` |
| `rationale_hint` | `str` |

### `core/score_normalizer.py`

| 함수 | 입력 | 출력 |
|---|---|---|
| `compute_raw_score()` | `GeminiAnalysisResult` | `float` |
| `compute_raw_score_batch()` | `list[GeminiAnalysisResult]` | `numpy.ndarray` |

### `core/pead_calculator.py`

| 함수 | 입력 | 출력 |
|---|---|---|
| `calculate_sue_score()` | `MarketData \| None` | `float \| None` |
| `classify_pead_signal()` | `sue_score: float` | `str` |

### `core/composite_scorer.py`

| 함수 | 입력 | 출력 |
|---|---|---|
| `calculate_composite_score()` | `raw_score`, `sue_score`, `momentum_score`, `volume_ratio` | `float` |
| `get_score_breakdown()` | 동일 | `ScoreBreakdown` |

#### `ScoreBreakdown`

| 필드 | 타입 |
|---|---|
| `sentiment_contrib` | `float` |
| `pead_contrib` | `float` |
| `momentum_contrib` | `float` |
| `volume_contrib` | `float` |
| `composite` | `float` |

### `core/regime_classifier.py`

| 함수 | 입력 | 출력 |
|---|---|---|
| `classify_regime()` | `MarketData \| None` | `MarketRegime` |
| `apply_regime_multiplier()` | `composite_score`, `regime` | `float` |

### `core/five_gate_filter.py`

| 함수 | 입력 | 출력 |
|---|---|---|
| `apply()` | composite/raw/confidence/euphemism/sue/momentum/market/llm/regime | `FilterResult` |
| `get_pass_rates()` | 없음 | `dict[str, float \| None]` |

#### `FilterResult`

| 필드 | 타입 |
|---|---|
| `trade_approved` | `bool` |
| `failed_gates` | `list[GateLabel]` |
| `gate_results` | `list[GateResult]` |
| `adj_composite` | `float` |

## 5. 전략/리스크/백테스트 계층

### `strategies/orchestrator.py`

| 함수 | 입력 | 출력 |
|---|---|---|
| `select_strategy()` | `MarketData \| None`, `GeminiAnalysisResult`, `raw_score: float` | `(StrategyName, int, WhisperSignal \| None, bool)` |

### `core/risk_manager.py`

| 함수 | 입력 | 출력 |
|---|---|---|
| `determine_signal_strength()` | `adj_composite: float` | `SignalStrength` |
| `calculate_position_size()` | `adj_composite`, `confidence`, `MarketData \| None` | `float` |
| `calculate_stop_take_profit()` | `signal_strength`, `current_price`, `atr_14`, `is_long` | tuple |
| `calculate_risk_parameters()` | `adj_composite`, `confidence`, `MarketData \| None` | `RiskParameters` |

### `core/backtester.py`

| 함수 | 입력 | 출력 |
|---|---|---|
| `run_backtest()` | `list[SignalRecord]` | `BacktestResult` |
| `recommend_gate_adjustment()` | `BacktestResult` | `(action: str, reason: str)` |
| `recommend_operating_mode()` | `BacktestResult` | `dict[str, object]` |

#### `SignalRecord`

| 필드 | 타입 |
|---|---|
| `ticker` | `str` |
| `timestamp` | `int` |
| `composite_score` | `float` |
| `raw_score` | `float` |
| `trade_approved` | `bool` |
| `strategy` | `str` |
| `actual_return` | `float \| None` |

#### `BacktestResult`

| 필드 | 타입 |
|---|---|
| `total_signals` | `int` |
| `approved_signals` | `int` |
| `win_count` | `int` |
| `loss_count` | `int` |
| `win_rate` | `float` |
| `avg_return` | `float` |
| `sharpe_ratio` | `float` |
| `max_drawdown` | `float` |
| `strategy_stats` | `dict[str, dict]` |
| `gate_approval_rate` | `float` |
| `avg_trades_per_day` | `float` |
| `target_win_rate` | `float` |
| `meets_target_win_rate` | `bool` |

## 6. 상태/계약 계층

### `core/context_manager.py`

| 함수 | 입력 | 출력 |
|---|---|---|
| `update()` | `session_key`, `ChunkRecord`, `is_final` | `None` |
| `get_context()` | `session_key` | `list[ChunkRecord]` |
| `get_active_tickers()` | 없음 | `list[str]` |
| `cleanup_expired()` | 없음 | `int` |

### `core/contract_adapter.py`

| 함수 | 입력 | 출력 |
|---|---|---|
| `to_backend_redis_signal()` | `TradingSignalV3`, `is_session_end: bool` | `BackendRedisSignal` |

### `core/redis_publisher.py`

| 함수 | 입력 | 출력 |
|---|---|---|
| `connect()` | 없음 | `None` |
| `disconnect()` | 없음 | `None` |
| `publish()` | `TradingSignalV3`, `BackendRedisSignal` | `bool` |

## 7. 주요 모델 I/O

### `AnalyzeRequest`

| 필드 | 타입 |
|---|---|
| `ticker` | `str` |
| `text_chunk` | `str` |
| `sequence` | `int` |
| `timestamp` | `int` |
| `is_final` | `bool` |
| `market_data` | `MarketData \| None` |
| `call_id` | `str \| None` |
| `event_id` | `str \| None` |
| `batch_id` | `str \| None` |
| `source_type` | `SourceType \| None` |
| `section_type` | `SectionType \| None` |
| `speaker_role` | `str \| None` |
| `speaker_name` | `str \| None` |
| `transcript_language` | `str \| None` |
| `request_priority` | `int` |

### `BackendRedisSignal`

| 필드 | 타입 |
|---|---|
| `ticker` | `str` |
| `raw_score` | `float` |
| `rationale` | `str` |
| `text_chunk` | `str` |
| `timestamp` | `int` |
| `is_session_end` | `bool` |

### `TradingSignalV3`

| 필드 | 타입 |
|---|---|
| `ticker` | `str` |
| `raw_score` | `float` |
| `rationale` | `str` |
| `text_chunk` | `str` |
| `timestamp` | `int` |
| `composite_score` | `float \| None` |
| `sue_score` | `float \| None` |
| `momentum_score` | `float \| None` |
| `trade_approved` | `bool \| None` |
| `primary_strategy` | `StrategyName \| None` |
| `signal_strength` | `SignalStrength \| None` |
| `position_pct` | `float \| None` |
| `market_regime` | `MarketRegime \| None` |
| `catalyst_type` | `CatalystType \| None` |
| `stop_loss_price` | `float \| None` |
| `take_profit_price` | `float \| None` |
| `stop_loss_pct` | `float \| None` |
| `take_profit_pct` | `float \| None` |
| `profit_factor` | `float \| None` |
| `hold_days_max` | `int \| None` |
| `failed_gates` | `list[GateLabel] \| None` |
| `whisper_signal` | `WhisperSignal \| None` |
| `sector_contagion` | `bool \| None` |
| `cot_reasoning` | `str \| None` |
