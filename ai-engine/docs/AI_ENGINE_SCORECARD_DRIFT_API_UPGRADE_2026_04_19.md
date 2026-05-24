# AI Engine Scorecard + Drift API 업그레이드

## 이번 단계 목적
운영 단계에서 단순 조회/KPI만으로는 부족하므로, 다음 진단 API를 추가했다.

- 품질 scorecard API
- 전략 drift 감지 API

## 추가 엔드포인트

### 1) `GET /v1/engine/metrics/scorecard`
AI engine 품질 점검용 API.

지원 query params:
- `lookback_days`

반환 구조:
- `summary`
- `rates`

주요 rate:
- `explanation_coverage_pct`
- `trade_plan_coverage_pct`
- `replay_coverage_pct`
- `replay_closed_rate_pct`
- `review_trigger_rate_pct`
- `low_confidence_rate_pct`

### 2) `GET /v1/engine/metrics/drift`
전략 성능이 최근 구간에서 악화/개선되고 있는지 비교한다.

지원 query params:
- `short_window_days` (default: 7)
- `baseline_window_days` (default: 30)

반환 구조:
- `items[]`
- `degrading[]`
- `improving[]`
- `stable[]`

비교 기준:
- 최근 window vs baseline window
- `win_rate_pct` delta
- `avg_realized_pnl_pct` delta

현재 진단 규칙:
- `win_rate_delta <= -15` 또는 `pnl_delta <= -2` → `degrading`
- `win_rate_delta >= 15` 또는 `pnl_delta >= 2` → `improving`
- 나머지 → `stable`

## 구현 포인트
- AI engine 내부 저장 데이터만 사용
- frontend에서 바로 heatmap/list/alert 카드로 렌더링 가능
- 향후 Slack alert, scheduler, weekly review bot으로 확장 가능

## 검증 결과
```bash
43 passed
```

## 활용 의미
이제 AI engine은 단순 inference module이 아니라 다음을 제공한다.

- 결과 생성
- 결과 저장
- 결과 조회
- 사후 replay 업데이트
- KPI 집계
- 품질 진단
- 전략 drift 감지

즉 팀원은 이 API를 기준으로 운영 대시보드와 알림 계층을 바로 붙일 수 있다.
