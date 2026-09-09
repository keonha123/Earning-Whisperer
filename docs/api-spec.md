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
9. **Data Pipeline** (Python) ➔ `[Redis Pub/Sub]` ➔ **Backend** (Java) : 글로벌 시장 지수 1분 스트리밍
10. **Data Pipeline** (Python) ➔ `[HTTP POST]` ➔ **Backend** (Java) : 실시간 어닝콜 트랜스크립트 segment 전달 (AI Engine 분석용 슬라이딩 윈도우와 별개 출력)
11. **Backend** (Java) ➔ `[WebSocket /topic/transcript]` ➔ **Trading Terminal / Frontend Web** : 어닝콜 트랜스크립트 라이브 표시

---

## 2. [Contract 1] Data Pipeline ➔ AI Engine

- **통신 방식:** HTTP POST (비동기)
- **엔드포인트:** `http://ai-engine:8000/api/v1/analyze`
- **설명:** 오디오 스트림에서 추출 및 슬라이딩 윈도우(Overlapping) 처리가 완료된 약 10~15초 단위의 STT 텍스트 조각을 분석 서버로 전송합니다.

| 필드명       | 타입    | 필수 | 설명                                                  |
| :----------- | :------ | :--: | :---------------------------------------------------- |
| `ticker`     | String  |  Y   | 분석 대상 종목 심볼 (예: "NVDA")                      |
| `text_chunk` | String  |  Y   | 슬라이딩 윈도우가 적용된 실시간 STT 텍스트            |
| `sequence`   | Integer |  Y   | 텍스트 조각의 순차 번호 (0부터 1씩 증가, 순서 보장용) |
| `timestamp`  | Long    |  Y   | 오디오 캡처 기준 발생 시점 (Unix Epoch Second)        |
| `is_final`   | Boolean |  Y   | 해당 어닝콜 세션의 완전 종료 여부                     |

---

## 3. [Contract 2] AI Engine ➔ Backend (Raw Signal)

- **통신 방식:** Redis Pub/Sub
- **Redis Channel:** `trading-signals`
- **설명:** AI 서버(Stateless)가 텍스트를 분석하여 도출한 **순수 감성 점수(Raw Score)**와 해설을 백엔드로 브로드캐스팅합니다.

| 필드명           | 타입    | 필수 | 설명                                                                       |
| :--------------- | :------ | :--: | :------------------------------------------------------------------------- |
| `ticker`         | String  |  Y   | 분석 대상 종목 심볼                                                        |
| `raw_score`      | Double  |  Y   | 감성 방향 및 강도 (-1.0[강한 매도] ~ +1.0[강한 매수])                      |
| `rationale`      | String  |  Y   | LLM이 생성한 분석 근거                                                     |
| `text_chunk`     | String  |  Y   | 분석에 사용된 원문 텍스트                                                  |
| `timestamp`      | Long    |  Y   | 분석 완료 시점 (Unix Epoch Second)                                         |
| `is_session_end` | Boolean |  N   | 어닝콜 세션 종료 신호. `true`이면 백엔드가 세션 종료 처리 (기본값 `false`) |

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

| 필드명           | 타입    | 필수 | 설명                                                                    |
| :--------------- | :------ | :--: | :---------------------------------------------------------------------- |
| `ticker`         | String  |  Y   | 종목 심볼 (예: `NVDA`)                                                  |
| `text_chunk`     | String  |  Y   | STT 원문 텍스트 (타이핑 효과 렌더링용)                                  |
| `raw_score`      | Double  |  Y   | AI 순수 감성 점수 — 텐션 미터기(게이지) 표시용                          |
| `ema_score`      | Double  |  Y   | EMA 추세 점수 — 추세선 차트 표시용                                      |
| `rationale`      | String  |  Y   | LLM 분석 근거 — 시그널 피드 텍스트 표시용                               |
| `action`         | String  |  Y   | 룰 엔진 최종 판단 (`BUY`, `SELL`, `HOLD`)                               |
| `timestamp`      | Long    |  Y   | 원본 어닝콜 발생 시점 (Unix Epoch Second, UTC)                          |
| `is_session_end` | Boolean |  N   | 루프 종료 신호. `true`이면 프론트엔드가 재시작 UI 표시 (기본값 `false`) |

### 4.2. Public Broadcast (실시간 라이브 신호 시각화용)

- **Topic:** `/topic/live/{ticker}`
- **설명:** 실제 어닝콜이 진행 중일 때 로그인한 웹 유저에게 시각화용 데이터를 동일하게 브로드캐스트합니다. (주문 명령 없음)
- **접근 권한:** 로그인 필수 (JWT). Free 유저는 `action` 필드를 `null`로 수신하여 BUY/SELL 판단은 노출되지 않습니다.
- **주가 데이터:** Data Pipeline이 Redis `market-data` 채널로 푸시한 주가 tick을 백엔드가 이 채널에 병합하여 포워딩합니다.

| 필드명           | 타입    | 필수 | 설명                                                                          |
| :--------------- | :------ | :--: | :---------------------------------------------------------------------------- |
| `ticker`         | String  |  Y   | 종목 심볼                                                                     |
| `text_chunk`     | String  |  Y   | 실시간 STT 원문 텍스트 (타이핑 효과 렌더링용)                                 |
| `raw_score`      | Double  |  Y   | AI 순수 감성 점수 — 텐션 미터기(게이지) 표시용                                |
| `ema_score`      | Double  |  Y   | 백엔드 계산 EMA 추세 점수 — 추세선 차트 표시용                                |
| `rationale`      | String  |  Y   | LLM 분석 근거 — 시그널 피드 텍스트 표시용                                     |
| `action`         | String  |  N   | 룰 엔진 최종 판단 (`BUY`, `SELL`, `HOLD`). **Pro 유저만 수신**, Free는 `null` |
| `price`          | Double  |  N   | 현재 주가 (USD). Data Pipeline 주가 데이터 수신 시 포함                       |
| `change_pct`     | Double  |  N   | 전일 대비 등락률. Data Pipeline 주가 데이터 수신 시 포함                      |
| `timestamp`      | Long    |  Y   | 신호 발생 시점 (Unix Epoch Second, UTC)                                       |
| `is_session_end` | Boolean |  N   | 어닝콜 세션 종료 신호 (기본값 `false`)                                        |

### 4.3. Private Routing (Trading Terminal 주문 지시용)

- **Queue:** `/user/{userId}/queue/signals`
- **설명:** 백엔드의 '자체 추정 장부(Internal Ledger)'와 유저의 리스크 룰을 통과한 **실제 매매 명령**을 특정 유저의 데스크톱 앱으로만 은밀하게 발송합니다.
- **수량 결정 원칙 (자본시장법 준수):** 백엔드는 **수량을 직접 계산하지 않고**, 사용자의 `PortfolioSettings.buyAmountRatio`를 `order_ratio` 필드로 실어 보냅니다. Trading Terminal이 주문 직전 실제 KIS 잔고·현재가를 조회하여 **사용자 로컬 PC에서 최종 수량을 산출**합니다. 이는 "중앙 서버가 사용자 대신 종목·수량·시점을 결정"하는 행위(미등록 투자일임업)를 회피하기 위한 설계입니다. 최종 체결 수량(`executed_qty`)은 콜백 API(Contract 4.1)로 보고되며, 백엔드는 이 값으로 `Trade.orderQty`를 덮어씁니다(PENDING 시점엔 0 센티널).

**수량 산출 공식 (Trading Terminal에서 적용):**

- BUY: `qty = floor(orderableCash × order_ratio / currentPrice)`
- SELL: `qty = floor(holdingQty × order_ratio)` (0이면 주문 안 함 — 서버 의도 비율 초과 매도 방지)

| 필드명        | 타입   | 필수 | 설명                                                                             |
| :------------ | :----- | :--: | :------------------------------------------------------------------------------- |
| `trade_id`    | String |  Y   | 백엔드가 DB에 생성한 `PENDING` 상태의 고유 거래 ID                               |
| `action`      | String |  Y   | 최종 매매 방향 (`BUY`, `SELL`)                                                   |
| `order_ratio` | Double |  Y   | 주문 비율 (0.0 ~ 1.0). BUY: 예수금 대비 매수 비율. SELL: 보유수량 대비 매도 비율 |
| `ticker`      | String |  Y   | 종목 심볼                                                                        |
| `ema_score`   | Double |  Y   | 최종 결정에 사용된 EMA 점수                                                      |

### 4.4. Global Market Indices Broadcast (글로벌 시장 지수 1분 스트리밍)

- **Topic:** `/topic/market/indices`
- **인증:** 불필요 (공개 시장 데이터)
- **설명:** 5종 글로벌 시장 지수(SPX/NDX/VIX/DXY/10Y)의 1분 단위 스냅샷을 모든 클라이언트(Trading Terminal, Frontend Web)에 브로드캐스트합니다.
- **발행 시점:** Data Pipeline의 `market-indices` Redis 채널(Contract 6.3) 수신 즉시 백엔드가 fan-out합니다.
- **백엔드 가공 책임:**
  - `trend` 필드 자동 산출 (`change_percent > +0.05` → `up`, `< -0.05` → `down`, 그 외 `neutral`. 임계치는 운영 중 조정 가능)
  - `format` 필드 5심볼 상수 매핑 (Contract 6.3 표 참조)
  - `schema_version`, `source`, `published_at` 등 발행자 메타는 클라이언트에 전달하지 않음

| 필드명           | 타입   | 필수 | 설명                                      |
| :--------------- | :----- | :--: | :---------------------------------------- |
| `symbol`         | String |  Y   | `SPX` \| `NDX` \| `VIX` \| `DXY` \| `10Y` |
| `price`          | Double |  Y   | 현재 지수값                               |
| `change_percent` | Double |  Y   | 전일 대비 등락률                          |
| `trend`          | String |  Y   | `up` \| `down` \| `neutral` (백엔드 산출) |
| `format`         | String |  Y   | `index` \| `percent` (백엔드 매핑)        |
| `timestamp`      | Long   |  Y   | 데이터 기준 시각 (Unix Epoch Second, UTC) |

> **구독 예시:** `stompClient.subscribe('/topic/market/indices', handler)`

### 4.5. Live Earnings Call Transcript Broadcast (실시간 어닝콜 스크립트 표시용)

- **Topic:** `/topic/transcript/{ticker}`
- **인증:** 로그인 필수 (JWT). 4.2 Public Broadcast와 동일 정책.
- **설명:** 실제 어닝콜 진행 중인 종목의 STT 트랜스크립트를 **stabilized segment 단위**(슬라이딩 윈도우 안정화 후 확정된 부분)로 클라이언트에 브로드캐스트합니다. Trading Terminal의 trading-room STT 패널·Frontend Web 라이브룸의 스크립트 영역이 구독합니다.
- **발행 시점:** Data Pipeline의 Contract 6.4 HTTP POST 수신 즉시 백엔드가 fan-out (저장 책임 외 가공 없음).
- **분석 시그널 채널과의 관계:** 본 채널은 **원문 스크립트 전용**입니다. AI 분석 시그널(`/topic/live/{ticker}`)과 독립이며, 클라이언트는 두 채널을 동시 구독하여 STT 패널과 분석 카드 영역을 각각 갱신합니다.
- **append-only 시맨틱:** 같은 `call_id` 내 `sequence`는 단조 증가, 동일 segment의 재발행 없음. 클라이언트는 `sequence` 누락 감지 시 REST fallback(추후 정의) 또는 다음 segment 도착으로 자연 복구.

| 필드명           | 타입    | 필수 | 설명                                                                                  |
| :--------------- | :------ | :--: | :------------------------------------------------------------------------------------ |
| `ticker`         | String  |  Y   | 종목 심볼                                                                             |
| `call_id`        | String  |  Y   | 어닝콜 세션 식별자 (예: `NVDA-2026Q1`)                                                |
| `sequence`       | Integer |  Y   | segment 순차 번호 (어닝콜 세션 내 단조 증가)                                          |
| `start_ms`       | Long    |  Y   | segment 시작 시각 (오디오 캡처 기준, milliseconds)                                    |
| `end_ms`         | Long    |  Y   | segment 종료 시각 (오디오 캡처 기준, milliseconds)                                    |
| `text`           | String  |  Y   | stabilized segment 텍스트 (오버랩 제거 완료)                                          |
| `speaker`        | String  |  N   | 화자 라벨 (`CEO`, `CFO`, `Q&A` 등). STT 메타로 식별 가능 시                           |
| `timestamp`      | Long    |  Y   | 발행 시각 (Unix Epoch Second, UTC)                                                    |
| `is_session_end` | Boolean |  N   | 어닝콜 세션 종료 신호 (기본값 `false`). `true` 수신 시 클라이언트는 "콜 종료" UI 표시 |

> **구독 예시:** `stompClient.subscribe('/topic/transcript/NVDA', handler)`

---

### 4.6. Live Fact-Check Broadcast (실시간 어닝콜 팩트체크 표시용)

- **Topic:** `/topic/factcheck/{ticker}`
- **인증:** 로그인 필수 (JWT). 4.5와 동일 정책.
- **설명:** 어닝콜 발언 중 검증 가능한 주장을 AI Engine이 뉴스 근거와 대조한 결과를 브로드캐스트합니다. Trading Terminal의 팩트체크 패널이 구독합니다.
- **발행 시점:** AI Engine이 3문장 배치 검증을 마치고 `status=COMPLETED` 이며 `claims[]`가 비어 있지 않을 때만 발행합니다. `BUFFERING`/`REJECTED`/`DISCARDED`와 주장이 0건인 배치는 화면에 표시할 것이 없으므로 발행하지 않습니다.
- **트랜스크립트 채널과의 관계:** 4.5는 발언 원문, 본 채널은 그 발언에 대한 검증 결과입니다. 검증에 LLM 2패스(실측 5~15초)가 걸리므로 **팩트체크는 해당 발언보다 늦게 도착합니다.** 클라이언트는 `batch_start_sequence`~`batch_end_sequence` 범위로 어느 발언에 대한 판정인지 매칭합니다.

| 필드명                 | 타입    | 필수 | 설명                                                    |
| :--------------------- | :------ | :--: | :------------------------------------------------------ |
| `ticker`               | String  |  Y   | 종목 심볼                                               |
| `call_id`              | String  |  Y   | 어닝콜 세션 식별자 (4.5와 동일 값)                      |
| `batch_start_sequence` | Integer |  Y   | 검증 대상 문장 범위의 시작 `sequence`                   |
| `batch_end_sequence`   | Integer |  Y   | 검증 대상 문장 범위의 끝 `sequence`                     |
| `claims`               | Array   |  Y   | 판정 목록. 항목 스키마는 Contract 9.3과 동일 (1건 이상) |

> **표기 규칙:** `verdict`의 화면 표기는 Contract 9.5 참조 (`SUPPORTED`=사실 확인, `CONTRADICTED`=사실과 다름, `INSUFFICIENT_EVIDENCE`=근거 부족).
>
> **구독 예시:** `stompClient.subscribe('/topic/factcheck/ORCL', handler)`

---

### 4.7. Earnings Call Summary Broadcast (어닝콜 종료 후 종합 판단)

- **Topic:** `/topic/evaluation/{ticker}`
- **인증:** 로그인 필수 (JWT). 4.5/4.6과 동일 정책.
- **설명:** 어닝콜 재생이 끝난 뒤 **회차당 한 번** 발행되는 종합 판단입니다. 4.6이 문장 단위 사실 검증이라면, 본 채널은 콜 전체를 놓고 낸 방향·강도·신뢰도와 그에 딸린 회피 지표·파급효과·손절 계획입니다.
- **발행 시점:** 재생이 정상 완료되고(중지된 회차 제외) 세그먼트가 1건 이상 발행되었으며, AI Engine이 판단 본문(`judgment`)을 돌려준 경우에만 발행합니다. 판단이 없으면 발행하지 않습니다 — 빈 화면보다 "종합 판단 없음"이 정확합니다.
- **소요 시간:** 즉시 오지 않습니다. 마지막 세그먼트 직후 제출되지만, LLM 리뷰 패스(`analyze`)와 부가 정보 조회(`earnings/intelligence`)를 순서대로 타므로 정상적으로도 수 초에서 십수 초가 걸리고, AI Engine 이 응답하지 않으면 읽기 타임아웃(`ai-engine.timeout-ms`, 기본 50초) 두 번을 소진한 뒤 발행 없이 끝납니다.
- **발행되지 않는 경우:** 중지된 회차, 세그먼트 0건인 회차, `ai-engine.summary-enabled=false`, 어닝콜 전문이 비어 있는 경우, `analyze` 가 판단 본문을 돌려주지 않은 경우. 모두 로그에 사유가 남습니다.
- **회차 대조:** 같은 종목을 연달아 재생하면 클라이언트가 이전 회차의 판단을 받을 수 있습니다. **반드시 `call_id` 를 현재 회차(4.5의 `call_id`)와 대조하고 다르면 무시하세요.** 백엔드도 발행 직전에 같은 검사를 하지만, 두 곳에서 막는 편이 안전합니다.

| 필드명         | 타입    | 필수 | 설명                                                          |
| :------------- | :------ | :--: | :------------------------------------------------------------ |
| `ticker`                 | String  |  Y   | 종목 심볼                                                     |
| `call_id`                | String  |  Y   | 어닝콜 세션 식별자 (4.5/4.6과 동일 값)                        |
| `generated_at`           | String  |  Y   | 생성 시각 (ISO-8601)                                          |
| `judgment`               | Object  |  Y   | LLM 판단 본문. 스키마는 Contract 9.6 응답의 `analysis`와 동일 |
| `gate`                   | Object  |  N   | 실행 가능성 게이트. Contract 9.6 응답의 `signal_brief`와 동일 |
| `intelligence_available` | Boolean |  N   | 부가 정보 조회 성공 여부. 아래 설명 참조                      |
| `evasion`                | Object  |  N   | 질문 회피 지표. Contract 9.7 응답의 `omission_evasion`         |
| `impact_chain`           | Array   |  N   | 연쇄 영향 후보. Contract 9.7 응답과 동일                       |
| `risk_plan`              | Object  |  N   | 손절/익절 계획. Contract 9.7 응답과 동일                       |
| `warnings`               | Array   |  N   | 엔진이 붙인 주의사항 문자열                                   |

> **`N` 의 인코딩이 두 가지입니다.** 위 표의 최상위 필드는 값이 없으면 **키 자체가 없습니다**(`NON_NULL` 직렬화). 반면 중첩 객체(`judgment` / `gate` / `risk_plan` 등) 내부의 없는 값은 **명시적 `null`** 로 옵니다. 클라이언트는 `'key' in payload` 가 아니라 옵셔널 접근으로 다루세요.
>
> **`evasion` / `impact_chain` / `risk_plan` / `warnings` 는 하나의 원자 그룹입니다.** 같이 오거나 같이 없습니다(모두 Contract 9.7 한 번의 호출에서 나오기 때문). `intelligence_available=false` 면 **조회 자체가 실패**한 것이고, `true` 인데 `risk_plan.available=false` 면 **엔진이 "계획을 낼 수 없다"고 답한** 것입니다. 화면에서 이 둘을 다르게 말해야 합니다 — 전자는 "부가 정보를 가져오지 못했습니다", 후자는 `risk_plan.invalidation_text` 의 사유.

> **`judgment`와 `gate`를 한 줄에 그리지 마세요.** `gate.action`은 판단 방향이 아니라 "이 판단대로 움직여도 되는가"의 답입니다. 뉴스 근거가 적재되지 않은 상태에서는 `missing_rag_evidence` 때문에 **`judgment.direction=BULLISH`인데 `gate.action=AVOID`** 가 정상적으로 나옵니다. 두 값을 나란히 놓으면 모순으로 읽히므로, 화면에서는 "판단"과 "실행 보류 사유"를 분리해 표시합니다.
>
> **`warnings`를 숨기지 마세요.** "RAG evidence is empty" 같은 항목이 여기 옵니다. 감추면 검증되지 않은 판단이 검증된 것처럼 보입니다.
>
> **구독 예시:** `stompClient.subscribe('/topic/evaluation/ORCL', handler)`

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

| 필드명       | 타입   | 필수 | 설명                                    |
| :----------- | :----- | :--: | :-------------------------------------- |
| `ticker`     | String |  Y   | 종목 심볼                               |
| `price`      | Double |  Y   | 현재 주가 (USD)                         |
| `change_pct` | Double |  Y   | 전일 대비 등락률 (예: `+2.35`, `-1.10`) |
| `timestamp`  | Long   |  Y   | 주가 기준 시각 (Unix Epoch Second, UTC) |

### 6.3. 글로벌 시장 지수 스트리밍 (Market Indices)

- **통신 방식:** Redis Pub/Sub
- **Redis Channel:** `market-indices`
- **설명:** 5종 글로벌 시장 지수(SPX/NDX/VIX/DXY/10Y)의 1분 단위 스냅샷을 발행합니다. 백엔드는 해당 채널을 구독하여 `trend`/`format` 필드를 가공한 뒤 STOMP `/topic/market/indices`(Contract 4.4)로 fan-out합니다.

| 필드명           | 타입   | 필수 | 설명                                                                          |
| :--------------- | :----- | :--: | :---------------------------------------------------------------------------- |
| `schema_version` | String |  Y   | 스키마 버전. 현재 `"1.0"`                                                     |
| `source`         | String |  Y   | 데이터 소스 식별자 (예: `"yfinance"`)                                         |
| `symbol`         | String |  Y   | `SPX` \| `NDX` \| `VIX` \| `DXY` \| `10Y`                                     |
| `price`          | Double |  Y   | 현재 지수값 (소수점 2자리 정밀도)                                             |
| `change_percent` | Double |  Y   | 전일 대비 등락률 (소수점 2자리)                                               |
| `timestamp`      | Long   |  Y   | **데이터 기준 시각** (외부 소스 last bar timestamp, Unix Epoch Second UTC)    |
| `published_at`   | Long   |  N   | 발행 시각 (Unix Epoch Second UTC). `timestamp`와 다를 수 있음 (1분 폴링 간격) |

**발행 단위:**

- 심볼별 단건 발행 (5종 → 분당 5회 publish, 배열 묶음 X). 부분 실패 격리·`market-data` 패턴과 일관.
- `trend`/`format` 필드 없음 — 발행자 책임이 아님. 백엔드가 가공해서 클라이언트에 전달 (Contract 4.4).

**5심볼 매핑 (백엔드 상수, 발행자 참고):**

| Symbol | yfinance Ticker                      | format (백엔드 매핑) |
| :----- | :----------------------------------- | :------------------: |
| SPX    | `^GSPC`                              |       `index`        |
| NDX    | `^NDX`                               |       `index`        |
| VIX    | `^VIX`                               |       `index`        |
| DXY    | `DX-Y.NYB` (결측 시 `DX=F` fallback) |       `index`        |
| 10Y    | `^TNX`                               |      `percent`       |

**폴링 정책:**

- 미국 장중(09:30–16:00 ET) **1분 간격**
- 장외/주말 **5분 간격으로 강등**
- 거래소 휴장일은 폴링 정지 (`pandas_market_calendars` 권장)

**발행 실패 처리:**

- 외부 API 호출 실패 시 **해당 심볼 publish 스킵**. 직전값 재발행 금지(stale 데이터를 fresh로 오인 방지).
- 백엔드는 last-known-value 캐시를 유지하여 신규 발행이 없으면 직전값을 보존.
- **연속 실패 SLA:** 동일 심볼 연속 5분(5회) 실패 시 알림(로깅 + 운영 채널). 구체 알림 채널은 인프라 팀 합의.

**헬스체크:**

- Redis 별도 채널 `market-indices:health`에 1분 단위 heartbeat publish 또는 Redis key `market-indices:last-publish` TTL 갱신.
- 백엔드가 발행자 생존을 모니터링하여 stale 상태를 운영팀에 알림.

**메시지 ordering:**

- Redis Pub/Sub 특성상 순서 미보장. 구독자(백엔드)가 `timestamp` 기준 정렬 책임.

**소수점 정밀도:**

- `price` 소수 2자리, `change_percent` 소수 2자리 권장.

**발행 예시 (SPX):**

    {
      "schema_version": "1.0",
      "source": "yfinance",
      "symbol": "SPX",
      "price": 5432.10,
      "change_percent": 0.42,
      "timestamp": 1730000000,
      "published_at": 1730000003
    }

### 6.4. 실시간 어닝콜 트랜스크립트 (Live Earnings Call Transcript)

- **통신 방식:** HTTP POST (비동기, segment 단위 push)
- **엔드포인트:** `POST {backend}/api/v1/internal/transcript-segment`
- **인증:** `X-Internal-Secret` 공유 시크릿 (Contract 8.3)
- **설명:** Data Pipeline이 `faster-whisper`로 변환한 STT 텍스트 중 **stabilized segment**(오버랩 슬라이딩 윈도우 안정화 후 확정된 부분)를 백엔드에 segment 단위로 즉시 push합니다. 백엔드는 수신 즉시 STOMP `/topic/transcript/{ticker}`(Contract 4.5)로 fan-out하며 가공/저장 외 변환은 수행하지 않습니다.
- **AI Engine용 출력과의 관계:** 본 contract는 **AI Engine으로 가는 슬라이딩 윈도우 chunk(Contract 1)와 별개의 출력**입니다. 같은 transcribe 결과에서 두 형태로 fan-out하며, 추론 비용은 공유되고 추가 비용은 HTTP POST 1회뿐입니다.
  - Contract 1 (`/api/v1/analyze`) → 분석용. 10~15초 슬라이딩 윈도우 + 5~7초 오버랩 (문맥 보존 목적)
  - Contract 6.4 (본 항목) → 화면 표시용. 오버랩 제거된 stabilized segment (중복·문장 깨짐 방지 목적)

**Stabilization 요구사항 (출력 단위):**

- 단순 시간 단위 cutting 금지: batch 경계에 발화가 걸치면 단어/의미가 깨져 화면에 부적합. (`data-pipeline/README.md` Feature 3의 "문맥 단절" 방지 원칙과 동일선상)
- 오버랩 슬라이딩 윈도우 + **LocalAgreement-2** (또는 그에 준하는 stabilization 알고리즘) 적용. 두 연속 윈도우의 공통 prefix만 "확정"으로 emit.
- 동일 segment의 중복 emit 금지 (sequence는 어닝콜 세션 내 단조 증가).
- 의도된 지연 5~10초 허용 (실시간감 vs 정확성 trade-off). 윈도우 크기·전진 폭으로 운영 중 조정 가능.

**세션 종료 신호:**

- 어닝콜 종료 시 마지막 segment에 `is_session_end: true`를 1회 발행 후 같은 `call_id`로 추가 발행 금지.
- 백엔드는 해당 신호를 STOMP 페이로드에 그대로 전파.

| 필드명           | 타입    | 필수 | 설명                                                                   |
| :--------------- | :------ | :--: | :--------------------------------------------------------------------- |
| `ticker`         | String  |  Y   | 종목 심볼 (예: `NVDA`)                                                 |
| `call_id`        | String  |  Y   | 어닝콜 세션 식별자 (예: `NVDA-2026Q1`). 동일 종목 멀티콜·재방송 구분용 |
| `sequence`       | Integer |  Y   | segment 순차 번호 (0부터 1씩 증가, 어닝콜 세션 내 단조 증가)           |
| `start_ms`       | Long    |  Y   | segment 시작 시각 (오디오 캡처 기준, milliseconds)                     |
| `end_ms`         | Long    |  Y   | segment 종료 시각 (오디오 캡처 기준, milliseconds)                     |
| `text`           | String  |  Y   | stabilized segment 텍스트 (오버랩 제거 완료, 보통 1~10초 분량 한 호흡) |
| `speaker`        | String  |  N   | 화자 라벨 (`CEO`, `CFO`, `Q&A` 등). STT 메타로 식별 가능 시            |
| `timestamp`      | Long    |  Y   | 발행 시각 (Unix Epoch Second, UTC)                                     |
| `is_session_end` | Boolean |  N   | 어닝콜 세션 종료 신호 (기본값 `false`)                                 |

**발행 예시:**

    {
      "ticker": "NVDA",
      "call_id": "NVDA-2026Q1",
      "sequence": 142,
      "start_ms": 873000,
      "end_ms": 879500,
      "text": "We saw record demand in data center this quarter.",
      "speaker": "CEO",
      "timestamp": 1730000000,
      "is_session_end": false
    }

**백엔드 응답:**

- `202 Accepted` (정상 수신, fan-out 큐 적재 완료)
- `400 Bad Request` (필수 필드 누락 또는 sequence 역행)
- `401 Unauthorized` (`X-Internal-Secret` 미일치)
- `409 Conflict` (`is_session_end: true` 이후 같은 `call_id` 재발행)

---

## 7. [Contract 7] Frontend/Terminal ➔ Backend (REST API 목록)

프론트엔드 Web 및 Trading Terminal이 호출하는 백엔드 REST API 전체 목록입니다.
모든 인증 필요 엔드포인트는 `Authorization: Bearer {accessToken}` 헤더가 필수입니다.

### 7.1. 인증 (Auth)

| Method | Endpoint              |  인증  | 설명                                          |
| :----- | :-------------------- | :----: | :-------------------------------------------- |
| POST   | `/api/v1/auth/signup` | 불필요 | 회원가입. 요청: `{email, password, nickname}` |
| POST   | `/api/v1/auth/login`  | 불필요 | 로그인. 응답: `{accessToken}`                 |

### 7.2. 사용자 (Users)

| Method | Endpoint                 | 인증 | 설명                                                                                            |
| :----- | :----------------------- | :--: | :---------------------------------------------------------------------------------------------- |
| GET    | `/api/v1/users/me`       | 필요 | 내 프로필 조회. 응답: `{id, email, nickname, role, createdAt}`                                  |
| PUT    | `/api/v1/users/settings` | 필요 | 리스크 룰 설정 저장. 요청: `{trading_mode, max_buy_ratio, max_holding_ratio, cooldown_minutes}` |

### 7.3. 거래 내역 (Trades)

| Method | Endpoint                            |        인증         | 설명                                      |
| :----- | :---------------------------------- | :-----------------: | :---------------------------------------- |
| GET    | `/api/v1/trades?page=0&size=20`     |        필요         | 내 거래 내역 페이징 조회. 응답: Page 형태 |
| POST   | `/api/v1/trades/{tradeId}/callback` | 필요 (Terminal JWT) | 체결 결과 콜백 (Contract 4.1 참조)        |

### 7.4. 포트폴리오 (Portfolio)

| Method | Endpoint                 |        인증         | 설명                                      |
| :----- | :----------------------- | :-----------------: | :---------------------------------------- |
| POST   | `/api/v1/portfolio/sync` | 필요 (Terminal JWT) | 실제 계좌 잔고 동기화 (Contract 4.2 참조) |

### 7.5. 관심종목 (Watchlist)

| Method | Endpoint                             | 인증 | 설명                                                                |
| :----- | :----------------------------------- | :--: | :------------------------------------------------------------------ |
| GET    | `/api/v1/watchlist`                  | 필요 | 내 관심종목 목록 조회. 응답: `[{ticker, companyName, sector}]`      |
| POST   | `/api/v1/watchlist`                  | 필요 | 관심종목 추가. 요청: `{ticker}`. S&P 500 외 종목 요청 시 400 반환   |
| DELETE | `/api/v1/watchlist/{ticker}`         | 필요 | 관심종목 삭제                                                       |
| GET    | `/api/v1/watchlist/search?q={query}` | 필요 | 종목 검색 (심볼·회사명, 최대 20건). 백엔드 DB(`stocks` 테이블) 기반 |

### 7.6. 어닝콜 일정 (Earnings Calendar)

| Method | Endpoint                            |  인증  | 설명                                                                                                               |
| :----- | :---------------------------------- | :----: | :----------------------------------------------------------------------------------------------------------------- |
| GET    | `/api/v1/earnings-calendar?days=60` |  필요  | 내 관심종목의 향후 N일 어닝콜 일정 조회. `days` 기본값 60. 응답: `[{ticker, companyName, scheduledAt, confirmed}]` |
| POST   | `/api/v1/earnings-calendar/sync`    | 불필요 | 어닝 일정 수동 갱신 (개발/테스트용). FINNHUB_API_KEY 미설정 시 409 반환                                            |

### 7.7. 글로벌 시장 지수 (Market Indices)

| Method | Endpoint                 |  인증  | 설명                                                                                                                                  |
| :----- | :----------------------- | :----: | :------------------------------------------------------------------------------------------------------------------------------------ |
| GET    | `/api/v1/market/indices` | 불필요 | 백엔드 캐싱된 5종 지수 스냅샷 조회. 응답 필드는 Contract 4.4 와 동일. 백엔드 기동 직후 Data Pipeline 첫 발행 전에는 빈 배열 `[]` 반환 |

응답 예시 (장중 정상):

    [
      { "symbol": "SPX", "price": 5432.10, "change_percent": 0.42, "trend": "up", "format": "index", "timestamp": 1730000000 },
      { "symbol": "NDX", "price": 18750.55, "change_percent": 0.38, "trend": "up", "format": "index", "timestamp": 1730000000 },
      { "symbol": "VIX", "price": 14.20, "change_percent": -1.10, "trend": "down", "format": "index", "timestamp": 1730000000 },
      { "symbol": "DXY", "price": 104.32, "change_percent": 0.01, "trend": "neutral", "format": "index", "timestamp": 1730000000 },
      { "symbol": "10Y", "price": 4.25, "change_percent": -0.30, "trend": "down", "format": "percent", "timestamp": 1730000000 }
    ]

> **초기 로드 전략:** Trading Terminal/Frontend Web 마운트 시 본 엔드포인트로 1회 GET 후 `/topic/market/indices` STOMP 구독. REST 응답이 빈 배열이면 placeholder 유지하고 STOMP 수신 시 즉시 렌더로 전환.

### 7.8. 어닝콜 시연 재생 제어 (Demo Earnings Call)

| Method | Endpoint                            | 인증 | 설명                             |
| :----- | :---------------------------------- | :--: | :------------------------------- |
| POST   | `/api/v1/demo/earnings-call/start`  | 필요 | 준비된 어닝콜 스크립트 재생 시작 |
| POST   | `/api/v1/demo/earnings-call/stop`   | 필요 | 재생 중지                        |
| GET    | `/api/v1/demo/earnings-call/status` | 필요 | 진행 상황 조회 (`?ticker=ORCL`)  |

- **설명:** 시연에서 Data Pipeline의 STT 단계를 사전 준비된 스크립트가 대신합니다. 재생된 세그먼트는 **실제 인입 경로**(`TranscriptService` 검증 → Contract 4.5 fan-out)를 그대로 통과하며, 동시에 Contract 9로 AI Engine 팩트체크를 거쳐 Contract 4.6으로 발행됩니다. 클라이언트가 가짜 데이터를 그리는 구조가 아닙니다.
- **요청 본문(start/stop):** `{"ticker": "ORCL"}`. start에서 생략하면 스크립트에 지정된 기본 종목을 사용합니다.

| 상태 코드 | 의미                                        |
| :-------- | :------------------------------------------ |
| 202       | 재생 시작 (비동기 진행). `call_id` 반환     |
| 409       | 해당 종목이 이미 재생 중 — 먼저 중지해야 함 |
| 500       | 스크립트 파일을 읽을 수 없음                |
| 404       | (stop) 진행 중인 재생이 없음                |

start 응답 예시:

    { "ticker": "ORCL", "call_id": "demo-orcl-q4fy26-1788886133461-1", "segment_count": 6, "interval_ms": 6000 }

- **`call_id`는 재생 회차마다 새로 생성됩니다.** 같은 값을 재사용하면 `TranscriptSessionRegistry`가 종료된 세션으로 판단해 모든 세그먼트를 거부합니다(조용한 실패).
- **status는 끝난 재생의 결과도 알려줍니다.** 재생 중이 아니면 `running:false`와 함께 `last_run`을 반환합니다. `outcome`은 `COMPLETED` / `STOPPED` / `NO_SEGMENT_PUBLISHED` 중 하나입니다. 세 번째는 스크립트 결함 등으로 세그먼트를 하나도 내보내지 못하고 끝난 경우로, 이것이 없으면 "정상 완료"·"시작한 적 없음"과 구별되지 않습니다.

      { "running": false, "ticker": "ORCL",
        "last_run": { "call_id": "...", "outcome": "COMPLETED", "published_count": 6, "total_segments": 6 } }

- **스크립트 교체 시 규칙.** 시작 시점에 검증하며, 위반하면 500(`SCRIPT_UNAVAILABLE`)으로 거부합니다.
  1. `sequence`는 **0부터 1씩 증가**해야 합니다. 0에서 시작하지 않으면 AI Engine의 ticker 버퍼가 초기화되지 않습니다 — AI Engine은 `call_id`가 아니라 `ticker`로 버퍼를 잡고 `sentence_sequence=0`에서만 리셋하므로, 중지 후 재시작 시 트랜스크립트는 정상인데 팩트체크만 전부 조용히 사라집니다.
  2. `text`는 비어 있을 수 없습니다.
  3. 세그먼트 수는 **3의 배수**를 권장합니다. AI Engine이 3문장 단위로 검증하므로 나머지 1~2문장은 `DISCARDED`되어 마지막 발언들의 팩트체크가 나오지 않습니다. 위반해도 시작은 되지만 기동 로그에 경고가 남습니다.
- **관련 설정:** `demo.earnings-call.script-path`, `demo.earnings-call.interval-ms`, `ai-engine.base-url`, `ai-engine.fact-check-enabled`, `ai-engine.timeout-ms`. `fact-check-enabled=false`로 두면 AI Engine 없이 트랜스크립트 재생만 수행합니다.

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

   | 레이어               | 주체                           | 필터링 기준                                      | 결과                                                               |
   | :------------------- | :----------------------------- | :----------------------------------------------- | :----------------------------------------------------------------- |
   | **1차 (서버)**       | Backend 룰 엔진                | EMA 임계치, 쿨다운, 장부 잔고/비중 조건          | 조건 미달 시 신호 자체를 생성하지 않음 (HOLD)                      |
   | **2차 (클라이언트)** | Trading Terminal 트레이딩 모드 | 사용자 승인 방식 (Manual / 1-Click / Auto-Pilot) | 신호를 수신하더라도 모드에 따라 즉시 실행하거나 사용자 승인을 대기 |

   즉, 백엔드가 신호를 보냈다고 해서 반드시 주문이 실행되는 것은 아닙니다. Terminal의 트레이딩 모드가 최종 실행 여부를 결정합니다.

---

## 9. [Contract 9] Backend ➔ AI Engine (실시간 팩트체크 · 종합 판단)

- **통신 방식:** HTTP POST (동기)
- **엔드포인트:** `http://ai-engine:8000/v1/engine/live-fact-check/sentence`
- **설명:** 어닝콜이 진행되는 동안 확정된 문장을 **1개씩** AI Engine에 제출합니다. AI Engine은 ticker별로 **3문장 버퍼**를 유지하다가 3문장이 모이면 Gemini 2패스(검증 가능한 주장 추출 → 뉴스 근거 대조)를 실행하고 판정을 반환합니다. 백엔드는 결과를 STOMP `/topic/factcheck/{ticker}`로 fan-out합니다.
- **기존 `/v1/engine/fact-check`와 다른 엔드포인트입니다.** 그쪽은 LLM을 쓰지 않는 단발 유사도 검증이라 숫자 모순을 잡지 못합니다. 상세 비교는 `ai-engine/docs/LIVE_FACT_CHECK_API.md` 참조.

### 9.1. 요청

| 필드명               | 타입    | 필수 | 설명                                                            |
| :------------------- | :------ | :--: | :-------------------------------------------------------------- |
| `ticker`             | String  |  Y   | 분석 대상 종목 심볼 (예: "ORCL")                                |
| `sentence`           | String  |  Y   | 확정된 어닝콜 문장 1개                                          |
| `sentence_sequence`  | Integer |  Y   | 세션 내 문장 순번 (0부터 단조 증가). `0` 재전송 시 버퍼 초기화  |
| `sentence_timestamp` | Long    |  Y   | Unix Epoch Second. **근거 검색 기준 시점** (9.4 주의사항 참조)  |
| `is_session_end`     | Boolean |  N   | 어닝콜 세션 종료 여부 (기본값 `false`)                          |

### 9.2. 응답

**HTTP 상태는 정상 흐름 전체가 200입니다.** 요청 스키마 위반만 422입니다. 호출자는 반드시 본문 `status`를 분기해야 합니다.

| `status`    | 발생 조건                    | 백엔드 처리                             |
| :---------- | :--------------------------- | :-------------------------------------- |
| `BUFFERING` | 3문장 미충족 (1~2번째 문장)  | fan-out 없음. 정상                      |
| `COMPLETED` | 3문장 충족, 검증 완료        | `claims[]`를 `/topic/factcheck/{ticker}`로 발행 |
| `REJECTED`  | 중복/역행 시퀀스             | 로그만. 재전송 금지                     |
| `DISCARDED` | 3문장 미만인 채 세션 종료    | 자투리 문장 폐기. 정상                  |

| 필드명                  | 타입    | 설명                                                    |
| :---------------------- | :------ | :------------------------------------------------------ |
| `ticker`                | String  | 정규화된(대문자) 종목 심볼                              |
| `status`                | String  | 위 4종                                                  |
| `buffered_count`        | Integer | 현재 버퍼에 쌓인 문장 수 (0~2)                          |
| `batch_start_sequence`  | Integer | 이번 배치의 시작 문장 순번 (`BUFFERING`이면 `null`)     |
| `batch_end_sequence`    | Integer | 이번 배치의 끝 문장 순번                                |
| `claims`                | Array   | 검증된 주장 목록 (9.3 참조)                             |
| `excluded_count`        | Integer | 검증 불가로 걸러진 주장 수 (수사적 표현 등)             |
| `extraction_llm_used`   | Boolean | 주장 추출 LLM 실행 여부                                 |
| `verification_llm_used` | Boolean | 근거 검증 LLM 실행 여부. `false`면 근거 부족으로 생략됨 |
| `warnings`              | Array   | `sequence_gap`, `claim_retrieval_failed` 등 진단 코드   |
| `generated_at`          | String  | 응답 생성 시각 (ISO-8601 UTC)                           |

### 9.3. `claims[]` 항목

| 필드명           | 타입    | 설명                                                                    |
| :--------------- | :------ | :---------------------------------------------------------------------- |
| `claim_id`       | String  | `{TICKER}:{시작seq}-{끝seq}:c{n}` 형식                                  |
| `sentence_index` | Integer | 배치 내 문장 위치 (0~2)                                                 |
| `source_text`    | String  | 원문에서 잘라낸 구간                                                    |
| `claim`          | String  | 정규화된 주장                                                           |
| `claim_type`     | String  | `numeric_fact` / `current_fact` / `historical_fact` / `event_fact`      |
| `verdict`        | String  | `SUPPORTED` / `CONTRADICTED` / `INSUFFICIENT_EVIDENCE`                  |
| `confidence`     | Double  | 0.0 ~ 1.0                                                               |
| `explanation_ko` | String  | 한국어 판정 설명. **클라이언트에 그대로 노출**                          |
| `reason_code`    | String  | `supported_by_news` / `contradicted_by_news` / `insufficient_relevance` / `evidence_not_specific` / `retrieval_failed` / `llm_failed` / `invalid_llm_response` |
| `evidence`       | Array   | `doc_id`, `title`, `snippet`, `url`, `source`, `published_at`, `relevance_score` |
| `retrieved_count` | Integer | 검색된 근거 수                                                         |
| `accepted_count` | Integer | 관련성 게이트를 통과한 근거 수                                          |

### 9.4. 통합 시 주의사항

1. **`sentence_timestamp`는 실제 현재 시각을 넣어야 합니다.** 근거 검색이 이 값을 기준으로 과거 N일을 조회하므로, 임의값을 넣으면 적재된 근거가 있어도 검색 결과가 0건이 되어 전부 `INSUFFICIENT_EVIDENCE`로 떨어집니다.
2. **근거는 사전 적재가 필요합니다.** 검증 대상 종목의 뉴스·보도자료를 `POST /api/v1/integration/collector/news`로 미리 넣어야 합니다. 관련성 게이트가 **서로 다른 매체 2곳 이상**을 요구하므로 단일 출처만 넣으면 통과하지 못합니다. 저장소가 인메모리라 AI Engine 재기동 시 초기화됩니다.
3. **재생 루프를 블로킹하지 마세요.** 3문장 배치 처리에 Gemini 호출 2회로 수 초가 걸립니다. 백엔드는 비동기로 던지고 결과가 오는 대로 발행해야 트랜스크립트 표시가 지연되지 않습니다.
4. **타임아웃과 폴백을 두세요.** 시연 중 LLM 지연·실패에 대비해 사전 캐시 응답으로 폴백합니다.

### 9.5. 클라이언트 표기 규칙

판정값은 AI Engine의 3종을 단일 진실 공급원으로 삼고, 화면 표기는 아래로 통일합니다.

| `verdict`               | UI 표기       |
| :---------------------- | :------------ |
| `SUPPORTED`             | 사실 확인     |
| `CONTRADICTED`          | 사실과 다름   |
| `INSUFFICIENT_EVIDENCE` | 근거 부족     |

### 9.6. 종합 판단 (`POST /v1/engine/analyze`)

어닝콜 전문을 통째로 넘겨 LLM 판단을 받습니다. **판단이 실제로 만들어지는 유일한 엔드포인트입니다.**

**요청**

| 필드명        | 타입    | 필수 | 설명                                                              |
| :------------ | :------ | :--: | :---------------------------------------------------------------- |
| `ticker`      | String  |  N   | 종목 심볼                                                         |
| `prompt`      | String  |  Y   | 어닝콜 전문 (모든 세그먼트를 이어붙인 것)                         |
| `needs_review`| Boolean |  N   | 리뷰 모델까지 태울지. 회차당 1회뿐이므로 백엔드는 항상 `true`     |
| `market_data` | Object  |  N   | `symbol`, `current_price`, `prev_close`. 없으면 손절 계획이 생략됨 |

**응답 (화면이 쓰는 필드만)**

- `analysis`: `direction`(BULLISH/BEARISH/NEUTRAL), `magnitude`(0~1), `confidence`(0~1), `catalyst_type`, `rationale`(영문), `risk_flags[]`, `hold_days`, `model_version`, `review_triggered`
- `signal_brief`: `action`, `gate_result`, `decision_state`, `institutional_grade`(A~E), `institutional_grade_score`, `institutional_approval_state`, `position_intent_ko`, `no_trade_summary_ko`, `risk_flags_ko[]`, `counter_thesis_ko`, `recommended_hold_days`

응답에는 이 밖에도 필드가 많습니다. 백엔드 모델은 `@JsonIgnoreProperties(ignoreUnknown = true)`로 선언해 두었으니 엔진이 필드를 늘려도 역직렬화가 깨지지 않습니다.

### 9.7. 회피·파급·손절 (`POST /v1/engine/earnings/intelligence`)

**이 엔드포인트는 LLM을 쓰지 않습니다.** 규칙 기반이라 응답이 즉시 옵니다. 여기서 나오는 `fact_checks`는 9.1의 LLM 검증이 아니라 구형 휴리스틱이므로 **화면에 쓰지 마세요.**

**요청**

| 필드명            | 타입   | 필수 | 설명                                                                    |
| :---------------- | :----- | :--: | :---------------------------------------------------------------------- |
| `ticker`          | String |  Y   | 종목 심볼                                                               |
| `event_text`      | String |  Y   | 어닝콜 전문                                                             |
| `question`        | String |  N   | 애널리스트 질문. 없으면 회피 지표가 의미를 잃습니다                     |
| `answer`          | String |  N   | 그 질문에 대한 경영진 답변                                              |
| `related_tickers` | Array  |  N   | 연쇄 영향을 볼 종목                                                     |
| `market_data`     | Object |  N   | `current_price`만 있어도 손절 계획이 계산됩니다                         |
| `direction_hint`  | String |  N   | 9.6의 `direction`. 손절 계획의 LONG/SHORT를 가릅니다                    |
| `confidence_hint` | Number |  N   | 9.6의 `confidence`                                                      |

**응답 (화면이 쓰는 필드만)**

- `omission_evasion`: `evasion_score`(0~1, 높을수록 회피), `directness`, `omission_score`, `pivot_detected`, `missing_topics[]`, `rationale_ko`
- `impact_chain[]`: `ticker`, `relationship`, `direction`, `impact_score`, `confidence`, `rationale_ko`
- `risk_plan`: `available`, `direction`, `reference_price`, `stop_loss`, `take_profit_1/2`, `stop_pct`, `take_profit_1/2_pct`, `risk_reward_1`, `time_stop_days`, `invalidation_text`, `sizing_note_ko`
- `warnings[]`

> **`related_tickers`를 반드시 실어 보내세요.** AI Engine의 정적 관계 그래프에는 일부 종목(NVDA/AMD/TSMC/MSFT/META/TSLA/AAPL)만 들어 있습니다. 시연 종목이 거기 없으면 `impact_chain`이 빈 배열로 나옵니다. 요청에 실어 보내면 그래프를 고치지 않고도 잡힙니다.
>
> **`risk_plan.available=false`면 나머지 필드는 전부 `null`입니다.** 가격 정보가 없거나 방향성이 서지 않았다는 뜻이므로, 화면에서 0으로 채우지 말고 `invalidation_text`의 사유를 보여줍니다.
>
> **무료 등급 Gemini 키 주의.** 9.6은 리뷰 모델을 태웁니다. 무료 키는 pro 계열 할당량이 0이라 pro를 지정하면 매 호출이 429로 실패하고, 엔진은 `confidence: 0.0`의 폴백 응답을 돌려줍니다. 화면에는 늘 NEUTRAL만 뜹니다. 사용 가능 모델은 `gemini-3.6-flash`, `gemini-3-flash-preview`, `gemini-3.1-flash-lite`입니다.
