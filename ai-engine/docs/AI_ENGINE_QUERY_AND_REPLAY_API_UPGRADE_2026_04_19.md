# AI Engine 조회 API + Replay Update API 업그레이드

## 추가 범위
이번 단계에서는 AI engine event store 위에 다음 기능을 추가했다.

- `run_id` 기준 조회 API
- `event_id` 기준 조회 API
- replay tracking PATCH API

## 추가 엔드포인트

### 1) `GET /v1/engine/runs/{run_id}`
단일 분석 실행(run)에 대한 저장 결과를 묶어서 반환한다.

반환 묶음:
- event
- analysis_run
- feature_snapshot
- signal_explanation
- trade_plan
- cards
- paywall
- replay

### 2) `GET /v1/engine/events/{event_id}`
이벤트 단위로 저장된 기본 정보와 run 목록을 반환한다.

반환 묶음:
- event
- runs[]

### 3) `PATCH /v1/engine/replay/{run_id}`
리플레이 추적 상태를 부분 업데이트한다.

지원 필드:
- `status`
- `original_signal`
- `milestones`
- `expected_path`
- `exit_watch`
- `realized_pnl_pct`
- `mfe_pct`
- `mae_pct`
- `close_reason`

## 구현 포인트
- JSON/JSONB 컬럼은 응답 시 자동 복원
- replay patch는 전달된 필드만 업데이트
- `updated_at = now()` 자동 반영
- 잘못된 patch 필드는 400 에러 처리
- 없는 run/event는 404 처리

## 수정 파일
- `main.py`
- `models/storage_models.py`
- `repositories/event_store_repository.py`
- `db/postgres_executor.py`
- `tests/test_main_persistence_api.py`
- `tests/test_event_store_repository.py`

## 검증 결과
```bash
35 passed
```

## 활용 관점
이제 AI engine 담당 범위에서 팀원에게 넘길 수 있는 명세/연결 포인트는 다음 수준까지 올라간다.

- 분석 결과 저장
- 저장 결과 조회
- 사후 성과 추적 업데이트

즉, backend/frontend 팀은 이 API를 기준으로 조회 화면, replay 화면, 성과 대시보드를 붙이면 된다.
