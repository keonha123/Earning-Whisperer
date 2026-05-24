# AI Engine Run List + Metrics API 업그레이드

## 이번 단계 범위
AI engine event store를 운영/대시보드에서 바로 사용할 수 있도록 다음을 추가했다.

- run 목록 조회 API
- 필터 + pagination 지원
- 성과 집계 overview API
- 전략별 집계 / 상위 ticker 집계

## 추가 엔드포인트

### 1) `GET /v1/engine/runs`
분석 run 목록을 조회한다.

지원 query params:
- `limit`
- `offset`
- `ticker`
- `strategy_code`
- `status`

반환 구조:
- `items[]`
- `pagination`
- `filters`

### 2) `GET /v1/engine/metrics/overview`
지정 기간 기준 성과 지표를 반환한다.

지원 query params:
- `lookback_days` (default: 30)

반환 구조:
- `summary`
- `by_strategy[]`
- `top_tickers[]`

## summary 주요 지표
- `total_runs`
- `ok_runs`
- `closed_replays`
- `winning_replays`
- `avg_confidence`
- `avg_realized_pnl_pct`
- `avg_mfe_pct`
- `avg_mae_pct`
- `win_rate_pct`

## by_strategy 주요 지표
- `strategy_code`
- `runs`
- `closed_replays`
- `wins`
- `avg_confidence`
- `avg_realized_pnl_pct`
- `win_rate_pct`

## 구현 파일
- `main.py`
- `models/storage_models.py`
- `repositories/event_store_repository.py`
- `tests/test_main_persistence_api.py`
- `tests/test_event_store_repository.py`

## 검증 결과
```bash
39 passed
```

## 활용 의미
이제 AI engine 범위에서 팀원에게 넘길 수 있는 API는 다음 수준이다.

- 분석 결과 저장
- 저장 결과 조회
- replay 사후 업데이트
- 목록 화면 구성
- KPI/대시보드 구성

즉, backend/frontend 팀은 별도 분석 로직 없이도 AI engine 결과를 운영형 화면으로 바로 연결할 수 있다.
