# AI Engine Gate Tuning + Alert Evaluation API 업그레이드

## 이번 단계 목적
AI engine 결과를 운영 대시보드에서 보는 것만으로 끝내지 않고, 다음 단계까지 자동으로 이어지게 만들었다.

- 게이트 파라미터 조정 권고치 제공
- 즉시 띄울 alert 평가 결과 제공

## 추가 엔드포인트

### 1) `GET /v1/engine/controls/gate-tuning`
전략별 게이트 조정 권고 API.

지원 query params:
- `short_window_days`
- `baseline_window_days`
- `lookback_days`

반환:
- `strategy_code`
- `current_action`
- `recent`
- `suggested_gate_patch`
- `rationale_ko`

`suggested_gate_patch` 예시 필드:
- `min_confidence_delta`
- `require_review_trigger`
- `max_hold_days_delta`
- `position_scale_delta`

### 2) `GET /v1/engine/alerts/evaluate`
운영 alert 평가 API.

지원 query params:
- `short_window_days`
- `baseline_window_days`
- `lookback_days`

반환:
- `alerts[]`
- `alert_count`
- `action_counts`

## 현재 alert 규칙
현재 기본 규칙은 다음과 같다.

- 설명 커버리지 95% 미만 → `EXPLANATION_COVERAGE_LOW`
- replay 종료율 50% 미만 → `REPLAY_CLOSED_RATE_LOW`
- soft_disable 권고 존재 → `SOFT_DISABLE_RECOMMENDED`
- tighten_gate 권고 전략 2개 이상 → `MULTI_STRATEGY_DEGRADING`

## 활용 방식
이 API를 기반으로 팀원은 다음을 쉽게 구현할 수 있다.

- 운영 알림 배너
- 관리자 대시보드 alert feed
- 전략별 게이트 patch 제안 UI
- weekly review automation
- soft-disable 검토 카드

## 검증 결과
```bash
51 passed
```

## 현재 AI Engine 구현 범위
이제 AI engine은 다음 범위를 커버한다.

- inference 결과 생성
- 저장 API
- 조회 API
- replay patch API
- run list API
- KPI overview API
- quality scorecard API
- strategy drift API
- leaderboard API
- control recommendation API
- gate tuning recommendation API
- alert evaluation API

즉, 분석 → 저장 → 조회 → 진단 → 운영 제어 권고 → 알림 평가까지 이어지는 구조가 완성된 상태다.
