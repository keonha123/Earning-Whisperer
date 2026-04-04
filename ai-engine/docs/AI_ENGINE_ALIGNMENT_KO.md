# AI Engine Alignment

이 문서는 `files (2).zip` 기반 구현과 팀 시스템 문서를 함께 반영해 현재 `ai_engine`가 어떤 기준에 맞춰졌는지 정리한다.

## 1. 정렬 기준

- Data Pipeline -> AI Engine 입력 계약은 유지한다.
- AI Engine -> Backend Redis 계약은 최소 필드 계약으로 고정한다.
- 웹 라이브룸은 매매 정보 없는 분석 전용 뷰를 제공한다.
- 브로커 API 키는 중앙 서버에 저장하지 않고, 데스크탑 콜백 구조를 전제로 한다.
- LangGraph 기반 LLM 호출 흐름은 유지하되, 아직 agentic/RAG 기능은 미완성 상태로 본다.
- Gemini API는 메인 LLM으로 유지한다.
- FinBERT는 phase-1 raw score 모델로 복원하되, 실패 시 lexical fallback으로 안전하게 처리한다.

## 2. 현재 입력 계약

기본 입력 계약:

```json
{
  "ticker": "NVDA",
  "text_chunk": "...",
  "sequence": 0,
  "timestamp": 1732143600,
  "is_final": false
}
```

확장 입력:

- `call_id`
- `event_id`
- `batch_id`
- `source_type`
- `section_type`
- `speaker_role`
- `speaker_name`

collector가 먼저 보낸 종목 지표, 일정, 시장 컨텍스트는 분석 시 자동 병합된다.

## 3. 현재 Redis 계약

기본 Redis 채널:

- 채널명: `trading-signals`

발행 형식:

```json
{
  "ticker": "NVDA",
  "raw_score": -0.85,
  "rationale": "...",
  "text_chunk": "...",
  "timestamp": 1732143600,
  "is_session_end": false
}
```

설명:

- Backend가 의존하는 최소 계약만 기본 채널로 보낸다.
- 내부 확장 분석 신호는 `trading-signals-enriched` 채널로 별도 발행 가능하다.

## 4. 현재 분석 흐름

1. `phase1_scorer`가 FinBERT로 빠른 raw score를 계산한다.
2. FinBERT 로딩이나 추론이 불가능하면 lexical fallback으로 즉시 대체한다.
3. LangGraph 기반 `analysis_service`가 Gemini 호출과 rationale 생성을 수행한다.
4. 결과가 애매하거나 긴 문맥이면 consensus 경로를 수행한다.
5. 정량 게이트, 리스크, 전략 선택을 계산한다.
6. Backend 최소 계약과 내부 확장 신호를 동시에 구성한다.

## 5. Goldman Sachs / J.P. Morgan 공개 레퍼런스에서 반영한 방향

- Goldman Sachs `gs-quant`: 연구/분석/운용 계층을 분리하는 구조 참고
- J.P. Morgan `Fusion SDK`: 계약 중심 데이터 인터페이스 분리 참고
- J.P. Morgan `abides-jpmc-public`: 연구 경로와 실시간 실행 경로를 분리하는 관점 참고

이번 구현 반영:

- 계약 모델과 내부 모델을 분리했다.
- integration 상태 저장 계층을 따로 뒀다.
- 연구용 API와 실시간 분석 API를 분리했다.

## 6. 아직 남아 있는 차이

- RAG는 아직 미구현이다.
- agentic workflow는 LangGraph 호출 기반만 있고, 도구 사용/계획/메모리형 에이전트는 없다.
- Data Pipeline 실 구현과 Trading Terminal 실 구현은 아직 별도 프로젝트 영역이다.

## 7. 관련 파일

- `api/analyze_router.py`
- `api/integration_router.py`
- `core/analysis_service.py`
- `core/phase1_scorer.py`
- `core/contract_adapter.py`
- `core/redis_publisher.py`
- `core/integration_state.py`
- `models/contract_models.py`
