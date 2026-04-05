# EarningWhisperer DB Schema

## ERD 개요

```
users (1) ──────────────────── (1) portfolio_settings
  │
  ├── (1:N) ──── signal_history
  │
  ├── (1:N) ──── trades ──── (N:1) signal_history
  │
  └── (1:N) ──── watchlist_items ──── (N:1) stocks ──── (1:N) earnings_calendar
```

---

## 테이블 명세

### `users`
사용자 계정 및 플랜 정보

| 컬럼 | 타입 | 제약 | 설명 |
|------|------|------|------|
| id | BIGINT | PK, AUTO_INCREMENT | 사용자 ID |
| email | VARCHAR(100) | UNIQUE, NOT NULL | 로그인 이메일 |
| password | VARCHAR(255) | NOT NULL | BCrypt 암호화 비밀번호 |
| nickname | VARCHAR(50) | NOT NULL | 표시 이름 |
| role | VARCHAR(10) | NOT NULL | `FREE` / `PRO` |
| created_at | DATETIME | NOT NULL | 가입 일시 |
| updated_at | DATETIME | NOT NULL | 최종 수정 일시 |

---

### `portfolio_settings`
사용자별 리스크 관리 설정 및 자체 추정 장부(Internal Ledger). User와 1:1 관계.

| 컬럼 | 타입 | 제약 | 설명 |
|------|------|------|------|
| id | BIGINT | PK, AUTO_INCREMENT | 설정 ID |
| user_id | BIGINT | FK(users), UNIQUE, NOT NULL | 소유 사용자 |
| buy_amount_ratio | DOUBLE | NOT NULL | 1회 매수 시 예수금 사용 비율 (0.0~1.0) |
| max_position_ratio | DOUBLE | NOT NULL | 단일 종목 최대 보유 비중 (0.0~1.0) |
| cooldown_minutes | INT | NOT NULL | 동일 종목 재진입 대기 시간 (분) |
| ema_threshold | DOUBLE | NOT NULL | BUY/SELL 실행 임계치 (예: 0.6) |
| trading_mode | VARCHAR(20) | NOT NULL | `MANUAL` / `SEMI_AUTO` / `AUTO_PILOT` |
| cash_balance | DOUBLE | NULL | Trading Terminal이 동기화한 실계좌 예수금 |
| created_at | DATETIME | NOT NULL | 생성 일시 |
| updated_at | DATETIME | NOT NULL | 수정 일시 |

---

### `stocks`
S&P 500 구성 종목 마스터 데이터. FMP API를 통해 분기 1회 동기화.

| 컬럼 | 타입 | 제약 | 설명 |
|------|------|------|------|
| id | BIGINT | PK, AUTO_INCREMENT | 종목 ID |
| ticker | VARCHAR(10) | UNIQUE, NOT NULL | 종목 심볼 (예: NVDA) |
| company_name | VARCHAR(255) | NOT NULL | 회사명 |
| sector | VARCHAR(50) | NULL | 업종 분류 |
| active | BOOLEAN | NOT NULL, DEFAULT true | S&P 500 편입 여부. 제외 시 false (soft delete) |
| created_at | DATETIME | NOT NULL | 생성 일시 |
| updated_at | DATETIME | NOT NULL | 수정 일시 |

---

### `watchlist_items`
사용자별 관심종목 목록. User : Stock = N:M 연결 테이블.

| 컬럼 | 타입 | 제약 | 설명 |
|------|------|------|------|
| id | BIGINT | PK, AUTO_INCREMENT | ID |
| user_id | BIGINT | FK(users), NOT NULL | 소유 사용자 |
| stock_id | BIGINT | FK(stocks), NOT NULL | 관심 종목 |
| created_at | DATETIME | NOT NULL | 추가 일시 |
| updated_at | DATETIME | NOT NULL | 수정 일시 |

**유니크 제약:** `(user_id, stock_id)` — 동일 종목 중복 추가 방지

---

### `earnings_calendar`
어닝콜 일정. Finnhub API를 통해 매일 06:00 UTC에 자동 갱신.

| 컬럼 | 타입 | 제약 | 설명 |
|------|------|------|------|
| id | BIGINT | PK, AUTO_INCREMENT | ID |
| stock_id | BIGINT | FK(stocks), NOT NULL | 어닝콜 발표 종목 |
| scheduled_at | DATETIME | NOT NULL | 어닝콜 발표 예정 일시 (UTC) |
| confirmed | BOOLEAN | NOT NULL, DEFAULT false | 일정 확정 여부 |
| created_at | DATETIME | NOT NULL | 생성 일시 |
| updated_at | DATETIME | NOT NULL | 수정 일시 |

**유니크 제약:** `(stock_id, scheduled_at)` — 동일 종목 중복 일정 방지

---

### `signal_history`
AI가 생성한 매매 시그널 이력

| 컬럼 | 타입 | 제약 | 설명 |
|------|------|------|------|
| id | BIGINT | PK, AUTO_INCREMENT | 시그널 ID |
| user_id | BIGINT | FK(users), NOT NULL | 소유 사용자 |
| ticker | VARCHAR(20) | NOT NULL | 종목 심볼 |
| raw_score | DOUBLE | NOT NULL | AI 원시 감성 점수 (-1.0~+1.0) |
| ema_score | DOUBLE | NOT NULL | 백엔드 계산 EMA 누적 점수 |
| rationale | TEXT | NOT NULL | LLM이 생성한 매매 근거 해설 |
| text_chunk | TEXT | NOT NULL | 분석에 사용된 STT 원문 텍스트 |
| action | VARCHAR(10) | NOT NULL | `BUY` / `SELL` / `HOLD` |
| signal_timestamp | BIGINT | NOT NULL | AI 분석 완료 시점 (Unix Epoch Second, UTC) |
| created_at | DATETIME | NOT NULL | 저장 일시 |

**인덱스:**
- `idx_signal_user_ticker (user_id, ticker)` — 종목별 시그널 조회
- `idx_signal_created_at (created_at)` — 시간 범위 조회

---

### `trades`
매매 주문 및 체결 내역

| 컬럼 | 타입 | 제약 | 설명 |
|------|------|------|------|
| id | BIGINT | PK, AUTO_INCREMENT | 거래 ID |
| user_id | BIGINT | FK(users), NOT NULL | 소유 사용자 |
| signal_id | BIGINT | FK(signal_history), NULL | 이 거래를 유발한 시그널 (없으면 NULL) |
| ticker | VARCHAR(20) | NOT NULL | 종목 심볼 |
| side | VARCHAR(10) | NOT NULL | `BUY` / `SELL` |
| order_type | VARCHAR(10) | NOT NULL | `MARKET` / `LIMIT` |
| order_qty | INT | NOT NULL | 주문 수량 (백엔드 룰엔진 산출) |
| price | DOUBLE | NOT NULL | 주문 단가 (시장가는 0) |
| executed_qty | INT | NOT NULL, DEFAULT 0 | 실제 체결 수량 (Trading Terminal 콜백으로 확정) |
| executed_price | DOUBLE | NULL | 실제 체결 단가 (Trading Terminal 콜백으로 확정) |
| status | VARCHAR(10) | NOT NULL | `PENDING` → `EXECUTED` / `FAILED` |
| broker_order_id | VARCHAR(50) | NULL | 증권사(KIS) 부여 주문 ID |
| created_at | DATETIME | NOT NULL | 주문 생성 일시 |

**인덱스:**
- `idx_trade_user_ticker (user_id, ticker)` — 종목별 거래 조회
- `idx_trade_created_at (created_at)` — 시간 범위 조회

---

## 주요 비즈니스 규칙

- `trades.status`는 엔티티 메서드(`executed()`, `failed()`)를 통해서만 전환 가능. 직접 setter 금지.
- `portfolio_settings.cash_balance`는 Trading Terminal이 보내는 Sync 데이터로만 덮어씀 — 백엔드가 자체 계산하지 않음.
- `stocks.active = false`는 S&P 500 제외 종목 표시. 실제 삭제하지 않음 (soft delete).
- `earnings_calendar`는 Finnhub 스케줄러(`FinnhubEarningsScheduler`)가 매일 06:00 UTC에 자동 갱신. `POST /api/v1/earnings-calendar/sync`로 수동 트리거 가능 (개발/테스트용).
