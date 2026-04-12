# 📢 EarningWhisperer API & Data Contract Specification

이 문서는 EarningWhisperer 프로젝트의 마이크로서비스 및 하이브리드 아키텍처(SaaS Web + Trading Terminal) 간 데이터 통신 규격을 정의합니다. 
모든 팀원은 본 명세에 정의된 필드명, 데이터 타입, 통신 주체를 엄격하게 준수하여 분산 시스템 환경에서 발생할 수 있는 파싱 에러와 상태 불일치를 원천 차단해야 합니다.

---

## 1. 전체 데이터 흐름도 (Data Pipeline)

1. **Data Pipeline** (Python) ➔ `[HTTP POST]` ➔ **AI Engine** (Python)
2. **AI Engine** (Python) ➔ `[Redis Pub/Sub]` ➔ **Backend** (Java Spring Boot)
3. **Backend** (Java) ➔ `[WebSocket /user/queue]` ➔ **Trading Terminal** (Electron/Node.js) : 개인화된 매매 명령 하달
4. **Backend** (Java) ➔ `[WebSocket /topic/live]` ➔ **Frontend Web** (Next.js) : 라이브 데모 시각화
5. **Trading Terminal** ➔ `[HTTP REST]` ➔ **증권사 KIS API** : 실제 주문 실행 (Client-side)
6. **Trading Terminal** ➔ `[HTTP POST Callback]` ➔ **Backend** (Java) : 체결 결과 보고 및 장부 동기화
7. **Data Pipeline** (Python) ➔ `[HTTP POST]` ➔ **Backend** (Java) : 어닝콜 일정 데이터 동기화 (저빈도 배치)
8. **Data Pipeline** (Python) ➔ `[Redis Pub/Sub]` ➔ **Backend** (Java) : 실시간 주가 데이터 스트리밍

---

## 2. [Contract 1] Data Pipeline ➔ AI Engine
- **통신 방식:** HTTP POST (비동기)
- **엔드포인트:** `http://ai-engine:8000/api/v1/analyze` 
- **설명:** 오디오 스트림에서 추출 및 슬라이딩 윈도우(Overlapping) 처리가 완료된 약 10~15초 단위의 STT 텍스트 조각을 분석 서버로 전송합니다.

| 필드명 | 타입 | 필수 | 설명 |
| :--- | :--- | :---: | :--- |
| `ticker` | String | Y | 분석 대상 종목 심볼 (예: "NVDA") |
| `text_chunk` | String | Y | 슬라이딩 윈도우가 적용된 실시간 STT 텍스트 |
| `sequence` | Integer | Y | 텍스트 조각의 순차 번호 (0부터 1씩 증가, 순서 보장용) |
| `timestamp` | Long | Y | 오디오 캡처 기준 발생 시점 (Unix Epoch Second) |
| `is_final` | Boolean | Y | 해당 어닝콜 세션의 완전 종료 여부 |

---

## 3. [Contract 2] AI Engine ➔ Backend (Raw Signal)
- **통신 방식:** Redis Pub/Sub
- **Redis Channel:** `trading-signals`
- **설명:** AI 서버(Stateless)가 텍스트를 분석하여 도출한 **순수 감성 점수(Raw Score)**와 해설을 백엔드로 브로드캐스팅합니다.

| 필드명 | 타입 | 필수 | 설명 |
| :--- | :--- | :---: | :--- |
| `ticker` | String | Y | 분석 대상 종목 심볼 |
| `raw_score` | Double | Y | 감성 방향 및 강도 (-1.0[강한 매도] ~ +1.0[강한 매수]) |
| `rationale` | String | Y | LLM이 생성한 분석 근거 |
| `text_chunk` | String | Y | 분석에 사용된 원문 텍스트 |
| `timestamp` | Long | Y | 분석 완료 시점 (Unix Epoch Second) |
| `is_session_end` | Boolean | N | 어닝콜 세션 종료 신호. `true`이면 백엔드가 세션 종료 처리 (기본값 `false`) |

---

## 4. [Contract 3] Backend ➔ Clients (WebSocket Signaling)
백엔드는 목적에 따라 세 가지 방식의 웹소켓 채널을 운영합니다.

### 4.1. Demo Replay Broadcast (Frontend Web 쇼케이스 데모룸용)
- **Topic:** `/topic/live/demo`
- **설명:** 회원가입 없이 서비스를 체험할 수 있는 **쇼케이스 데모룸** 전용 채널입니다. 실제 AI 분석을 24시간 운영하는 대신, 과거 주요 어닝콜(예: NVDA 2024 Q4)을 미리 분석해 저장한 스크립트 파일을 재생하여 라이브 느낌을 연출합니다.
- **재생 방식 (라디오 방송국 모델):** 서버 기동 시부터 `DemoReplayService`가 스크립트를 처음부터 끝까지 무한 반복 재생합니다. 유저는 접속 시점의 진행 구간부터 수신하며, 실제 라이브 룸에 중간 입장한 것과 동일한 경험을 얻습니다.
- **스크립트 파일 위치:** `src/main/resources/data/mock-{ticker}-replay.json` (JSON 배열)
- **재생 간격:** 이벤트 간 `timestamp` 차이를 기반으로 자연스러운 속도로 재생합니다. MVP에서는 고정 2~3초 간격으로 시작하며, 이후 타임스탬프 기반 재생으로 개선 예정입니다.
- **루프 전환 처리:** 스크립트 마지막 이벤트 발행 후 `is_session_end: true` 이벤트를 한 번 발행하여 프론트엔드가 "세션 종료 — 재시작" UI를 표시할 수 있도록 합니다. 이후 짧은 대기 시간 후 루프를 재시작합니다.

| 필드명 | 타입 | 필수 | 설명 |
| :--- | :--- | :---: | :--- |
| `ticker` | String | Y | 종목 심볼 (예: `NVDA`) |
| `text_chunk` | String | Y | STT 원문 텍스트 (타이핑 효과 렌더링용) |
| `raw_score` | Double | Y | AI 순수 감성 점수 — 텐션 미터기(게이지) 표시용 |
| `ema_score` | Double | Y | EMA 추세 점수 — 추세선 차트 표시용 |
| `rationale` | String | Y | LLM 분석 근거 — 시그널 피드 텍스트 표시용 |
| `action` | String | Y | 룰 엔진 최종 판단 (`BUY`, `SELL`, `HOLD`) |
| `timestamp` | Long | Y | 원본 어닝콜 발생 시점 (Unix Epoch Second, UTC) |
| `is_session_end` | Boolean | N | 루프 종료 신호. `true`이면 프론트엔드가 재시작 UI 표시 (기본값 `false`) |

### 4.2. Public Broadcast (실시간 라이브 신호 시각화용)
- **Topic:** `/topic/live/{ticker}`
- **설명:** 실제 어닝콜이 진행 중일 때 로그인한 웹 유저에게 시각화용 데이터를 동일하게 브로드캐스트합니다. (주문 명령 없음)
- **접근 권한:** 로그인 필수 (JWT). Free 유저는 `action` 필드를 `null`로 수신하여 BUY/SELL 판단은 노출되지 않습니다.
- **주가 데이터:** Data Pipeline이 Redis `market-data` 채널로 푸시한 주가 tick을 백엔드가 이 채널에 병합하여 포워딩합니다.

| 필드명 | 타입 | 필수 | 설명 |
| :--- | :--- | :---: | :--- |
| `ticker` | String | Y | 종목 심볼 |
| `text_chunk` | String | Y | 실시간 STT 원문 텍스트 (타이핑 효과 렌더링용) |
| `raw_score` | Double | Y | AI 순수 감성 점수 — 텐션 미터기(게이지) 표시용 |
| `ema_score` | Double | Y | 백엔드 계산 EMA 추세 점수 — 추세선 차트 표시용 |
| `rationale` | String | Y | LLM 분석 근거 — 시그널 피드 텍스트 표시용 |
| `action` | String | N | 룰 엔진 최종 판단 (`BUY`, `SELL`, `HOLD`). **Pro 유저만 수신**, Free는 `null` |
| `price` | Double | N | 현재 주가 (USD). Data Pipeline 주가 데이터 수신 시 포함 |
| `change_pct` | Double | N | 전일 대비 등락률. Data Pipeline 주가 데이터 수신 시 포함 |
| `timestamp` | Long | Y | 신호 발생 시점 (Unix Epoch Second, UTC) |
| `is_session_end` | Boolean | N | 어닝콜 세션 종료 신호 (기본값 `false`) |

### 4.3. Private Routing (Trading Terminal 주문 지시용)
- **Queue:** `/user/{userId}/queue/signals`
- **설명:** 백엔드의 '자체 추정 장부(Internal Ledger)'와 유저의 리스크 룰을 통과한 **실제 매매 명령**을 특정 유저의 데스크톱 앱으로만 은밀하게 발송합니다.
- **수량 결정 원칙 (자본시장법 준수):** 백엔드는 **수량을 직접 계산하지 않고**, 사용자의 `PortfolioSettings.buyAmountRatio`를 `order_ratio` 필드로 실어 보냅니다. Trading Terminal이 주문 직전 실제 KIS 잔고·현재가를 조회하여 **사용자 로컬 PC에서 최종 수량을 산출**합니다. 이는 "중앙 서버가 사용자 대신 종목·수량·시점을 결정"하는 행위(미등록 투자일임업)를 회피하기 위한 설계입니다. 최종 체결 수량(`executed_qty`)은 콜백 API(Contract 4.1)로 보고되며, 백엔드는 이 값으로 `Trade.orderQty`를 덮어씁니다(PENDING 시점엔 0 센티널).

**수량 산출 공식 (Trading Terminal에서 적용):**
- BUY: `qty = floor(orderableCash × order_ratio / currentPrice)`
- SELL: `qty = floor(holdingQty × order_ratio)` (0이면 주문 안 함 — 서버 의도 비율 초과 매도 방지)

| 필드명 | 타입 | 필수 | 설명 |
| :--- | :--- | :---: | :--- |
| `trade_id` | String | Y | 백엔드가 DB에 생성한 `PENDING` 상태의 고유 거래 ID |
| `action` | String | Y | 최종 매매 방향 (`BUY`, `SELL`) |
| `order_ratio` | Double | Y | 주문 비율 (0.0 ~ 1.0). BUY: 예수금 대비 매수 비율. SELL: 보유수량 대비 매도 비율 |
| `ticker` | String | Y | 종목 심볼 |
| `ema_score` | Double | Y | 최종 결정에 사용된 EMA 점수 |

---

## 5. [Contract 4] Trading Terminal ➔ Backend (Callback & Sync)
로컬 PC에서 매매를 대신 실행한 Trading Terminal이 백엔드 장부(Ledger)와 상태를 일치시키기 위해 호출하는 핵심 REST API입니다.

### 5.1. 매매 체결 결과 보고 (Callback)
- **엔드포인트:** `POST /api/v1/trades/{tradeId}/callback`
- **설명:** Trading Terminal이 실제 KIS 잔고와 현재가를 조회하여 `order_ratio`에 따라 최종 수량을 산출하고 주문을 실행한 뒤, 체결 결과를 백엔드로 보고하여 DB 상태를 `EXECUTED` 또는 `FAILED`로 확정합니다. `Trade.orderQty`는 PENDING 시점엔 0(센티널)이며 본 콜백 수신 시 `executed_qty`로 덮어써집니다.

    {
      "status": "EXECUTED",
      "broker_order_id": "ODNO_123456789",
      "executed_price": 125.50,
      "executed_qty": 10,
      "error_message": null
    }

### 5.2. 실제 계좌 장부 동기화 (Sync)
- **엔드포인트:** `POST /api/v1/portfolio/sync`
- **설명:** Trading Terminal이 기동되거나 매매가 완료된 직후, 실제 KIS 계좌 잔고를 백엔드에 덮어씌워 룰 엔진의 오차를 교정합니다.

    {
      "total_cash": 15000000,
      "holdings": [
        { "ticker": "NVDA", "qty": 15, "avg_price": 120.00 }
      ]
    }

---

## 6. [Contract 6] Data Pipeline ➔ Backend (시장 데이터)

Data Pipeline 팀이 외부 주가/어닝 일정 데이터를 수집하여 백엔드로 전달하는 계약입니다.
백엔드는 수신 데이터를 DB에 저장 후 REST API로 프론트엔드에 제공합니다.

### 6.1. 어닝콜 일정 동기화 (Earnings Calendar)

> **⚠️ 아키텍처 변경 (2026-04-03):** 어닝콜 일정 수집은 Data Pipeline이 아닌 **백엔드가 Finnhub API를 직접 호출**하여 처리합니다. Data Pipeline → 백엔드 HTTP POST 계약은 폐기되었습니다. Data Pipeline 팀은 해당 기능을 구현하지 않아도 됩니다.

**현재 구현:**
- 백엔드 `FinnhubEarningsScheduler`가 매일 06:00 UTC에 Finnhub `/calendar/earnings` 를 호출하여 DB를 갱신합니다.
- 인증이 필요 없는 무료 엔드포인트이며 분당 60회 제한이 있으나, 배치(하루 1회)이므로 문제없습니다.
- 프론트엔드는 `/api/v1/earnings-calendar?days=60` GET으로 DB에서 직접 조회합니다 (7.6 참조).

**S&P 500 구성원 동기화:**
- FMP API를 통해 분기 1회(1·4·7·10월 1일 09:00 UTC) 자동 동기화합니다.
- 편입 종목 신규 추가, 제외 종목 soft delete(`active = false`) 처리합니다.

### 6.2. 실시간 주가 스트리밍 (Market Data)
- **통신 방식:** Redis Pub/Sub
- **Redis Channel:** `market-data`
- **설명:** 어닝콜 진행 중인 종목의 실시간 주가 tick 데이터를 스트리밍합니다. 백엔드는 해당 채널을 구독하여 WebSocket `/topic/live/{ticker}` 채널을 통해 프론트엔드로 포워딩합니다. **어닝콜이 진행 중인 종목만** 발행하며, 상시 시장 전체 tick은 범위 외입니다.

| 필드명 | 타입 | 필수 | 설명 |
| :--- | :--- | :---: | :--- |
| `ticker` | String | Y | 종목 심볼 |
| `price` | Double | Y | 현재 주가 (USD) |
| `change_pct` | Double | Y | 전일 대비 등락률 (예: `+2.35`, `-1.10`) |
| `timestamp` | Long | Y | 주가 기준 시각 (Unix Epoch Second, UTC) |

---

## 7. [Contract 7] Frontend/Terminal ➔ Backend (REST API 목록)

프론트엔드 Web 및 Trading Terminal이 호출하는 백엔드 REST API 전체 목록입니다.
모든 인증 필요 엔드포인트는 `Authorization: Bearer {accessToken}` 헤더가 필수입니다.

### 7.1. 인증 (Auth)

| Method | Endpoint | 인증 | 설명 |
| :--- | :--- | :---: | :--- |
| POST | `/api/v1/auth/signup` | 불필요 | 회원가입. 요청: `{email, password, nickname}` |
| POST | `/api/v1/auth/login` | 불필요 | 로그인. 응답: `{accessToken}` |

### 7.2. 사용자 (Users)

| Method | Endpoint | 인증 | 설명 |
| :--- | :--- | :---: | :--- |
| GET | `/api/v1/users/me` | 필요 | 내 프로필 조회. 응답: `{id, email, nickname, role, createdAt}` |
| PUT | `/api/v1/users/settings` | 필요 | 리스크 룰 설정 저장. 요청: `{trading_mode, max_buy_ratio, max_holding_ratio, cooldown_minutes}` |

### 7.3. 거래 내역 (Trades)

| Method | Endpoint | 인증 | 설명 |
| :--- | :--- | :---: | :--- |
| GET | `/api/v1/trades?page=0&size=20` | 필요 | 내 거래 내역 페이징 조회. 응답: Page 형태 |
| POST | `/api/v1/trades/{tradeId}/callback` | 필요 (Terminal JWT) | 체결 결과 콜백 (Contract 4.1 참조) |

### 7.4. 포트폴리오 (Portfolio)

| Method | Endpoint | 인증 | 설명 |
| :--- | :--- | :---: | :--- |
| POST | `/api/v1/portfolio/sync` | 필요 (Terminal JWT) | 실제 계좌 잔고 동기화 (Contract 4.2 참조) |

### 7.5. 관심종목 (Watchlist)

| Method | Endpoint | 인증 | 설명 |
| :--- | :--- | :---: | :--- |
| GET | `/api/v1/watchlist` | 필요 | 내 관심종목 목록 조회. 응답: `[{ticker, companyName, sector}]` |
| POST | `/api/v1/watchlist` | 필요 | 관심종목 추가. 요청: `{ticker}`. S&P 500 외 종목 요청 시 400 반환 |
| DELETE | `/api/v1/watchlist/{ticker}` | 필요 | 관심종목 삭제 |
| GET | `/api/v1/watchlist/search?q={query}` | 필요 | 종목 검색 (심볼·회사명, 최대 20건). 백엔드 DB(`stocks` 테이블) 기반 |

### 7.6. 어닝콜 일정 (Earnings Calendar)

| Method | Endpoint | 인증 | 설명 |
| :--- | :--- | :---: | :--- |
| GET | `/api/v1/earnings-calendar?days=60` | 필요 | 내 관심종목의 향후 N일 어닝콜 일정 조회. `days` 기본값 60. 응답: `[{ticker, companyName, scheduledAt, confirmed}]` |
| POST | `/api/v1/earnings-calendar/sync` | 불필요 | 어닝 일정 수동 갱신 (개발/테스트용). FINNHUB_API_KEY 미설정 시 409 반환 |

---

## 8. 공통 개발 가이드라인 (Common Rules)
1. **인증 방식:** JWT Bearer 토큰. 로그인 응답의 `accessToken`을 모든 인증 필요 요청의 `Authorization: Bearer {token}` 헤더에 포함. WebSocket STOMP 연결 시 CONNECT 프레임의 `Authorization` 헤더로 전달.
2. **플랜 접근 제어:** 유저 role은 `FREE` / `PRO` 두 가지. `action` (BUY/SELL 신호) 및 Trading Terminal 사용은 PRO 전용. FREE 유저는 `raw_score` 시각화까지만 접근 가능.
3. **내부 API 인증:** Data Pipeline → 백엔드 내부 전용 엔드포인트(`/api/v1/internal/*`)는 `X-Internal-Secret` 헤더로 공유 시크릿 검증.
4. **에러 처리:** REST API 통신 시 에러가 발생하면 무조건 HTTP Status `4xx` 또는 `500`과 함께 `{"error": "에러 상세 원인"}` 형태의 JSON을 반환해야 합니다.
5. **타임존:** 모든 `timestamp`는 **UTC** 기준의 Unix Epoch Second를 사용합니다. 프론트엔드 및 터미널 수신 후 로컬 브라우저/OS 시간으로 변환하여 표출합니다.
6. **무상태성 및 단일 진실 공급원:** 백엔드는 KIS API 키를 가지지 않으며, 모든 '최종' 자산 상태는 Trading Terminal이 쏘아주는 Sync 데이터를 '단일 진실 공급원(Single Source of Truth)'으로 취급하여 덮어씁니다.
7. **Fallback (안전망):** Trading Terminal은 백엔드 웹소켓 연결이 끊기거나 비정상적인 데이터가 수신될 경우, 즉시 매매 모드를 `MANUAL(수동)`로 강제 전환하고 유저에게 OS 네이티브 알림을 띄워야 합니다.
8. **매매 필터링 책임 분리 (2-Layer Filter):** 신호가 실제 주문으로 이어지기까지 두 단계의 독립적인 필터가 존재합니다. 두 필터는 서로 다른 관심사를 담당하며 중복이 아닙니다.

    | 레이어 | 주체 | 필터링 기준 | 결과 |
    | :--- | :--- | :--- | :--- |
    | **1차 (서버)** | Backend 룰 엔진 | EMA 임계치, 쿨다운, 장부 잔고/비중 조건 | 조건 미달 시 신호 자체를 생성하지 않음 (HOLD) |
    | **2차 (클라이언트)** | Trading Terminal 트레이딩 모드 | 사용자 승인 방식 (Manual / 1-Click / Auto-Pilot) | 신호를 수신하더라도 모드에 따라 즉시 실행하거나 사용자 승인을 대기 |

    즉, 백엔드가 신호를 보냈다고 해서 반드시 주문이 실행되는 것은 아닙니다. Terminal의 트레이딩 모드가 최종 실행 여부를 결정합니다.