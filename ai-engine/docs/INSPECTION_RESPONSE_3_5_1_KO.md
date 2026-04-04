# Inspection Response 3.5.1

## 반영한 수정

- `analyze_router.py`
  - `_compute_momentum_score()`가 실제 사용된 지표 가중치 합으로 정규화되도록 수정
- `backtester.py`
  - Sharpe 계산을 이벤트 기반 연환산으로 수정
  - Sharpe와 MDD가 모두 퍼센트 수익률 입력을 동일하게 해석하도록 통일
  - `actual_return == 0.0`은 loss가 아니라 non-negative 쪽으로 집계
- `five_gate_filter.py`
  - gate 통계 갱신에 `threading.Lock` 적용
- `regime_classifier.py`
  - 함수 내부 `import numpy` 제거
- `llm_router.py`
  - overlap 계산을 선형 시간 prefix-function 방식으로 변경

## 새 회귀 테스트

- `tests/test_inspection_regressions.py`
  - momentum 정규화 회귀
  - Sharpe 퍼센트 단위 / 이벤트 연환산 회귀
  - 0 수익률 분류 회귀
  - 긴 텍스트 overlap 계산 회귀

## 비고

- 제공된 백테스팅 수치는 외부 네트워크가 없는 현재 환경에서 직접 재현하지는 못했다.
- 대신 리포트에서 지적한 코드 레벨 버그들을 실제 구현 기준으로 반영하고, 관련 계산 회귀 테스트를 추가했다.
