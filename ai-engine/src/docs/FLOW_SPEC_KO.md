# AI Engine Flow Spec

## 목적

이 문서는 엔진 전체 흐름을 단계별로 설명하는 운영 관점의 flow 문서입니다. 입력이 어디서 들어오고 어떤 모듈을 거쳐 어떤 출력으로 끝나는지, 그리고 batch, integration, research flow까지 함께 정리합니다.

## 1. 실시간 분석 메인 플로우

```text
Collector / Data Pipeline
    -> POST /api/v1/analyze
    -> enqueue_analysis_request()
    -> _run_pipeline()
    -> ContextManager.update()
    -> Phase1Scorer.analyze_text()
    -> AnalysisService.analyze()
         -> route_decision
         -> build_prompt
         -> primary_llm_call
         -> review_gate
         -> adjudication_llm_call (optional)
         -> parse_and_finalize
    -> compute_raw_score()
    -> calculate_sue_score()
    -> _compute_momentum_score()
    -> calculate_composite_score()
    -> classify_regime()
    -> apply_regime_multiplier()
    -> FiveGateFilter.apply()
    -> StrategyOrchestrator.select_strategy()
    -> calculate_risk_parameters()
    -> TradingSignalV3
    -> BackendRedisSignal
    -> RedisPublisher.publish()
```

## 2. 단계별 상세

### Step 1. API 진입

파일:
- `api/analyze_router.py`

역할:
- 입력 검증
- 빈 텍스트 차단
- background task로 실분석 파이프라인 분리
- 단일/배치 요청 모두 동일한 `_run_pipeline()`을 사용

입력:
- `AnalyzeRequest`

출력:
- 즉시 `accepted` 응답
- 실제 분석 결과는 Redis publish로 전달

### Step 2. 세션 컨텍스트 관리

파일:
- `core/context_manager.py`

역할:
- `ticker`, `call_id`, `event_id`, `batch_id`를 기반으로 세션 키 구성
- 최근 N개 청크 유지
- 세션 TTL cleanup
- final 청크 수신 시 세션 close

핵심 포인트:
- 세션 키 예시: `NVDA:NVDA-2026Q1`
- multi-call 상황에서도 ticker 단위가 아니라 call/event 단위로 격리

### Step 3. Phase-1 점수화

파일:
- `core/phase1_scorer.py`

역할:
- 먼저 빠른 방향성 점수 생성
- FinBERT 우선
- 로딩 실패 또는 inference 실패 시 lexical fallback

출력:
- `Phase1ScoreResult`

### Step 4. Gemini 라우팅 분석

파일:
- `core/analysis_service.py`
- `core/llm_router.py`
- `core/prompt_builder.py`
- `src/graph/workflow.py`
- `src/graph/nodes/*`

역할:
- 청크 중요도와 novelty 기반 route 선택
- 비용 절감형 `economy` 또는 정보 보존형 `standard` 선택
- Flash 1차 호출
- 필요 시 Pro adjudication
- 최종 JSON parse

핵심 정책:
- 모든 청크는 최소 1회 LLM 호출
- 라이브 경로 최대 2회 호출
- 기본: `gemini-3-flash-preview`
- review: `gemini-3-pro-preview`

### Step 5. raw score 정규화

파일:
- `core/score_normalizer.py`

역할:
- `GeminiAnalysisResult`를 거래 가능한 raw score로 변환
- direction, magnitude, confidence, euphemism 등의 영향을 반영

### Step 6. 정량 피처 계산

파일:
- `core/pead_calculator.py`
- `api/analyze_router.py::_compute_momentum_score`
- `core/composite_scorer.py`

역할:
- SUE 계산
- 기술적 모멘텀 계산
- 거래량 점수 계산
- sentiment + pead + momentum + volume 합성

### Step 7. 시장 국면 보정

파일:
- `core/regime_classifier.py`

역할:
- VIX와 일부 technical 상태를 이용해 regime 분류
- extreme fear/high volatility에서 composite 강도 조정

### Step 8. 5-Gate 필터

파일:
- `core/five_gate_filter.py`

게이트:
- `G1`: 신뢰도 및 score quality
- `G2`: PEAD 방향 일치
- `G3`: 모멘텀 충돌 여부
- `G4`: 거래량/스프레드/유동성
- `G5`: 시장 국면 / VIX 차단

출력:
- `FilterResult`

### Step 9. 전략/리스크 산출

파일:
- `strategies/orchestrator.py`
- `core/risk_manager.py`

역할:
- primary strategy 선택
- 보유 일수 추천
- whisper signal / sector contagion 판정
- position sizing, stop loss, take profit 계산

### Step 10. 최종 신호와 발행

파일:
- `models/signal_models.py`
- `core/contract_adapter.py`
- `core/redis_publisher.py`

역할:
- `TradingSignalV3` 생성
- Backend용 최소 계약 `BackendRedisSignal` 생성
- `trading-signals`와 optional enriched 채널 발행

## 3. 배치 플로우

파일:
- `api/analyze_router.py`

흐름:

```text
POST /api/v1/analyze/batch
    -> AnalyzeBatchRequest
    -> _run_batch_pipeline()
    -> asyncio.Semaphore(max_concurrency)
    -> 각 item 마다 _run_pipeline()
```

특징:
- `ANALYSIS_BATCH_CONCURRENCY` 상한 적용
- 단일 파이프라인 로직 재사용

## 4. Integration 플로우

파일:
- `api/integration_router.py`
- `core/integration_state.py`

### 4-1. Collector 데이터 적재

```text
/collector/schedules
/collector/universe
/collector/indicator-snapshots
/collector/market-context
    -> IntegrationStateStore 저장
```

### 4-2. Collector transcript ingest

```text
/collector/transcript-chunk
    -> TranscriptChunkIngestRequest
    -> enqueue_analysis_request()
    -> 메인 분석 플로우 재사용
```

### 4-3. Desktop 피드백

```text
/desktop/execution-feedback
    -> DesktopExecutionFeedbackRequest
    -> IntegrationStateStore.record_execution_feedback()
```

### 4-4. Web live-room 조회

```text
/live-room/{ticker}
    -> IntegrationStateStore.get_live_room_view()
    -> LiveRoomSignalView 반환
```

## 5. Research 플로우

파일:
- `api/research_router.py`
- `core/backtester.py`
- `core/execution_style.py`

### 5-1. Backtest

```text
POST /api/v1/research/backtest
    -> BacktestRequest
    -> SignalRecord list 변환
    -> run_backtest()
    -> recommend_gate_adjustment()
    -> recommend_operating_mode()
```

### 5-2. Style Recommendation

```text
POST /api/v1/research/style
    -> StyleRecommendationRequest
    -> recommend_execution_style()
```

## 6. 모니터링 플로우

### `/health`

반환:
- 현재 primary model
- review model
- app version

### `/stats`

반환:
- active tickers
- Gemini stats
- route counts
- flash only 비율
- pro escalation 비율
- prompt/output token 추정치
- phase1 status
- gate pass rates
- Redis 연결 상태
- integration state readiness

## 7. 실패 및 fallback 플로우

### Redis 실패

```text
Redis publish 실패
    -> primary backup queue 저장
    -> enriched backup queue 저장
    -> 다음 reconnect 시 flush
```

### Gemini 실패

```text
primary parse 실패
    -> review 가능 시 Pro adjudication
    -> review budget 불가 시 neutral fallback
```

### FinBERT 실패

```text
FinBERT warmup/init/inference 실패
    -> lexical fallback
    -> phase1 provider = lexical_phase1
```

## 8. 운영 관점 요약

- 실시간 메인 경로는 background task 기반 비동기
- 세션 컨텍스트는 call/event 단위로 분리
- phase-1은 로컬 우선, Gemini는 route-aware 비용 절감형
- final trade decision은 LLM 단독이 아니라 quant + gate + regime + risk를 거침
- Backend와의 계약은 Redis 최소 계약으로 분리되어 있음
