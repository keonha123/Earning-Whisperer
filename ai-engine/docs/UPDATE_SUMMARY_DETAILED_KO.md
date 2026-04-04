# 업데이트 상세 정리

## 1. 이번 재구성의 목표

- zip 기반 구현을 현재 팀 문서와 다시 정렬
- Gemini를 메인 LLM으로 유지
- FinBERT를 빠른 phase-1 raw score 모델로 복원
- LangGraph 이식 상태는 유지하되 agentic/RAG 미구현 전제를 문서화
- collector / backend / web / desktop 사이의 계약을 명확히 분리
- 테스트와 문서를 함께 보강

## 2. 핵심 업데이트

### 구조화

- 계약 모델과 내부 모델을 분리했다.
- collector 호환 계층을 별도 라우터로 분리했다.
- 연구용 API와 실시간 분석 API를 분리했다.

### 계약 정렬

- 기본 Redis 채널은 Backend가 읽는 최소 계약만 발행한다.
- 확장 신호는 별도 enriched 채널에서 유지한다.
- 웹 라이브룸은 매매 필드가 없는 분석 전용 뷰를 제공한다.

### FinBERT 복원

- `phase1_scorer.py`를 FinBERT 중심 구조로 재작성
- lazy load
- cache
- device auto 선택
- lexical fallback
- startup warmup 옵션 추가

### 호환성 개선

- collector가 먼저 수집한 종목 지표와 시장 컨텍스트를 분석 시 자동 병합
- desktop execution feedback 수용
- 다중 콜 세션 분리 유지

### 테스트/문서

- FinBERT 확률 매핑 테스트 추가
- integration 상태 테스트 유지
- 파일 설명서와 호환성 점검 문서 갱신

## 3. 변경 파일

### 크게 수정

- `core/phase1_scorer.py`
- `config.py`
- `.env.example`
- `requirements.txt`
- `main.py`
- `tests/test_contract_compatibility.py`

### 문서 갱신

- `docs/AI_ENGINE_ALIGNMENT_KO.md`
- `docs/COMPATIBILITY_AUDIT_KO.md`
- `docs/FILE_MANUAL_KO.md`
- `docs/UPDATE_SUMMARY_DETAILED_KO.md`

## 4. 참고한 공개 레퍼런스

- Goldman Sachs `gs-quant`
- JPMorganChase `fusion-java-sdk`
- JPMorganChase `abides-jpmc-public`

반영 방식:

- 서비스 계약 분리
- 상태 저장과 분석 계층 분리
- 실시간 실행 경로와 연구 경로 분리

## 5. 현재 결론

현재 `ai_engine`는 다음 기준에 맞춘 상태다.

- `FinBERT raw_score first`
- `Gemini rationale second`
- `Backend contract minimal`
- `web live-room safe`
- `desktop broker local`
- `collector data merge ready`
