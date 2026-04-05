# AI Engine Technical Spec Table

## 1. 서비스 개요

| 항목 | 값 |
|---|---|
| 서비스명 | EarningWhisperer AI Engine |
| 현재 버전 | `3.5.2` |
| 런타임 | Python 3.10+ |
| 프레임워크 | FastAPI |
| 비동기 모델 | `asyncio` |
| 실시간 LLM | Gemini 3.x |
| phase-1 모델 | FinBERT with lexical fallback |
| 메시징 | Redis Pub/Sub |
| 주요 출력 | `TradingSignalV3`, `BackendRedisSignal` |

## 2. 주요 기술 스택

| 분류 | 기술 |
|---|---|
| API | FastAPI, Uvicorn |
| 설정 | pydantic, pydantic-settings |
| LLM | `google-genai`, `google-generativeai` fallback |
| 로컬 ML | `transformers`, `torch` |
| 수치 계산 | `numpy` |
| 그래프 오케스트레이션 | `langgraph` with fallback sequential workflow |
| 메시징 | `redis.asyncio` |
| 테스트 | `pytest`, `pytest-asyncio`, `fastapi.testclient` |

## 3. 환경변수 기술 명세

### 필수

| 키 | 타입 | 기본값 | 설명 |
|---|---|---|---|
| `GEMINI_API_KEY` | `str` | `""` | Gemini API 키 |
| `REDIS_URL` | `str` | `redis://localhost:6379` | Redis 연결 URL |

### Gemini / Routing

| 키 | 타입 | 기본값 |
|---|---|---|
| `GEMINI_PRIMARY_MODEL` | `str` | `gemini-3-flash-preview` |
| `GEMINI_REVIEW_MODEL` | `str` | `gemini-3-pro-preview` |
| `GEMINI_PRIMARY_MAX_OUTPUT_TOKENS` | `int` | `384` |
| `GEMINI_STANDARD_MAX_OUTPUT_TOKENS` | `int` | `640` |
| `GEMINI_REVIEW_MAX_OUTPUT_TOKENS` | `int` | `960` |
| `GEMINI_PRIMARY_THINKING_LEVEL` | `str` | `minimal` |
| `GEMINI_STANDARD_THINKING_LEVEL` | `str` | `low` |
| `GEMINI_REVIEW_THINKING_LEVEL` | `str` | `medium` |
| `LLM_ROUTER_MAX_CALLS_PER_CHUNK` | `int` | `2` |
| `LLM_ROUTER_NOVELTY_THRESHOLD` | `float` | `0.18` |
| `LLM_ROUTER_HIGH_SIGNAL_RAW_THRESHOLD` | `float` | `0.45` |
| `LLM_ROUTER_HIGH_PRIORITY` | `int` | `8` |
| `LLM_ROUTER_REVIEW_CONFIDENCE_THRESHOLD` | `float` | `0.68` |

### Phase-1

| 키 | 타입 | 기본값 |
|---|---|---|
| `PHASE1_PROVIDER` | `Literal[finbert, lexical]` | `finbert` |
| `PHASE1_FINBERT_MODEL_NAME` | `str` | `ProsusAI/finbert` |
| `PHASE1_FINBERT_DEVICE` | `Literal[auto, cpu, cuda]` | `auto` |
| `PHASE1_FINBERT_MAX_LENGTH` | `int` | `256` |
| `PHASE1_MAX_CHARS` | `int` | `3000` |
| `PHASE1_CACHE_SIZE` | `int` | `1024` |
| `PHASE1_WARMUP_ON_STARTUP` | `bool` | `true` |

### Context / Throughput

| 키 | 타입 | 기본값 |
|---|---|---|
| `CONTEXT_HISTORY_SIZE` | `int` | `5` |
| `CONTEXT_SESSION_TTL_SECONDS` | `int` | `3600` |
| `ANALYSIS_MAX_PROMPT_TOKENS` | `int` | `12000` |
| `ANALYSIS_TARGET_CHUNK_TOKENS` | `int` | `2500` |
| `ANALYSIS_BATCH_CONCURRENCY` | `int` | `4` |

### Gate / Risk

| 키 | 타입 | 기본값 |
|---|---|---|
| `COMPOSITE_THRESHOLD` | `float` | `0.55` |
| `CONFIDENCE_THRESHOLD` | `float` | `0.82` |
| `RAW_SCORE_THRESHOLD` | `float` | `0.45` |
| `MAX_EUPHEMISM_COUNT` | `int` | `2` |
| `MIN_VOLUME_RATIO` | `float` | `1.80` |
| `MAX_VIX` | `float` | `25.0` |
| `KELLY_MAX_POSITION` | `float` | `0.25` |
| `EXECUTION_TARGET_WIN_RATE` | `float` | `0.50` |

## 4. 외부 인터페이스 명세

### Contract 1: Ingest

| 엔드포인트 | 메서드 | 입력 모델 | 출력 |
|---|---|---|---|
| `/api/v1/analyze` | `POST` | `AnalyzeRequest` | accepted `dict` |
| `/api/v1/analyze/batch` | `POST` | `AnalyzeBatchRequest` | accepted `dict` |

### Contract 2: Backend Redis

| 채널 | 페이로드 타입 |
|---|---|
| `trading-signals` | `BackendRedisSignal` |
| `trading-signals-enriched` | `TradingSignalV3` |

### Research API

| 엔드포인트 | 메서드 | 입력 | 출력 |
|---|---|---|---|
| `/api/v1/research/backtest` | `POST` | `BacktestRequest` | `backtest + gate_recommendation + operating_mode` |
| `/api/v1/research/style` | `POST` | `StyleRecommendationRequest` | execution style recommendation |

### Integration API

| 엔드포인트 | 메서드 | 입력 |
|---|---|---|
| `/api/v1/integration/collector/schedules` | `POST` | `EarningsScheduleBatchRequest` |
| `/api/v1/integration/collector/universe` | `POST` | `CompanyUniverseBatchRequest` |
| `/api/v1/integration/collector/indicator-snapshots` | `POST` | `IndicatorSnapshotBatchRequest` |
| `/api/v1/integration/collector/market-context` | `POST` | `MarketContextSnapshot` |
| `/api/v1/integration/collector/transcript-chunk` | `POST` | `TranscriptChunkIngestRequest` |
| `/api/v1/integration/desktop/execution-feedback` | `POST` | `DesktopExecutionFeedbackRequest` |
| `/api/v1/integration/live-room/{ticker}` | `GET` | `ticker`, `call_id`, `event_id` |

## 5. 핵심 모델 명세

### `AnalyzeRequest`

| 필드 | 타입 | 필수 |
|---|---|---|
| `ticker` | `str` | 예 |
| `text_chunk` | `str` | 예 |
| `sequence` | `int` | 예 |
| `timestamp` | `int` | 예 |
| `is_final` | `bool` | 예 |
| `market_data` | `MarketData \| None` | 아니오 |
| `call_id` | `str \| None` | 아니오 |
| `event_id` | `str \| None` | 아니오 |
| `batch_id` | `str \| None` | 아니오 |
| `source_type` | `SourceType \| None` | 아니오 |
| `section_type` | `SectionType \| None` | 아니오 |
| `speaker_role` | `str \| None` | 아니오 |
| `speaker_name` | `str \| None` | 아니오 |
| `transcript_language` | `str \| None` | 아니오 |
| `request_priority` | `int` | 아니오 |

### `MarketData`

대표 필드:

| 카테고리 | 필드 예시 | 타입 |
|---|---|---|
| 가격 | `prev_close`, `current_price`, `price_change_pct` | `float \| None` |
| 기술지표 | `rsi_14`, `macd_signal`, `bb_position`, `atr_14` | `float \| None` |
| 거래량/유동성 | `volume_ratio`, `premarket_volume_ratio`, `bid_ask_spread_bps`, `liquidity_score` | `float \| None` |
| 실적 | `earnings_surprise_pct`, `avg_analyst_est`, `whisper_eps` | `float \| None` |
| 시장 국면 | `vix` | `float \| None` |
| 옵션/포지셔닝 | `put_call_ratio`, `current_iv`, `iv_rank`, `implied_move_pct` | `float \| None` |
| 숏 데이터 | `short_interest_pct`, `days_to_cover` | `float \| None` |

### `GeminiAnalysisResult`

| 필드 | 타입 |
|---|---|
| `direction` | `str` |
| `magnitude` | `float` |
| `confidence` | `float` |
| `rationale` | `str` |
| `catalyst_type` | `str` |
| `euphemism_count` | `int` |
| `negative_word_ratio` | `float` |
| `cot_reasoning` | `str \| None` |
| `model_route` | `str \| None` |

### `TradingSignalV3`

| 카테고리 | 필드 |
|---|---|
| 기본 | `ticker`, `raw_score`, `rationale`, `text_chunk`, `timestamp` |
| 정량 | `composite_score`, `sue_score`, `momentum_score` |
| 판단 | `trade_approved`, `primary_strategy`, `signal_strength`, `market_regime`, `catalyst_type` |
| 리스크 | `position_pct`, `stop_loss_price`, `take_profit_price`, `stop_loss_pct`, `take_profit_pct`, `profit_factor`, `hold_days_max` |
| 설명 | `failed_gates`, `whisper_signal`, `sector_contagion`, `cot_reasoning` |

## 6. Graph Workflow 명세

| 노드 | 입력 | 출력 |
|---|---|---|
| `route_decision` | 기본 analyze state | routing config |
| `build_prompt` | routing config + context | `contents` |
| `primary_llm_call` | `contents`, `primary_model`, `primary_config` | `primary_result_text` |
| `review_gate` | `primary_result_text`, integrity/phase1 info | `needs_review`, `review_reason` |
| `adjudication_llm_call` | review state | `review_result_text` |
| `parse_and_finalize` | review or primary text | `GeminiAnalysisResult` |

## 7. 관측/운영 명세

### `/health`

| key | 타입 |
|---|---|
| `status` | `str` |
| `model` | `str` |
| `primary_model` | `str` |
| `review_model` | `str` |
| `version` | `str` |

### `/stats`

| key | 타입 |
|---|---|
| `active_tickers` | `list[str]` |
| `gemini_stats` | `dict` |
| `route_counts` | `dict[str, int]` |
| `flash_only_rate` | `float` |
| `pro_escalation_rate` | `float` |
| `avg_estimated_prompt_tokens` | `float` |
| `avg_estimated_output_tokens` | `float` |
| `economy_prompt_rate` | `float` |
| `phase1_status` | `dict` |
| `gate_pass_rates` | `dict[str, float \| None]` |
| `redis_connected` | `bool` |
| `redis_backup_queue` | `int` |
| `integration_state_ready` | `bool` |

## 8. 테스트 명세

| 테스트 파일 | 목적 |
|---|---|
| `test_contract_compatibility.py` | Redis/backend 계약 호환성 |
| `test_core.py` | 핵심 계산 모듈 단위 검증 |
| `test_llm_routing.py` | Gemini 3 라우팅과 graph 경로 검증 |
| `test_inspection_regressions.py` | 최근 검수 반영 회귀 |
| `test_operational_guards.py` | 운영 가드, legacy mapping, 1-call fallback, SDK 호환성 |
| `test_research_extensions.py` | research/backtest/style 관련 검증 |
| `test_integration_state.py` | integration state 검증 |
| `test_redis_publisher.py` | Redis queue/reconnect 동작 검증 |

## 9. 배포 전 체크리스트

| 항목 | 필수 여부 | 설명 |
|---|---|---|
| `GEMINI_API_KEY` | 필수 | Gemini 호출 |
| Redis 기동 | 필수 | Backend signal 발행 |
| FinBERT 모델 가용성 | 권장 | warmup 성공 또는 fallback 전략 확정 |
| `/health` 확인 | 필수 | 모델/버전 확인 |
| `/stats` 확인 | 필수 | Redis, phase1, gemini 상태 확인 |
