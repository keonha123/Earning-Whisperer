# LLM I/O Spec

## 목적

이 문서는 `ai_engine`의 LLM 계층에 들어가는 입력 구성과 출력 구성을 따로 정리한 문서입니다. Gemini 호출, 라우팅, 프롬프트, review escalation, JSON output 계약을 한 번에 확인할 수 있습니다.

## 1. LLM 호출에 들어가기 전 입력

LLM 최종 입력은 `analysis_service.analyze()`에서 조립됩니다.

### 상위 입력 필드

| 필드 | 타입 | 설명 |
|---|---|---|
| `ticker` | `str` | 종목 코드 |
| `current_chunk` | `str` | 현재 STT 청크 |
| `context_chunks` | `list[ChunkRecord]` | 직전 rolling transcript |
| `market_data` | `MarketData \| None` | 가격, 기술지표, execution quality, EPS surprise 등 |
| `section_type` | `SectionType \| None` | `PREPARED_REMARKS`, `Q_AND_A`, `OTHER` |
| `request_priority` | `int` | 1~10 |
| `is_final` | `bool` | 세션 마지막 청크 여부 |
| `phase1_result` | `Phase1ScoreResult` | FinBERT phase-1 결과 |

### `Phase1ScoreResult`

| 필드 | 타입 |
|---|---|
| `raw_score` | `float` |
| `confidence` | `float` |
| `provider` | `str` |
| `rationale_hint` | `str` |

## 2. 라우팅 입력과 판단 기준

라우팅은 `core/llm_router.py::decide_route()`에서 수행됩니다.

### 라우팅 입력

| 필드 | 타입 |
|---|---|
| `current_chunk` | `str` |
| `context_chunks` | `Sequence[ChunkRecord]` |
| `market_data` | `MarketData \| None` |
| `section_type` | `SectionType \| None` |
| `request_priority` | `int` |
| `is_final` | `bool` |
| `phase1_raw_score` | `float` |

### 라우팅 출력 `RouteDecision`

| 필드 | 타입 | 설명 |
|---|---|---|
| `route_profile` | `str` | `economy` 또는 `standard` |
| `context_policy` | `str` | `delta` 또는 `rolling` |
| `primary_model` | `str` | 기본 `gemini-3-flash-preview` |
| `review_model` | `str` | 기본 `gemini-3-pro-preview` |
| `primary_max_output_tokens` | `int` | profile별 최대 출력 토큰 |
| `review_max_output_tokens` | `int` | review 최대 출력 토큰 |
| `primary_thinking_level` | `str` | `minimal` 또는 `low` |
| `review_thinking_level` | `str` | 기본 `medium` |
| `novelty_score` | `float` | 0~1, overlap 기반 |
| `overlap_ratio` | `float` | 0~1 |
| `estimated_prompt_tokens` | `int` | 입력 토큰 추정치 |
| `important_chunk` | `bool` | 중요 청크 여부 |

### 중요 청크 규칙

다음 중 하나라도 만족하면 중요 청크로 간주합니다.

- `section_type == Q_AND_A`
- `request_priority >= 8`
- `is_final == true`
- `abs(phase1_raw_score) >= 0.45`
- `market_data.volume_ratio >= 2.5`
- `abs(market_data.gap_pct) >= 3.0`
- `abs(market_data.earnings_surprise_pct) >= 10.0`

### review escalation 규칙

`core/llm_consistency.py::should_request_review()` 기준:

- primary parse 실패
- integrity validation 실패
- phase1 방향과 Flash 결과 방향 충돌, 양쪽 confidence >= 0.70
- 중요 청크인데 primary confidence < `llm_router_review_confidence_threshold`
- `euphemism_count >= 2` 이면서 Q&A 또는 guidance 맥락

## 3. Prompt 입력 구성

프롬프트는 `core/prompt_builder.py::build_prompt()`에서 생성됩니다.

### 함수 입력

| 필드 | 타입 |
|---|---|
| `ticker` | `str` |
| `current_chunk` | `str` |
| `context_chunks` | `Sequence[ChunkRecord]` |
| `market_data` | `MarketData \| None` |
| `prompt_profile` | `str` |
| `context_policy` | `str` |
| `phase1_score` | `float \| None` |
| `previous_result` | `GeminiAnalysisResult \| None` |
| `review_reason` | `str \| None` |

### Prompt profile 종류

| profile | 용도 | 특징 |
|---|---|---|
| `economy` | 기본 실시간 경로 | 1문장 rationale, 짧은 CoT, 축소된 market data |
| `standard` | 중요 청크 | 2문장 rationale, rolling context, full market dump |
| `adjudication` | review 경로 | 1차 결과, phase1 score, review reason 포함 |

### Context policy 종류

| policy | 입력 구성 |
|---|---|
| `delta` | 현재 청크에서 overlap 제거 + 직전 anchor 1개 |
| `rolling` | 최근 context chunk들 + 현재 청크 |
| `adjudication` | 현재 청크 + 직전 anchor + review block |

### economy profile에서 포함되는 market data

| 필드 | 타입 |
|---|---|
| `current_price` | `float \| None` |
| `price_change_pct` | `float \| None` |
| `volume_ratio` | `float \| None` |
| `vix` | `float \| None` |
| `earnings_surprise_pct` | `float \| None` |
| `gap_pct` | `float \| None` |
| `bid_ask_spread_bps` | `float \| None` |
| `liquidity_score` | `float \| None` |

### standard profile에서 포함되는 market data

- `MarketData.model_dump(exclude_none=True)` 전체

## 4. Gemini 호출 구성

LLM transport는 `core/gemini_client.py::generate_content()`가 담당합니다.

### Gemini 입력

| 항목 | 타입 | 설명 |
|---|---|---|
| `model` | `str` | `gemini-3-flash-preview`, `gemini-3-pro-preview` |
| `contents` | `str` | prompt text |
| `config` | `dict` | system instruction, max tokens, mime type, thinking level |

### Gemini config 필드

| key | 타입 |
|---|---|
| `system_instruction` | `str` |
| `max_output_tokens` | `int` |
| `response_mime_type` | `str` |
| `thinking_level` | `str` |

### Modern SDK 내부 매핑

| 설정 | modern SDK 객체 |
|---|---|
| `system_instruction` | `GenerateContentConfig.system_instruction` |
| `max_output_tokens` | `GenerateContentConfig.max_output_tokens` |
| `response_mime_type` | `GenerateContentConfig.response_mime_type` |
| `thinking_level` | `ThinkingConfig` 또는 omit |

## 5. Gemini 출력 계약

모든 live 경로는 JSON only 응답을 기대합니다.

### required JSON keys

| key | 타입 | 제약 |
|---|---|---|
| `cot_reasoning` | `str \| null` | economy에서는 짧게 |
| `direction` | `str` | `BULLISH`, `BEARISH`, `NEUTRAL` |
| `magnitude` | `float` | 0.0 ~ 1.0 |
| `confidence` | `float` | 0.0 ~ 1.0 |
| `rationale` | `str` | economy 1문장, standard/adjudication 2문장 이하 |
| `catalyst_type` | `str` | 허용 enum 중 하나 |
| `euphemism_count` | `int` | 0 이상 |
| `negative_word_ratio` | `float` | 0.0 ~ 1.0 |

### 허용 `catalyst_type`

- `EARNINGS_BEAT`
- `EARNINGS_MISS`
- `GUIDANCE_UP`
- `GUIDANCE_DOWN`
- `GUIDANCE_HOLD`
- `RESTRUCTURING`
- `PRODUCT_NEWS`
- `MACRO_COMMENTARY`
- `REGULATORY_RISK`
- `OPERATIONAL_EXEC`

### 파싱 후 내부 결과 타입

`GeminiAnalysisResult`

| 필드 | 타입 |
|---|---|
| `direction` | `str` |
| `magnitude` | `float` |
| `confidence` | `float` |
| `rationale` | `str` |
| `catalyst_type` | `str` |
| `euphemism_count` | `int` |
| `euphemisms` | `list[str] \| None` |
| `negative_word_ratio` | `float` |
| `cot_reasoning` | `str \| None` |
| `model_route` | `str \| None` |
| `consensus_score` | `float \| None` |
| `disagreement_score` | `float \| None` |

## 6. Graph Flow I/O

### `route_decision`

| 입력 | 출력 |
|---|---|
| 기본 analyze state | `route_profile`, `context_policy`, `primary_model`, `review_model`, `primary_config`, `review_config`, `estimated_prompt_tokens`, `important_chunk` |

### `build_prompt`

| 입력 | 출력 |
|---|---|
| route state + market/context | `contents`, `estimated_prompt_tokens` |

### `primary_llm_call`

| 입력 | 출력 |
|---|---|
| `primary_model`, `contents`, `primary_config` | `primary_result_text`, `llm_call_count`, consumed token estimates |

### `review_gate`

| 입력 | 출력 |
|---|---|
| `primary_result_text`, phase1/conflict/integrity info | `needs_review`, `review_reason`, `parsed_primary_result` 또는 `result` |

### `adjudication_llm_call`

| 입력 | 출력 |
|---|---|
| review state | `review_contents`, `review_result_text`, updated token estimates |

### `parse_and_finalize`

| 입력 | 출력 |
|---|---|
| primary/review text 또는 fallback state | `result: GeminiAnalysisResult`, `estimated_prompt_tokens`, `estimated_output_tokens` |

## 7. 운영 관측치

### `/stats`의 LLM 관련 필드

| 필드 | 타입 | 의미 |
|---|---|---|
| `gemini_stats.call_count` | `int` | 총 Gemini 호출 수 |
| `gemini_stats.error_count` | `int` | 호출 실패 수 |
| `gemini_stats.avg_latency_ms` | `float` | 평균 지연 |
| `route_counts` | `dict[str, int]` | economy/standard/review 집계 |
| `flash_only_rate` | `float` | Flash only 종료 비율 |
| `pro_escalation_rate` | `float` | Pro review 승격 비율 |
| `avg_estimated_prompt_tokens` | `float` | 평균 추정 입력 토큰 |
| `avg_estimated_output_tokens` | `float` | 평균 추정 출력 토큰 |
| `economy_prompt_rate` | `float` | economy profile 사용 비율 |

## 8. 실패 시 fallback

| 실패 지점 | fallback 동작 |
|---|---|
| Gemini SDK 미설치/키 없음 | `GeminiClient.analyze()`는 neutral fallback 결과 |
| primary parse 실패 + review 가능 | Pro adjudication 시도 |
| primary parse 실패 + review budget 불가 | neutral fallback result로 종료 |
| FinBERT 초기화 실패 | lexical phase-1 scorer로 자동 전환 |
