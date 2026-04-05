# Compatibility Audit

## 1. 점검 목적

이번 점검의 목적은 다음과 같다.

- `files (2).zip` 기반 ai_engine이 현재 팀 문서의 시스템 계약과 충돌하지 않는지 확인
- collector / backend / frontend / desktop 역할 분리가 코드 구조에 반영되는지 확인
- FinBERT를 다시 넣어도 응답 속도와 처리 신뢰성이 유지되는지 확인
- LangGraph 이식 상태가 현재 구조와 충돌하지 않는지 확인

## 2. 점검 결과 요약

### 계약 호환성

- Contract 1: 호환
- Contract 2: 호환
- 웹 라이브룸 비매매 뷰: 호환
- 데스크탑 콜백 구조: 호환

### 구조 호환성

- collector ingest 상태 캐시: 호환
- 배치 분석: 호환
- 다중 어닝콜 세션 분리: 호환
- 연구용 백테스트 API: 독립 운영 가능

### 성능/신뢰성 설계

- phase-1은 FinBERT를 메인으로 사용
- FinBERT 모델은 lazy load
- 반복 청크는 LRU 캐시 재사용
- 모델 로딩 실패나 런타임 오류 시 lexical fallback
- Gemini는 여전히 메인 rationale/consensus LLM

## 3. 실제 수정 사항

- FinBERT 기반 `phase1_scorer.py` 재구성
- warmup 옵션 추가
- phase-1 cache 설정 추가
- `transformers`, `torch` 의존성 반영
- Redis publisher 기본 채널/확장 채널 이중 발행 유지
- pytest cacheprovider 비활성화로 테스트 안정화

## 4. 테스트 결과

- `python -m pytest`
- 총 54개 수준의 핵심 시나리오가 안정적으로 통과하도록 점검
- 캐시 권한 경고 없이 테스트 실행되도록 정리

## 5. 다음 권장 작업

- Backend Redis subscriber JSON 스키마와 1:1 맞대조
- `data-pipeline` 샘플 sender 추가
- Trading Terminal callback 예시 payload 문서화
- production 환경에서는 `PHASE1_WARMUP_ON_STARTUP=true` 검토
