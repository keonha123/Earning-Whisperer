# Update Summary Through v3.5.2

## 목적

이 문서는 현재 GitHub 업로드 기준 버전인 `v3.5.2`까지 반영된 주요 업데이트를 요약한 문서입니다. 무엇이 새로 들어갔고, 무엇이 바뀌었고, 어떤 운영 리스크가 닫혔는지를 빠르게 확인할 수 있습니다.

## 1. 큰 방향 변화

### 1-1. 구조 분리

- router, core, models, graph, strategies, tests 구조로 정리
- Backend 계약, collector 호환, desktop 콜백, research/backtest 경로를 각각 분리
- 실시간 분석 경로와 연구/검증 경로가 섞이지 않도록 정리

### 1-2. Gemini 중심 아키텍처

- 메인 LLM을 Gemini 계열로 고정
- Gemini 3.x 기준 라우팅 도입
- Flash 1차 호출, 필요 시 Pro adjudication 구조로 단순화

### 1-3. phase-1 재정비

- FinBERT를 phase-1 raw score 계층으로 유지
- 로딩 실패, 네트워크 차단, 런타임 오류 시 lexical fallback 자동 지원
- startup warmup과 상태 관측치 추가

## 2. 버전별 핵심 업데이트

### `v3.4.x` 계열

- FinBERT raw score + Gemini 메인 분석 구조 정착
- `analysis_service`, `gemini_client`, `analyze_router` 역할 분리
- contract adapter로 Backend Redis 최소 계약 고정
- integration router/state 추가
- live-room, collector, desktop execution feedback 호환 계층 추가

### `v3.5.0`

- Gemini 3.x cost-aware routing 도입
- 기본 모델:
  - `gemini-3-flash-preview`
  - `gemini-3-pro-preview`
- graph workflow를 다음 흐름으로 재구성
  - `route_decision`
  - `build_prompt`
  - `primary_llm_call`
  - `review_gate`
  - `adjudication_llm_call`
  - `parse_and_finalize`
- economy/standard/adjudication prompt profile 도입
- delta/rolling/adjudication context policy 도입
- `/health`, `/stats`에 라우팅 관측치 추가

### `v3.5.1`

- inspection 기반 버그 수정 반영
- `_compute_momentum_score()` 정규화 보정
- backtester Sharpe / MDD / zero-return 분류 수정
- `llm_router` overlap 계산 최적화
- `five_gate_filter` 통계 race 방지
- `regime_classifier` 내부 import 제거

### `v3.5.2`

- 운영 리스크 5건 추가 패치
- legacy Gemini env가 새 Gemini 3.x 설정을 덮어쓰지 않도록 수정
- `llm_router_novelty_threshold`를 실제 라우팅 정책에 연결
- `LLM_ROUTER_MAX_CALLS_PER_CHUNK=1`에서도 malformed first pass가 neutral fallback으로 종료되도록 보완
- `analyze_prompt()`를 explicit opt-in research helper로 격리
- modern Gemini SDK의 `thinking_config` 호환성 강화
- API 키 변경 시 modern client 재생성 지원
- 운영 가드 테스트 추가

## 3. 모듈별 주요 변경

### `config.py`

- Gemini 3.x 기본값 추가
- legacy env mapping 우선순위 수정
- deprecation warning 추가

### `core/analysis_service.py`

- graph 기반 live analysis orchestration
- route 통계 집계
- direct prompt helper를 live path에서 격리

### `core/gemini_client.py`

- modern SDK / legacy SDK 이중 지원
- thinking config 호환 fallback
- raw transport + parse 분리
- model별 호출 통계 추가

### `core/llm_router.py`

- route decision 구조화
- novelty score 계산
- high overlap에서 delta context 강제 가능
- O(n^2) overlap 계산 제거

### `core/prompt_builder.py`

- economy / standard / adjudication profile 도입
- rolling / delta / adjudication context 정책 지원
- economy profile용 축소 market data 구성

### `src/graph/workflow.py`

- LangGraph 기반 플로우 정의
- LangGraph 미설치 환경용 fallback sequential workflow 유지

### `core/phase1_scorer.py`

- FinBERT phase-1
- lexical fallback
- warmup/status/cache 구조 추가

### `api/analyze_router.py`

- session key 분리
- context update -> phase1 -> Gemini -> quant -> gate -> strategy -> risk -> publish 흐름 고정
- momentum normalization 수정 반영

### `core/backtester.py`

- event-based Sharpe 환산
- return unit 일관화
- MDD 계산 정리
- zero-return 분류 개선
- gate/operating mode 추천 기능 유지

## 4. 새로 추가된 문서

- `FLOW_AND_STRUCTURE_KO.md`
- `MODULE_IO_SPEC_KO.md`
- `LLM_IO_SPEC_KO.md`
- `FLOW_SPEC_KO.md`
- `TECHNICAL_SPEC_TABLE_KO.md`
- `UPDATE_SUMMARY_3_5_2_KO.md`

## 5. 새로 강화된 테스트 범위

- contract compatibility
- core quant logic
- inspection regressions
- routing regressions
- operational guards
- research/backtest extensions
- integration state
- redis publisher

현재 기준:
- `81 passed`

## 6. 현재 상태 요약

### 잘 정리된 부분

- live analysis flow
- Gemini 3.x routing
- Backend Redis 최소 계약
- collector / desktop / web integration compatibility
- research/backtesting extension
- 운영 관측치 `/health`, `/stats`

### 아직 운영 환경에서 추가로 챙길 부분

- FinBERT 실제 모델 파일 또는 사전 캐시 확보
- Redis 실서버 연결
- Gemini quota / 권한 확인
- backend / frontend / desktop과 end-to-end 통합 검증
