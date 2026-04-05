# Review Response 3.4.3

## 이번 검수 반영 사항

### 1. Tetlock 패널티 대칭성 수정

- 파일: `core/score_normalizer.py`
- 수정:
  - Tetlock 패널티가 방향과 무관하게 음수로 더해지던 구조를 제거
  - 이제 `BULLISH`와 `BEARISH` 모두 절대값이 줄어드는 방향으로 보정
  - `NEUTRAL`에는 Tetlock 패널티가 적용되지 않음

### 2. ContextManager TTL cleanup 레이스 완화

- 파일: `core/context_manager.py`
- 수정:
  - cleanup 후보를 먼저 수집한 뒤, 실제 삭제 시 per-session lock과 global lock 아래에서 TTL을 다시 확인
  - cleanup 대기 중 새로운 업데이트가 들어오려는 상황에서도 방금 갱신된 세션을 잘못 삭제하지 않도록 보완

### 3. `ticker` -> `session_key` 인터페이스 정리

- 파일: `core/context_manager.py`
- 수정:
  - 공개 메서드 파라미터를 실제 사용 방식에 맞춰 `session_key`로 명확화
  - 예시와 로깅도 `NVDA:call-001` 같은 세션 키 기준으로 정리

### 4. 부정어 감지 범위 확장

- 파일: `core/integrity_validator.py`
- 수정:
  - 부정어 뒤 허용 범위를 기존 3자에서 15자 초과 여유를 두는 창으로 확대
  - `"not at all growth"` 같은 표현이 `BULLISH`로 오탐되는 문제를 완화

### 5. 회귀 테스트 추가

- 파일: `tests/test_regression_fixes.py`
- 검증:
  - Tetlock 패널티가 `BEARISH` 절대값을 키우지 않는지
  - `NEUTRAL`에 근거 없는 음수 편향이 생기지 않는지
  - cleanup 중 세션이 갱신되면 삭제되지 않는지
  - `session_key` 명명 인터페이스가 동작하는지
  - `"not at all growth"` 문장이 `BULLISH`로 판정되지 않는지

## 이번 턴에서 의도적으로 가짜 구현하지 않은 항목

### Teacher-Student 파인튜닝

- 이 항목은 단순 코드 패치가 아니라 아래가 함께 필요하다.
  - 라벨링 데이터셋
  - 학습/평가 파이프라인
  - 모델 버전 관리
  - 배포 모델 교체 절차
- 따라서 이번 턴에서는 운영 코드에 억지 placeholder를 넣지 않았다.
- 현재 구조는 `FinBERT phase-1 + Gemini main LLM`을 유지하고, 학습 파이프라인은 별도 작업으로 분리하는 편이 안전하다.
