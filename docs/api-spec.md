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

---

## 4. [Contract 3] Backend ➔ Clients (WebSocket Signaling)
백엔드는 목적에 따라 두 가지 방식의 웹소켓 채널을 운영합니다.

### 4.1. Public Broadcast (Frontend Web 데모용)
- **Topic:** `/topic/live/{ticker}`
- **설명:** 웹 대시보드 접속자 모두에게 시각화용 데이터(STT 텍스트, 게이지바 수치)를 동일하게 뿌려줍니다. (주문 명령 없음)

| 필드명 | 타입 | 필수 | 설명 |
| :--- | :--- | :---: | :--- |
| `ticker` | String | Y | 종목 심볼 |
| `text_chunk` | String | Y | 실시간 STT 원문 텍스트 (타이핑 효과 렌더링용) |
| `raw_score` | Double | Y | AI 순수 감성 점수 — 텐션 미터기(게이지) 표시용 |
| `ema_score` | Double | Y | 백엔드 계산 EMA 추세 점수 — 추세선 차트 표시용 |
| `rationale` | String | Y | LLM 분석 근거 — 시그널 피드 텍스트 표시용 |
| `action` | String | Y | 룰 엔진 최종 판단 (`BUY`, `SELL`, `HOLD`) |
| `timestamp` | Long | Y | 신호 발생 시점 (Unix Epoch Second, UTC) |

### 4.2. Private Routing (Trading Terminal 주문 지시용)
- **Queue:** `/user/{userId}/queue/signals`
- **설명:** 백엔드의 '자체 추정 장부(Internal Ledger)'와 유저의 리스크 룰을 통과한 **실제 매매 명령**을 특정 유저의 데스크톱 앱으로만 은밀하게 발송합니다.
- **수량 처리 원칙:** 백엔드는 자체 장부(Ledger) 기준으로 `target_qty`를 산출하여 전송합니다. Trading Terminal은 주문 직전 실제 KIS 증권사 잔고를 조회하여 수량을 보정(예: 예수금 부족 시 하향 조정)한 뒤 매매를 실행합니다. 최종 체결 수량(`executed_qty`)은 콜백 API(Contract 4.1)로 보고하여 백엔드 장부의 오차를 교정합니다.

| 필드명 | 타입 | 필수 | 설명 |
| :--- | :--- | :---: | :--- |
| `trade_id` | String | Y | 백엔드가 DB에 생성한 `PENDING` 상태의 고유 거래 ID |
| `action` | String | Y | 최종 매매 방향 (`BUY`, `SELL`) |
| `target_qty` | Integer | Y | 백엔드 장부(Ledger) 기준으로 산출한 목표 주문 수량. Terminal이 실제 잔고 조회 후 보정할 수 있음 |
| `ticker` | String | Y | 종목 심볼 |
| `ema_score` | Double | Y | 최종 결정에 사용된 EMA 점수 |

---

## 5. [Contract 4] Trading Terminal ➔ Backend (Callback & Sync)
로컬 PC에서 매매를 대신 실행한 Trading Terminal이 백엔드 장부(Ledger)와 상태를 일치시키기 위해 호출하는 핵심 REST API입니다.

### 5.1. 매매 체결 결과 보고 (Callback)
- **엔드포인트:** `POST /api/v1/trades/{tradeId}/callback`
- **설명:** Trading Terminal이 실제 KIS 잔고를 조회하여 수량을 보정한 뒤 주문을 실행하고, 체결 결과를 백엔드로 보고하여 DB 상태를 `EXECUTED` 또는 `FAILED`로 확정합니다. `executed_qty`는 백엔드가 산출한 `target_qty`와 다를 수 있으며, 이 값으로 자체 장부(Ledger)의 오차를 교정합니다.

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

## 6. [Contract 5] Frontend Web ➔ Backend (User Settings)
- **통신 방식:** HTTP PUT
- **엔드포인트:** `PUT /api/v1/users/settings`
- **설명:** SaaS 웹 대시보드(또는 Terminal 설정창)에서 유저가 수정한 리스크 관리 룰을 백엔드 DB에 저장합니다.

    {
      "trading_mode": "AUTO",
      "max_buy_ratio": 0.2,
      "max_holding_ratio": 0.5,
      "cooldown_minutes": 5
    }

---

## 7. 공통 개발 가이드라인 (Common Rules)
1. **에러 처리:** REST API 통신 시 에러가 발생하면 무조건 HTTP Status `4xx` 또는 `500`과 함께 `{"error": "에러 상세 원인"}` 형태의 JSON을 반환해야 합니다.
2. **타임존:** 모든 `timestamp`는 **UTC** 기준의 Unix Epoch Second를 사용합니다. 프론트엔드 및 터미널 수신 후 로컬 브라우저/OS 시간으로 변환하여 표출합니다.
3. **무상태성 및 단일 진실 공급원:** 백엔드는 API 키를 가지지 않으며, 모든 '최종' 자산 상태는 Trading Terminal이 쏘아주는 Sync 데이터를 '단일 진실 공급원(Single Source of Truth)'으로 취급하여 덮어씁니다.
4. **Fallback (안전망):** Trading Terminal은 백엔드 웹소켓 연결이 끊기거나 비정상적인 데이터가 수신될 경우, 즉시 매매 모드를 `MANUAL(수동)`로 강제 전환하고 유저에게 OS 네이티브 알림을 띄워야 합니다.
5. **매매 필터링 책임 분리 (2-Layer Filter):** 신호가 실제 주문으로 이어지기까지 두 단계의 독립적인 필터가 존재합니다. 두 필터는 서로 다른 관심사를 담당하며 중복이 아닙니다.

    | 레이어 | 주체 | 필터링 기준 | 결과 |
    | :--- | :--- | :--- | :--- |
    | **1차 (서버)** | Backend 룰 엔진 | EMA 임계치, 쿨다운, 장부 잔고/비중 조건 | 조건 미달 시 신호 자체를 생성하지 않음 (HOLD) |
    | **2차 (클라이언트)** | Trading Terminal 트레이딩 모드 | 사용자 승인 방식 (Manual / 1-Click / Auto-Pilot) | 신호를 수신하더라도 모드에 따라 즉시 실행하거나 사용자 승인을 대기 |

    즉, 백엔드가 신호를 보냈다고 해서 반드시 주문이 실행되는 것은 아닙니다. Terminal의 트레이딩 모드가 최종 실행 여부를 결정합니다.