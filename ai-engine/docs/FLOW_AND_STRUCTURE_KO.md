# AI Engine Flow And Structure

## 1. 엔진의 전체 흐름

### 입력

- `POST /api/v1/analyze`
- `POST /api/v1/analyze/batch`
- collector 또는 data pipeline 이 어닝콜 STT 청크와 시장 데이터를 전달

### 처리 단계

1. `api/analyze_router.py`
   요청 검증, 세션 키 생성, 배치/비동기 파이프라인 진입
2. `core/context_manager.py`
   `ticker:call_id` 또는 `ticker:event_id` 기준으로 최근 청크를 유지
3. `core/phase1_scorer.py`
   FinBERT 우선 phase-1 raw score 생성, 실패 시 lexical fallback
4. `core/analysis_service.py`
   graph workflow를 통해 Gemini 분석 orchestration 수행
5. `src/graph/workflow.py`
   `route_decision -> build_prompt -> primary_llm_call -> review_gate -> adjudication_llm_call -> parse_and_finalize`
6. `core/score_normalizer.py`
   Gemini 결과를 raw score로 정규화
7. `core/pead_calculator.py`
   EPS surprise 기반 SUE 계산
8. `api/analyze_router.py::_compute_momentum_score`
   MACD, RSI, BB position 기반 모멘텀 계산
9. `core/composite_scorer.py`
   sentiment, SUE, momentum, volume을 합쳐 composite score 계산
10. `core/regime_classifier.py`
    시장 국면 분류 및 composite 조정
11. `core/five_gate_filter.py`
    G1~G5 규칙으로 trade approval 판정
12. `strategies/orchestrator.py`
    Gap-and-go, whisper play 등 전략 선택
13. `core/risk_manager.py`
    position size, stop loss, take profit 계산
14. `models/signal_models.py`
    `TradingSignalV3` 생성
15. `core/contract_adapter.py`
    Backend Redis 최소 계약 형태로 변환
16. `core/redis_publisher.py`
    `trading-signals`와 `trading-signals-enriched` 채널 발행

### 출력

- 내부 풍부한 신호: `TradingSignalV3`
- Backend 계약 신호: `BackendRedisSignal`

## 2. 모듈별 책임

### `api/`

- `analyze_router.py`
  실시간 분석 진입점, 전체 파이프라인 조립
- `integration_router.py`
  collector, desktop, live-room 통합용 엔드포인트
- `research_router.py`
  백테스트와 execution-style 추천 엔드포인트

### `core/`

- `analysis_service.py`
  Gemini 분석 orchestration 및 라우팅 통계 집계
- `gemini_client.py`
  modern SDK / legacy SDK 호환 Gemini transport
- `llm_router.py`
  economy vs standard, delta vs rolling, review escalation 판단
- `prompt_builder.py`
  economy, standard, adjudication 프롬프트 구성
- `llm_consistency.py`
  live review 조건 및 research consensus 유틸
- `phase1_scorer.py`
  FinBERT 기반 초기 점수화
- `context_manager.py`
  세션 컨텍스트 저장과 TTL cleanup
- `redis_publisher.py`
  Redis publish, reconnect, backup queue
- `backtester.py`
  전략 성과 요약, Sharpe, MDD, 운용 모드 추천
- `five_gate_filter.py`
  trade gate 통과 여부와 pass-rate 통계

### `models/`

- `request_models.py`
  분석 입력 계약
- `signal_models.py`
  엔진 내부/최종 신호 모델
- `contract_models.py`
  Backend Redis 최소 계약
- `research_models.py`
  백테스트 요청/응답 모델

### `src/graph/`

- `workflow.py`
  LangGraph 또는 fallback sequential workflow 구성
- `state.py`
  graph state 정의
- `nodes/`
  route/prompt/call/review/finalize 노드 구현

### `strategies/`

- `orchestrator.py`
  이벤트 성격과 시장 상태에 따라 주 전략 선택

### `tests/`

- 계약 호환성
- 핵심 연산 모듈
- 라우팅 회귀
- inspection 회귀
- 운영 guard 테스트

## 3. GitHub 업로드 시 포함 권장 범위

- `api/`
- `core/`
- `docs/`
- `models/`
- `src/`
- `strategies/`
- `tests/`
- `.env.example`
- `.gitignore`
- `config.py`
- `main.py`
- `pytest.ini`
- `requirements.txt`
- `README.md`

## 4. 업로드 시 제외 권장 범위

- `.env`
- `__pycache__/`
- `pytest-cache-files-*`
- 로컬 zip 산출물
- 개인 실험 스크립트

## 5. 배포 전 확인 항목

- `GEMINI_API_KEY`
- `REDIS_URL`
- FinBERT 모델 캐시 또는 초기 다운로드 가능 여부
- `/health` 확인
- `/stats`에서 `redis_connected`, `phase1_status`, `gemini_stats` 확인
