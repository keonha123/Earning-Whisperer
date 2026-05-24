# AI Engine FastAPI 저장 API + PostgreSQL Insert Layer 업그레이드

## 이번 단계 범위
AI engine 결과를 **이벤트 스토어 스키마 기준으로 저장**할 수 있도록 다음을 추가했다.

- FastAPI 저장 API
- PostgreSQL insert / upsert 레이어
- schema bootstrap API
- 저장 매핑 단위 테스트
- analyze + persist 통합 API

## 추가된 엔드포인트

### 1) `POST /v1/engine/events/persist`
이미 생성된 AI engine envelope JSON을 그대로 받아 DB에 저장한다.

### 2) `POST /v1/engine/analyze-and-persist`
기존 분석 요청을 받아:
1. 분석 수행
2. frontend 계약형 envelope 생성
3. PostgreSQL 저장
4. envelope + 저장 결과 반환

### 3) `POST /v1/engine/admin/bootstrap-schema`
`sql/ai_engine_event_store_schema.sql`을 실행해 스키마를 초기화한다.

## 저장 대상 테이블
- `ai_events`
- `ai_analysis_runs`
- `ai_feature_snapshots`
- `ai_signal_explanations`
- `ai_trade_plans`
- `ai_cards`
- `ai_paywall_surfaces`
- `ai_replay_tracks`

## 구현 파일
- `main.py`
- `config.py`
- `db/postgres_executor.py`
- `repositories/event_store_repository.py`
- `models/storage_models.py`
- `tests/test_event_store_repository.py`
- `tests/test_main_persistence_api.py`
- `.env.example`

## 런타임 요구사항
실제 PostgreSQL 연결 시 아래 패키지가 필요하다.

```bash
pip install "psycopg[binary]"
```

## 환경변수
```env
DATABASE_URL=postgresql://postgres:postgres@localhost:5432/earningwhisperer
DB_SCHEMA_PATH=sql/ai_engine_event_store_schema.sql
```

## 저장 구조 요약
- `event_id` 기준 이벤트 업서트
- `run_id` 기준 분석 결과 업서트
- card는 `card_id` 기준 개별 업서트
- paywall / replay / trade_plan / explanation / feature snapshot은 `run_id` 기준 1:1 저장

## 검증 결과
로컬 테스트 기준:

```bash
31 passed
```

## 다음 자연스러운 단계
1. FastAPI 저장 API에 인증/내부 토큰 추가
2. async background queue 또는 worker로 비동기 persist 분리
3. replay 업데이트용 PATCH API 추가
4. run 조회 API / event 조회 API 추가
5. PostgreSQL connection pool 및 장애 재시도 정책 추가
