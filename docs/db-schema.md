# 🗄️ EarningWhisperer DB Schema

## ERD 개요

```
users (1) ──────── (1) portfolio_settings
  │
  ├── (1:N) ──── signal_history
  │
  └── (1:N) ──── trades
                    └── (N:1) signal_history
```

---

## 테이블 명세

### `users`
| 컬럼 | 타입 | 제약 | 설명 |
|------|------|------|------|
| id | BIGINT | PK, AUTO_INCREMENT | 사용자 ID |
| email | VARCHAR(100) | UNIQUE, NOT NULL | 로그인 이메일 |
| password | VARCHAR(255) | NOT NULL | 암호화된 비밀번호 |
| nickname | VARCHAR(50) | NOT NULL | 표시 이름 |
| created_at | DATETIME | NOT NULL | 생성 시각 |
| updated_at | DATETIME | NOT NULL | 수정 시각 |

---

### `portfolio_settings`
사용자별 모의투자 리스크 관리 설정 (User와 1:1 관계)

| 컬럼 | 타입 | 제약 | 설명 |
|------|------|------|------|
| id | BIGINT | PK, AUTO_INCREMENT | 설정 ID |
| user_id | BIGINT | FK(users), UNIQUE, NOT NULL | 소유 사용자 |
| buy_amount_ratio | DOUBLE | NOT NULL | 1회 매수 예수금 비율 (0.0~1.0) |
| max_position_ratio | DOUBLE | NOT NULL | 종목 최대 보유 비중 (0.0~1.0) |
| cooldown_minutes | INT | NOT NULL | 쿨다운 타임 (분) |
| ema_threshold | DOUBLE | NOT NULL | EMA 임계치 (예: 0.6) |
| trading_mode | VARCHAR(20) | NOT NULL | MANUAL / SEMI_AUTO / AUTO_PILOT |
| created_at | DATETIME | NOT NULL | 생성 시각 |
| updated_at | DATETIME | NOT NULL | 수정 시각 |

---

### `signal_history`
AI가 생성한 매매 시그널 이력

| 컬럼 | 타입 | 제약 | 설명 |
|------|------|------|------|
| id | BIGINT | PK, AUTO_INCREMENT | 시그널 ID |
| user_id | BIGINT | FK(users), NOT NULL | 소유 사용자 |
| ticker | VARCHAR(20) | NOT NULL | 종목 심볼 (예: NVDA) |
| raw_score | DOUBLE | NOT NULL | AI 원시 감성 점수 (-1.0~+1.0) |
| ema_score | DOUBLE | NOT NULL | 백엔드 EMA 누적 점수 |
| rationale | TEXT | NOT NULL | LLM 해설 |
| text_chunk | TEXT | NOT NULL | 분석에 사용된 STT 원문 |
| action | VARCHAR(10) | NOT NULL | BUY / SELL / HOLD |
| signal_timestamp | BIGINT | NOT NULL | AI 분석 시점 (UTC Unix Epoch Second) |
| created_at | DATETIME | NOT NULL | 저장 시각 |

**인덱스:**
- `idx_signal_user_ticker (user_id, ticker)` — 종목별 시그널 조회
- `idx_signal_created_at (created_at)` — 시간 범위 조회

---

### `trades`
모의투자 주문 및 체결 내역

| 컬럼 | 타입 | 제약 | 설명 |
|------|------|------|------|
| id | BIGINT | PK, AUTO_INCREMENT | 거래 ID |
| user_id | BIGINT | FK(users), NOT NULL | 소유 사용자 |
| signal_id | BIGINT | FK(signal_history), NULL 허용 | 유발 시그널 |
| ticker | VARCHAR(20) | NOT NULL | 종목 심볼 |
| side | VARCHAR(10) | NOT NULL | BUY / SELL |
| order_type | VARCHAR(10) | NOT NULL | MARKET / LIMIT |
| order_qty | INT | NOT NULL | 주문 수량 |
| price | DOUBLE | NOT NULL | 주문 단가 (시장가=0) |
| executed_qty | INT | NOT NULL | 실제 체결 수량 |
| status | VARCHAR(10) | NOT NULL | PENDING / EXECUTED / FAILED |
| broker_order_id | VARCHAR(50) | NULL 허용 | 증권사 부여 주문 ID |
| created_at | DATETIME | NOT NULL | 주문 시각 |

**인덱스:**
- `idx_trade_user_ticker (user_id, ticker)` — 종목별 거래 조회
- `idx_trade_created_at (created_at)` — 시간 범위 조회
