# AI Engine 파일 설명서

이 문서는 현재 `ai_engine` 디렉토리의 핵심 파일을 빠르게 이해할 수 있도록 설명한다.

## 루트 파일

### `config.py`

- 런타임 설정을 관리한다.
- Gemini 모델, FinBERT phase-1 설정, Redis 채널, 게이트 임계치, 컨텍스트 크기, 연구용 목표 승률 등이 정의된다.
- `PHASE1_PROVIDER=finbert`가 기본값이다.

### `.env.example`

- 로컬 환경 변수 템플릿이다.
- Gemini 모델, FinBERT 모델, Redis 채널, warmup 옵션이 포함돼 있다.

### `main.py`

- FastAPI 앱 진입점이다.
- lifespan에서 `ContextManager`, `FiveGateFilter`, `IntegrationStateStore`, `RedisPublisher`를 초기화한다.
- 필요 시 `phase1_scorer.warmup()`도 수행한다.

### `requirements.txt`

- Python 의존성 목록이다.
- FastAPI, Redis, LangGraph, Gemini SDK, `transformers`, `torch`, 테스트 도구가 포함된다.

### `pytest.ini`

- 테스트 설정 파일이다.
- cacheprovider를 비활성화해 권한 경고 없이 테스트하도록 맞췄다.

## `api/`

### `api/analyze_router.py`

- 실시간 분석 API 메인 라우터다.
- `/api/v1/analyze`, `/api/v1/analyze/batch`를 제공한다.
- 처리 흐름:
  1. 세션 컨텍스트 적재
  2. collector 상태와 입력 market_data 병합
  3. `phase1_scorer`로 빠른 raw score 계산
  4. LangGraph 기반 Gemini 분석 수행
  5. 정량 점수, 게이트, 전략, 리스크 계산
  6. Backend 계약 JSON과 내부 확장 신호를 Redis에 발행

### `api/integration_router.py`

- collector, 웹 라이브룸, 데스크탑 콜백을 위한 호환 라우터다.

### `api/research_router.py`

- 연구용 API 라우터다.
- 백테스트와 운용 스타일 추천을 제공한다.

## `core/`

### `core/analysis_service.py`

- 프롬프트 생성과 Gemini 호출 오케스트레이션을 담당한다.
- 토큰 예산, prompt compaction, consensus 호출이 여기에 있다.

### `core/backtester.py`

- 연구용 백테스트 계산 로직이다.
- 승률, 평균 수익률, 샤프, 최대 낙폭, 전략별 통계를 계산한다.

### `core/composite_scorer.py`

- raw score, SUE, momentum, volume 신호를 합성해 composite score를 계산한다.

### `core/context_manager.py`

- 티커 또는 콜 세션별 슬라이딩 컨텍스트를 유지한다.

### `core/contract_adapter.py`

- 내부 `TradingSignalV3`를 Backend 최소 Redis 계약으로 변환한다.

### `core/execution_style.py`

- 시그널 특성과 시장 유동성을 바탕으로 intraday / swing / scalp / no-trade를 추천한다.

### `core/five_gate_filter.py`

- 최종 매매 승인 여부를 판단하는 게이트 필터다.

### `core/gemini_client.py`

- Gemini SDK raw transport와 응답 파싱을 담당한다.
- modern SDK와 legacy SDK를 모두 지원한다.

### `core/integration_state.py`

- collector와 데스크탑에서 들어오는 상태를 임시 저장하는 in-memory store다.

### `core/integrity_validator.py`

- LLM 결과 방향성과 원문 텍스트 방향성의 불일치를 검사한다.

### `core/llm_consistency.py`

- 여러 Gemini 샘플 결과를 합의 기반으로 집계한다.

### `core/pead_calculator.py`

- 실적 서프라이즈 기반 SUE/PEAD 보조 지표를 계산한다.

### `core/phase1_scorer.py`

- 1차 raw score 산출 단계다.
- 기본 경로는 `ProsusAI/finbert` 로컬 추론이다.
- 특징:
  - lazy load
  - LRU cache
  - device auto 선택
  - lexical fallback
- 역할:
  - 빠른 raw score 계산
  - Gemini 실패 시 fallback 분석 힌트 제공

### `core/prompt_builder.py`

- 현재 chunk, 이전 context, market data를 합쳐 Gemini 프롬프트를 구성한다.

### `core/redis_publisher.py`

- 기본 채널에는 Backend 최소 계약을 발행한다.
- `trading-signals-enriched`에는 내부 확장 신호를 함께 발행할 수 있다.

### `core/regime_classifier.py`

- VIX와 시장 상태를 바탕으로 시장 레짐을 분류한다.

### `core/risk_manager.py`

- 포지션 크기, 손절, 익절, 신호 강도를 계산한다.

### `core/score_normalizer.py`

- Gemini 결과를 raw score로 정규화한다.

### `core/token_budgeter.py`

- 프롬프트 길이 기반으로 모델 라우팅과 compact 필요 여부를 계산한다.

## `models/`

### `models/contract_models.py`

- Backend Redis 최소 계약 모델을 정의한다.

### `models/integration_models.py`

- collector ingest, market context, desktop feedback, live-room view 모델을 정의한다.

### `models/request_models.py`

- 분석 요청 입력 모델과 `MarketData` 구조를 정의한다.

### `models/research_models.py`

- 연구용 API 입력 모델을 정의한다.

### `models/signal_models.py`

- 내부 분석 결과와 최종 시그널 모델을 정의한다.

## `src/graph/`

### `src/graph/workflow.py`

- LangGraph 기반 Gemini 호출 그래프의 진입점이다.

### `src/graph/nodes/llm_call.py`

- Gemini 호출 노드 구현이다.

### `src/graph/state.py`

- 그래프 상태 모델을 정의한다.

## `strategies/`

### `strategies/orchestrator.py`

- 시그널과 시장 데이터를 기반으로 전략 태그를 결정한다.

## `tests/`

### `tests/test_core.py`

- 핵심 계산 로직 테스트다.

### `tests/test_research_extensions.py`

- consensus, token budget, execution style, 백테스트 확장 테스트다.

### `tests/test_integration_state.py`

- collector 상태 병합과 live-room 비매매 뷰 테스트다.

### `tests/test_contract_compatibility.py`

- phase-1 raw score, FinBERT 확률 매핑, Backend Redis 계약 변환 테스트다.
