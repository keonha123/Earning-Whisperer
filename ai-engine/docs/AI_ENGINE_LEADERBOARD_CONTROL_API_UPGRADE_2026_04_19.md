# AI Engine Leaderboard + Control Recommendation API 업그레이드

## 이번 단계 목적
운영자 관점에서 다음 질문에 답할 수 있도록 기능을 추가했다.

- 지금 가장 잘 되는 전략은 무엇인가?
- 어떤 전략은 게이트를 조여야 하는가?
- 어떤 전략은 일시 중단 권고 수준인가?

## 추가 엔드포인트

### 1) `GET /v1/engine/metrics/leaderboard`
전략 순위 조회 API.

지원 query params:
- `lookback_days`
- `limit`
- `min_closed`
- `metric`

지원 metric:
- `avg_realized_pnl_pct`
- `win_rate_pct`
- `avg_confidence`

반환:
- `rank`
- `strategy_code`
- `runs`
- `closed_replays`
- `wins`
- `avg_confidence`
- `avg_realized_pnl_pct`
- `win_rate_pct`

### 2) `GET /v1/engine/controls/recommendations`
운영 제어 권고 API.

지원 query params:
- `short_window_days`
- `baseline_window_days`
- `lookback_days`

반환:
- `scorecard`
- `drift`
- `leaderboard_metric`
- `recommendations[]`
- `action_counts`

## action 규칙
현재 권고 action은 다음과 같다.

- `keep`
- `tighten_gate`
- `soft_disable`
- `expand`

현재 판단 로직:
- drift가 `degrading` 이고 최근 replay 표본이 충분하면 `tighten_gate`
- 하락폭이 매우 크면 `soft_disable`
- drift가 `improving` 이고 표본이 충분하면 `expand`
- 그 외는 `keep`

## 활용 방식
frontend/backend 팀은 이 API를 활용해 다음 화면/기능을 만들 수 있다.

- 전략 리더보드 카드
- 전략 운영 상태판
- soft-disable 후보 리스트
- 게이트 강화 추천 알림
- 주간 전략 리뷰 대시보드

## 검증 결과
```bash
47 passed
```

## 현재 AI Engine 구현 범위
이제 AI engine은 다음 레벨까지 올라왔다.

- inference 생성
- 저장 API
- 조회 API
- replay patch API
- run list API
- KPI overview API
- quality scorecard API
- strategy drift API
- leaderboard API
- control recommendation API

즉, AI engine 담당 범위 안에서 운영 의사결정까지 가능한 수준의 백엔드 로직이 붙은 상태다.
