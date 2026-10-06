# 📢 EarningWhisperer API & Data Contract Specification

이 문서는 EarningWhisperer 프로젝트의 마이크로서비스 및 하이브리드 아키텍처(SaaS Web + Trading Terminal) 간 데이터 통신 규격을 정의합니다.
모든 팀원은 본 명세에 정의된 필드명, 데이터 타입, 통신 주체를 엄격하게 준수하여 분산 시스템 환경에서 발생할 수 있는 파싱 에러와 상태 불일치를 원천 차단해야 합니다.

---

## 1. 전체 데이터 흐름도 (Data Pipeline)

1. **Data Pipeline** (Python) ➔ `[HTTP POST]` ➔ **AI Engine** (Python)
2. **Backend** (Java) ➔ `[WebSocket /topic/live/demo]` ➔ **Frontend Web** (Next.js) : 데모 재생 시각화
3. **Trading Terminal** ➔ `[HTTP REST]` ➔ **증권사 KIS API** : 사용자가 입력한 수동 주문 실행 (Client-side)
4. **Trading Terminal** ➔ `[HTTP POST]` ➔ **Backend** (Java) : 수동 주문 기록, 체결 결과 보고, 잔고 동기화
5. **Data Pipeline** (Python) ➔ `[HTTP POST]` ➔ **Backend** (Java) : 어닝콜 일정 데이터 동기화 (저빈도 배치)
6. **Data Pipeline** (Python) ➔ `[Redis Pub/Sub]` ➔ **Backend** (Java) : 실시간 주가 데이터 스트리밍
7. **Data Pipeline** (Python) ➔ `[Redis Pub/Sub]` ➔ **Backend** (Java) : 글로벌 시장 지수 1분 스트리밍
8. **Data Pipeline** (Python) ➔ `[HTTP POST]` ➔ **Backend** (Java) : 실시간 어닝콜 트랜스크립트 segment 전달 (AI Engine 분석용 슬라이딩 윈도우와 별개 출력)
9. **Backend** (Java) ➔ `[WebSocket /topic/transcript]` ➔ **Trading Terminal / Frontend Web** : 어닝콜 트랜스크립트 라이브 표시

> 매매 신호로 주문을 내던 경로(AI Engine ➔ Redis `trading-signals` ➔ Backend 룰 엔진 ➔ `/user/queue/signals` ➔ Terminal)는 #127 에서 제거했습니다. EarningWhisperer 는 어닝콜 분석 프로그램이고, 주문은 사용자가 터미널에서 직접 내는 주문만 있습니다.

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
- **현재 상태:** 백엔드는 #127 에서 이 채널의 구독을 제거했습니다. AI Engine 이 발행하더라도 받는 곳이 없습니다. 형식은 기록으로 남겨 둡니다.

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

백엔드는 목적에 따라 여러 웹소켓 채널을 운영합니다. 개인 큐(`/user/queue/...`)로 보내는 채널은 #127 에서 매매 신호 경로를 제거하면서 없어졌습니다.

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
- **현재 상태:** 이 토픽은 Redis `trading-signals` 수신을 계기로 발행됐으므로, #127 에서 구독을 제거한 뒤로는 발행되지 않습니다. 데모 재생(4.1)의 `/topic/live/demo` 는 그대로입니다.
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

### 4.3. Private Routing (제거됨)

`/user/{userId}/queue/signals` 로 매매 명령을 보내던 채널은 #127 에서 제거했습니다. 백엔드는 더 이상 주문을 지시하지 않으며, 터미널은 이 큐를 구독하지 않습니다. 재접속 시 대기 명령을 복원하던 `GET /api/v1/trades/pending` 도 함께 제거했습니다.

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

### 4.8. Transcript Translation Broadcast (어닝콜 자막 한국어 번역)

- **Topic:** `/topic/transcript-translation/{ticker}`
- **인증:** 로그인 필수 (JWT). 4.5와 동일 정책.
- **설명:** 4.5로 나간 자막 세그먼트의 한국어 번역입니다(#110). 백엔드가 세그먼트를 몇 개씩 묶어 AI Engine(Contract 9.10)에 번역을 요청하고, 결과를 이 채널로 발행합니다. 용어 사전(7.9)에 있는 용어는 사전의 번역어로 고정됩니다.
- **발행 시점:** 세그먼트 3개가 모이거나, 묶음의 첫 세그먼트가 들어온 지 10초가 지나거나, 글자 수 상한(1,200자)에 닿거나, 세션 종료 세그먼트(`is_session_end=true`)가 들어왔을 때 묶음을 보냅니다. 번역은 AI Engine 응답(LLM) 시간만큼 더 늦게 도착합니다. 값은 `transcript-translation.*` 설정으로 바꿀 수 있습니다.
- **발행되지 않는 경우:** 번역이 꺼져 있을 때(`ai-engine.translation-enabled=false`), AI Engine 호출 실패, 번역 실패(`available=false`), 대기열에서 30초(`transcript-translation.max-age-ms`) 넘게 밀린 묶음. 원문을 번역 대신 보내지 않습니다. 사유는 백엔드 로그에 남습니다.
- **트랜스크립트 채널과의 관계:** 4.5 원문은 번역을 기다리지 않고 먼저 나갑니다. 클라이언트는 `sequences` 로 어느 세그먼트들의 번역인지 짝짓습니다. 묶음 단위로 한 문단이 오므로 세그먼트별로 나뉘어 있지 않습니다.

| 필드명       | 타입          | 필수 | 설명                                                                 |
| :----------- | :------------ | :--: | :------------------------------------------------------------------- |
| `ticker`     | String        |  Y   | 종목 심볼                                                            |
| `call_id`    | String        |  Y   | 어닝콜 세션 식별자 (4.5와 동일 값)                                   |
| `sequences`  | Array<Integer> |  Y   | 이 번역이 담은 4.5 세그먼트의 `sequence`. 오름차순, 1개 이상         |
| `text_ko`    | String        |  Y   | 한국어 번역문                                                        |
| `terms_used` | Array<String> |  Y   | 사전 번역어가 번역문에 실제로 들어간 용어 (원문 표기). 없으면 빈 배열 |

> **구독 예시:** `stompClient.subscribe('/topic/transcript-translation/WMT', handler)`

---

## 5. [Contract 4] Trading Terminal ➔ Backend (Callback & Sync)

Trading Terminal이 사용자의 수동 주문 결과와 실제 계좌 상태를 백엔드에 기록하기 위해 호출하는 REST API입니다.

### 5.1. 매매 체결 결과 보고 (Callback)

- **엔드포인트:** `POST /api/v1/trades/{tradeId}/callback`
- **설명:** `PENDING` 으로 기록된 수동 주문(7.3 `POST /api/v1/trades/manual`)이 나중에 체결되거나 실패했을 때, 그 결과를 보고해 DB 상태를 `EXECUTED` 또는 `FAILED`로 확정합니다. 본 콜백 수신 시 `Trade.orderQty`는 `executed_qty`로 덮어써집니다. `EXPIRED` 상태에서 `EXECUTED` 를 받으면 정정 전이로 처리합니다.

  {
  "status": "EXECUTED",
  "broker_order_id": "ODNO_123456789",
  "executed_price": 125.50,
  "executed_qty": 10,
  "error_message": null
  }

### 5.2. 실제 계좌 장부 동기화 (Sync)

- **엔드포인트:** `POST /api/v1/portfolio/sync`
- **설명:** Trading Terminal이 기동되거나 매매가 완료된 직후, 실제 KIS 계좌 잔고를 백엔드에 덮어씌웁니다.

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

`PUT /api/v1/users/settings` 와 `GET`·`PUT /api/v1/portfolio/settings`(매매 모드와 룰 엔진 설정)는 #127 에서 제거했습니다.

### 7.3. 거래 내역 (Trades)

| Method | Endpoint                            |        인증         | 설명                                      |
| :----- | :---------------------------------- | :-----------------: | :---------------------------------------- |
| GET    | `/api/v1/trades?page=0&size=20`     |        필요         | 내 거래 내역 페이징 조회. 응답: Page 형태 |
| POST   | `/api/v1/trades/manual`             |        필요         | 수동 주문 기록 (아래 참조). 201 `{tradeId}` |
| POST   | `/api/v1/trades/{tradeId}/callback` | 필요 (Terminal JWT) | 체결 결과 콜백 (Contract 4.1 참조)        |

**`GET /api/v1/trades` 응답 항목** (`TradeResponse`)

| 필드 | 타입 | 설명 |
| :--- | :--- | :--- |
| `id` | Long | 거래 ID |
| `ticker` | String | 종목 |
| `side` | Enum | `BUY` \| `SELL` |
| `orderType` | Enum | `MARKET` \| `LIMIT` |
| `orderQty` | Integer | 주문 수량 |
| `price` | Double | 주문 지정가. 미체결 주문에도 존재 |
| `executedQty` | Integer | 체결 수량. 미체결이면 0 |
| `executedPrice` | Double | 체결 평균가. 미체결이면 `null` |
| `status` | Enum | `PENDING` \| `EXECUTED` \| `FAILED` \| `EXPIRED` |
| `brokerOrderId` | String | 증권사 주문번호 (KIS ODNO). 미체결 주문도 보존 |
| `createdAt` | DateTime | 주문 생성 시각 |

#### `POST /api/v1/trades/manual`

- **설명:** 사용자가 터미널 UI 에서 직접 낸 주문의 결과를 기록합니다. 백엔드가 주문을 지시하지 않으므로 요청에 `trade_id` 가 없고, 터미널이 KIS 주문 후 결과를 그대로 보고합니다. `side` 는 `BUY` / `SELL` 만 받습니다. 활성 `BrokerAccount` 가 없으면 **422** 입니다.
- **응답 201 `{"tradeId": 123}`** — `status: PENDING` 으로 기록된 미체결 주문을 나중에 `POST /api/v1/trades/{tradeId}/callback` 으로 종결시키기 위해 필요하다. 터미널에 아직 체결 폴링이 없어 현재는 이 경로를 쓰지 않지만, id 를 돌려주지 않으면 종결 자체가 구조적으로 불가능하다.
- **PENDING 수동 주문은 `app.trade.manual-pending-ttl-seconds`(기본 24시간)가 지나면 `EXPIRED` 로 바뀝니다.** 증권사에 실제로 접수돼 체결을 기다리는 주문이라 짧게 만료시키면 살아 있는 주문이 "실패" 로 뜹니다. 반대로 만료 대상에서 아예 빼면 영구 PENDING 고아가 되므로, KIS 당일 주문이 장 마감에 취소되는 것에 맞춰 하루를 줍니다. 사후에 체결이 확인되면 EXPIRED → EXECUTED 정정 전이로 회복합니다. 매매 신호 명령용이던 `app.trade.pending-ttl-seconds` 는 #127 에서 제거했습니다.
- **`status` 는 `EXECUTED` / `PENDING` / `FAILED` 세 값을 받는다.** `PENDING` 은 KIS 가 주문을 접수했으나(ODNO 반환) 아직 체결되지 않은 상태다 — 살아 있는 주문을 `FAILED` 로 적으면 안 된다.
- **`order_type` 은 항상 `LIMIT` 이다.** KIS 해외주식 매수에는 시장가 코드가 없어(`ORD_DVSN` 매수는 `00` 지정가 / `32` LOO / `34` LOC, 모의투자는 `00` 만) UI 의 "즉시 체결" 도 현재가 ±1% 지정가로 환산해 나간다. `price` 는 브로커에 실제로 보낸 지정가다. 단, 가격 확정 전에 실패한 경우(현재가 조회 불가)는 주문이 나가지 않았으므로 `MARKET` / `price: 0` 으로 기록된다.

```json
{
  "ticker": "WMT",
  "side": "BUY",
  "order_type": "LIMIT",
  "order_qty": 1,
  "price": 107.47,
  "executed_qty": 0,
  "executed_price": null,
  "broker_order_id": "0000044600",
  "status": "PENDING",
  "error_message": null
}
```

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
| GET    | `/api/v1/demo/earnings-call/speakers` | 필요 | 콜 참가자 명부 조회              |

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

- **`evidence_warning`이 실려 오면 근거가 없다는 뜻입니다.** 근거 뉴스가 최소 기준(20건) 미만이면 start 응답에 이 필드가 붙습니다. 재생은 그대로 진행되지만 팩트체크는 대부분 `INSUFFICIENT_EVIDENCE`로 나옵니다. **클라이언트는 이 값을 반드시 사용자에게 보여줘야 합니다** — 없으면 시연 중에 "근거 없는 주장"과 "근거를 안 넣은 것"이 화면에서 구별되지 않습니다.

      { "ticker": "WMT", "call_id": "...", "segment_count": 24, "interval_ms": 6000,
        "evidence_warning": "근거 뉴스가 0건뿐입니다. 팩트체크가 대부분 '근거 부족'으로 나옵니다. 시연 전 뉴스를 적재하세요." }

- **`call_id`는 재생 회차마다 새로 생성됩니다.** 같은 값을 재사용하면 `TranscriptSessionRegistry`가 종료된 세션으로 판단해 모든 세그먼트를 거부합니다(조용한 실패).
- **status는 끝난 재생의 결과도 알려줍니다.** 재생 중이 아니면 `running:false`와 함께 `last_run`을 반환합니다. `outcome`은 `COMPLETED` / `STOPPED` / `NO_SEGMENT_PUBLISHED` 중 하나입니다. 세 번째는 스크립트 결함 등으로 세그먼트를 하나도 내보내지 못하고 끝난 경우로, 이것이 없으면 "정상 완료"·"시작한 적 없음"과 구별되지 않습니다.

      { "running": false, "ticker": "ORCL",
        "last_run": { "call_id": "...", "outcome": "COMPLETED", "published_count": 6, "total_segments": 6 } }

- **스크립트 교체 시 규칙.** 시작 시점에 검증하며, 위반하면 500(`SCRIPT_UNAVAILABLE`)으로 거부합니다.
  1. `sequence`는 **0부터 1씩 증가**해야 합니다. 0에서 시작하지 않으면 AI Engine의 ticker 버퍼가 초기화되지 않습니다 — AI Engine은 `call_id`가 아니라 `ticker`로 버퍼를 잡고 `sentence_sequence=0`에서만 리셋하므로, 중지 후 재시작 시 트랜스크립트는 정상인데 팩트체크만 전부 조용히 사라집니다.
  2. `text`는 비어 있을 수 없습니다.
  3. 세그먼트 수는 **3의 배수**를 권장합니다. AI Engine이 3문장 단위로 검증하므로 나머지 1~2문장은 `DISCARDED`되어 마지막 발언들의 팩트체크가 나오지 않습니다. 위반해도 시작은 되지만 기동 로그에 경고가 남습니다.
  4. **과거 어닝콜을 재생한다면 `call_started_at`(ISO-8601)을 반드시 채우세요.** 비워 두면 세그먼트 타임스탬프를 재생 시점의 현재 시각으로 찍는데, AI Engine은 그 값을 기준으로 "과거 30일"을 근거 검색 창으로 잡습니다. 작년 콜에 작년 뉴스를 넣어 두면 창 밖으로 밀려 **전부 근거 부족**이 됩니다. 값을 채우면 타임스탬프가 `call_started_at + start_ms`로 계산되어 검색 창이 그 콜 시점에 맞춰집니다. 형식이 틀리면 재생은 되지만 현재 시각으로 되돌아가며 경고 로그가 남습니다.
  5. `related_tickers`와 `analyst_qa`는 종합 판단(§4.7)에 쓰입니다. 전자가 없으면 파급효과가 비고, 후자가 없으면 회피 지표가 생략됩니다. `analyst_qa`는 Q&A 세션에서 실제로 오간 질문·답변 한 쌍이어야 합니다 — `PLACEHOLDER`로 시작하는 문자열은 백엔드가 걸러 냅니다.
  6. `speakers`에는 **트랜스크립트에서 확인되는 사실만** 적습니다 — 이름·직책·소속·애널리스트 여부. 화법 성향이나 과거 가이던스 달성률처럼 원문에서 확인할 수 없는 값은 넣지 않습니다. 터미널은 이 명부에 이번 회차에 실제로 수신한 발언량과 팩트체크 판정을 붙여 보여줍니다. 비어 있으면 터미널의 발화자 프로필 진입점이 나타나지 않습니다. `speakers[].match_key`는 세그먼트의 `speaker` 문자열과 **정확히 같아야** 합니다 — 세그먼트 라벨은 표시용이라 "CEO · John Furner"처럼 직책이 붙는 반면 이름은 "John Furner"라서, 이 키가 없으면 클라이언트가 부분 문자열 매칭을 추측하게 되고 그 추측은 동명이인·중간 이니셜에서 조용히 틀립니다. 비워 두면 `name`을 키로 씁니다. 세그먼트에 발언이 없는 참가자(발췌에 안 들어간 애널리스트 등)는 발언 0건으로 표시됩니다.
- **`speakers` 응답.** 재생 중이 아니어도 조회됩니다. 명부가 없으면 빈 배열이고, **스크립트 파일을 읽지 못하면 500**입니다 — 둘을 같은 응답으로 내려보내면 "명부를 안 넣었다"와 "파일이 깨졌다"가 구별되지 않습니다.

      [ { "name": "John Furner", "match_key": "CEO · John Furner", "title": "CEO", "affiliation": "Walmart Inc.", "analyst": false },
        { "name": "Kate McShane", "match_key": "Kate McShane", "title": "Analyst", "affiliation": "Goldman Sachs", "analyst": true } ]

- **관련 설정:** `demo.earnings-call.script-path`, `demo.earnings-call.interval-ms`, `ai-engine.base-url`, `ai-engine.fact-check-enabled`, `ai-engine.timeout-ms`. `fact-check-enabled=false`로 두면 AI Engine 없이 트랜스크립트 재생만 수행합니다.

### 7.9. 어닝콜 용어 사전 (Glossary)

| Method | Endpoint           | 인증 | 설명                 |
| :----- | :----------------- | :--: | :------------------- |
| GET    | `/api/v1/glossary` | 필요 | 어닝콜 용어 사전 전체 |

- **설명:** 어닝콜 영어의 금융 용어와 그 한국어 표기를 담은 사전입니다. 한 사전을 두 기능이 함께 씁니다. 실시간 번역(#110)은 세그먼트에서 찾은 용어의 `ko`로 번역어를 고정하고, 용어 하이라이팅(#111)은 `definition_ko`·`why_ko`를 정의 팝오버에 보여줍니다.
- **사전은 백엔드 리소스(`data/glossary_ko.json`)입니다.** 기동 시 한 번 읽어 끝까지 같은 값을 내려주므로, 클라이언트는 로그인 직후 한 번만 조회하면 됩니다(JWT 필요). AI Engine 가동 여부와 무관하게 응답합니다.
- **`ko`는 번역문에 그대로 들어가는 표기입니다.** 설명을 괄호로 붙이면(예: "가이던스(실적 전망치)") 번역문에도 매번 괄호째 들어갑니다. 설명은 `definition_ko`에 둡니다. 약어 병기("주당순이익(EPS)")처럼 번역문에 함께 보여야 하는 것만 괄호를 씁니다.
- **`definition_ko`·`why_ko`는 선택 필드이며, 값이 없으면 응답에서 생략됩니다.** 정의가 없는 용어는 번역 고정에만 쓰이고 하이라이팅 대상이 아닙니다. 현재 사전(version 2)은 57개 용어 중 55개에 정의가 있습니다. `eCommerce`·`market share`처럼 설명이 필요 없는 용어는 정의를 비워 번역 고정에만 씁니다. 정의는 초보 투자자 기준으로 일반적인 뜻과 왜 중요한지까지만 적고, 특정 콜의 수치에 대한 판단은 넣지 않습니다.

      { "version": 1,
        "terms": [
          { "term": "comp sales", "aliases": ["comparable sales", "comps"], "ko": "기존점 매출", "category": "retail",
            "definition_ko": "1년 이상 운영된 점포만 집계한 매출 증가율입니다.", "why_ko": "신규 출점 효과를 뺀 실제 영업력을 보여줍니다." },
          { "term": "guidance", "aliases": [], "ko": "가이던스", "category": "guidance" } ] }

- **사전 교체 시 규칙.** 기동 시점에 검증하며, 위반하면 **애플리케이션이 기동되지 않습니다.** 빈 사전이나 잘못된 사전으로 기동하면 번역이 용어 고정 없이 도는데, 화면만으로는 원인을 알 수 없기 때문입니다.
  1. `version`은 1 이상, `terms`는 1개 이상이어야 합니다.
  2. `term`·`ko`는 비어 있을 수 없습니다.
  3. `term`과 `aliases` 전체에서 같은 표기가 두 번 나올 수 없습니다(대소문자·앞뒤 공백 무시). 한 표기가 두 용어에 걸리면 어느 번역어로 고정할지 정해지지 않습니다.
  4. 정의된 필드 외의 키는 거부합니다. `definiton_ko` 같은 키 오타가 조용히 버려지는 것을 막기 위해서입니다.
- **관련 설정:** `glossary.path` (기본 `data/glossary_ko.json`).

### 7.10. 어닝콜 질의응답 (Assistant)

| Method | Endpoint                | 인증 | 설명 |
| :----- | :---------------------- | :--: | :--- |
| POST   | `/api/v1/assistant/ask` | 필요 | 어닝콜 질문을 보내고 답을 SSE 로 받습니다 |

```json
{ "ticker": "WMT", "call_id": "demo-wmt-q2fy27-1787227200000-1", "as_of_sequence": 17,
  "anchor_sequence": 3, "question": "가이던스가 바뀌었어?", "suggested_question_id": null,
  "history": [ { "role": "user", "text": "..." }, { "role": "assistant", "text": "..." } ] }
```

- **요청.** `as_of_sequence` 는 터미널이 마지막으로 받은 세그먼트 번호입니다. backend 는 이를 저장된 마지막 세그먼트 이하로 낮추고, 그 세그먼트의 발행 시각을 근거 시점으로 씁니다. `anchor_sequence` 는 사용자가 고른 대목이며 없으면 `null` 입니다. `suggested_question_id` 가 있으면 대목 지정은 무시하고 콜 전체 범위로 답합니다. `question` 은 500자, `history` 는 6개(후속 질문 3회)까지이고 대화 기록은 터미널이 보관합니다.
- **Accept.** 성공은 `text/event-stream`, 실패는 JSON 이므로 `Accept: text/event-stream, application/json` 으로 보냅니다.
- **성공(200).** 이벤트는 10.6 과 같습니다(`meta` → `delta` → `citations` → `done`, 실패 시 `error`). backend 가 덧붙이는 `error` 의 `code` 는 `assistant_unavailable`(질의응답 서비스 연결 실패), `assistant_stream_interrupted`(완료 이벤트 없이 끊김), `timeout`(60초 초과)입니다.
- **실패.** 본문은 `{"error": "<메시지>", "code": "<code>"}` 입니다.

| 상태 | code | 의미 |
|---|---|---|
| 400 | (검증 오류) / `ticker_mismatch` | 형식·길이 위반, 또는 콜과 종목 불일치 |
| 401 | | JWT 없음·만료 |
| 404 | `segments_not_found` | 이 콜의 저장된 자막이 없음 |
| 409 | `assistant_busy` | 같은 사용자의 이전 질문 답변이 진행 중 |
| 429 | `daily_limit_exceeded` | 하루 질문 수(기본 50, 한국 시간 자정 초기화) 초과. `reset_at` 에 다음 초기화 시각(UTC ISO-8601) |
| 503 | `assistant_overloaded` / `assistant_unavailable` | 중계가 가득 참 / 자막·한도 저장소(Redis) 장애 |

- 하루 횟수는 질문을 시작할 때 차감하며, 답이 실패해도 돌려주지 않습니다. 404·400·409 는 횟수를 쓰지 않습니다.
- 사용자가 연결을 끊으면 backend 는 질의응답 서비스 연결을 닫고, 질의응답 서비스는 진행 중인 생성을 멈춥니다.
- **관련 설정:** `app.assistant.base-url`, `app.assistant.daily-limit`, `app.assistant.stream-timeout-seconds`.

---

## 8. 공통 개발 가이드라인 (Common Rules)

1. **인증 방식:** JWT Bearer 토큰. 로그인 응답의 `accessToken`을 모든 인증 필요 요청의 `Authorization: Bearer {token}` 헤더에 포함. WebSocket STOMP 연결 시 CONNECT 프레임의 `Authorization` 헤더로 전달.
2. **플랜 접근 제어:** 유저 role은 `FREE` / `PRO` 두 가지. `action` (BUY/SELL 신호) 및 Trading Terminal 사용은 PRO 전용. FREE 유저는 `raw_score` 시각화까지만 접근 가능.
3. **내부 API 인증:** Data Pipeline → 백엔드 내부 전용 엔드포인트(`/api/v1/internal/*`)는 `X-Internal-Secret` 헤더로 공유 시크릿 검증.
4. **에러 처리:** REST API 통신 시 에러가 발생하면 무조건 HTTP Status `4xx` 또는 `500`과 함께 `{"error": "에러 상세 원인"}` 형태의 JSON을 반환해야 합니다.

   - **401 과 403 을 구분합니다.** 인증이 없거나 토큰이 만료·위조된 경우는 **401** 입니다. 권한 부족(**403**)은 핸들러만 마련해 둔 상태입니다 — 현재 모든 엔드포인트 규칙이 `permitAll` 아니면 `authenticated()` 라서 실제로 403 이 나가는 경로는 없습니다. §8.2 의 FREE/PRO 접근 제어를 구현하면 그때 쓰입니다. 클라이언트(터미널·웹 프론트)는 **401 에서만** refresh 토큰으로 갱신하고 원 요청을 재시도합니다. 전에는 Spring Security 기본값(`Http403ForbiddenEntryPoint`) 때문에 만료된 토큰에도 403 이 나갔고, 그래서 양쪽 클라이언트의 갱신 로직이 한 번도 실행되지 않았습니다 — 액세스 토큰 수명(15분)마다 로그인 화면으로 튕겼습니다. `SecurityConfig.exceptionHandling` 이 이 규약을 지킵니다.
   - 만료와 위조를 응답에서 구분해 알려주지 않습니다. 둘 다 `{"error": "인증이 필요합니다."}` 입니다.
5. **타임존:** 모든 `timestamp`는 **UTC** 기준의 Unix Epoch Second를 사용합니다. 프론트엔드 및 터미널 수신 후 로컬 브라우저/OS 시간으로 변환하여 표출합니다.
6. **무상태성 및 단일 진실 공급원:** 백엔드는 KIS API 키를 가지지 않으며, 모든 '최종' 자산 상태는 Trading Terminal이 쏘아주는 Sync 데이터를 '단일 진실 공급원(Single Source of Truth)'으로 취급하여 덮어씁니다.
7. **주문 주체:** 모든 주문은 사용자가 Trading Terminal 에서 직접 입력한 수동 주문입니다. 백엔드의 룰 엔진과 터미널의 매매 모드 선택은 #127 에서 제거했습니다.

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

> **`impact_score` 는 null 일 수 있습니다.** 이 값은 그 종목이 이번 콜의 근거 문서에 함께 등장하는 비율입니다 (같이 언급된 문서 수 ÷ 전체 근거 문서 수). 근거 문서가 하나도 없으면 셀 것이 없으므로 `0.0` 이 아니라 `null` 로 내려갑니다 — `0.0`("영향 없음")과 "측정 못 함"을 같은 값으로 내려보내면 근거 적재를 빠뜨린 것을 화면에서 알아챌 수 없기 때문입니다. `confidence` 는 근거 문서 수를 20건 기준으로 환산한 값입니다.
>
> **`risk_plan.available=false`면 나머지 필드는 전부 `null`입니다.** 가격 정보가 없거나 방향성이 서지 않았다는 뜻이므로, 화면에서 0으로 채우지 말고 `invalidation_text`의 사유를 보여줍니다.
>
> **무료 등급 Gemini 키 주의.** 9.6은 리뷰 모델을 태웁니다. 무료 키는 pro 계열 할당량이 0이라 pro를 지정하면 매 호출이 429로 실패하고, 엔진은 `confidence: 0.0`의 폴백 응답을 돌려줍니다. 화면에는 늘 NEUTRAL만 뜹니다. 사용 가능 모델은 `gemini-3.6-flash`, `gemini-3-flash-preview`, `gemini-3.1-flash-lite`입니다.

### 9.8. 근거 준비 확인 (`GET /v1/engine/evidence/readiness`)

근거 저장소에 해당 종목 문서가 몇 건 있는지 센다. **임베딩 호출 없이 개수만 세므로 빠르고**, 재생 시작 버튼 경로에서 동기로 불러도 된다.

| 쿼리 파라미터   | 필수 | 설명                                                                     |
| :-------------- | :--: | :----------------------------------------------------------------------- |
| `ticker`        |  Y   | 종목 심볼                                                                |
| `as_of`         |  N   | 기준 시각(epoch seconds). **과거 콜 재생 시 그 콜의 시각.** 없으면 현재  |
| `lookback_days` |  N   | 검색 창 길이. 없으면 `FACT_CHECK_NEWS_LOOKBACK_DAYS`                     |

응답: `ticker`, `document_count`, `lookback_days`, `as_of_epoch`, `ready`, `minimum_expected`

    { "ticker": "WMT", "document_count": 391, "lookback_days": 30,
      "as_of_epoch": 1787230800, "ready": true, "minimum_expected": 20 }

> **왜 필요한가.** 근거를 하나도 넣지 않은 채로 어닝콜을 재생하면 화면에는 "근거 부족" 판정만 줄줄이 뜬다. 그 화면은 **정말 근거 없는 주장을 검증한 결과**와 **근거 적재를 잊은 것**이 완전히 똑같이 보인다. 시연 도중에는 알아차릴 방법이 없다. 백엔드는 재생 시작 전에 이 값을 확인해 §7.8의 `evidence_warning`으로 내려보낸다.
>
> **`as_of`를 빠뜨리지 마세요.** 과거 콜을 재생하면서 기준 시각을 현재로 두면, 그 콜 시점의 뉴스가 검색 창 밖이라 `document_count`가 0으로 나온다. 실제로는 적재돼 있는데도 그렇다.

### 9.9. 임베딩 설정 주의

근거 검색 품질은 `EMBEDDING_PROVIDER`에 달려 있다. **기본값 `hash`는 SHA256 단어 겹침이라 의미 검색이 아니다.** 이 상태로는 뉴스를 아무리 넣어도 관련도가 임계값을 넘지 못해 대부분 `INSUFFICIENT_EVIDENCE`가 된다.

OpenAI 키가 없으면 `gemini`를 쓴다. 무료 등급 Gemini 키로 `gemini-embedding-001`이 동작하는 것을 실측했다(3072차원, `outputDimensionality`로 768 축소, 배치 상한 20건 — 100건은 429).

**관련도 임계값은 임베딩 모델에 종속된다.** Gemini 임베딩은 기준선 유사도가 높아서 무관한 문서도 0.48 수준이 나온다. 해시 임베딩 기준으로 잡힌 0.42/0.34를 그대로 쓰면 아무 기사나 근거로 통과한다. 모델을 바꾸면 `FACT_CHECK_STRONG_RELEVANCE_SCORE` / `FACT_CHECK_MODERATE_RELEVANCE_SCORE`를 실제 코퍼스로 재보정해야 한다.

### 9.10. 세그먼트 한국어 번역 (`POST /v1/engine/transcript/translate`)

어닝콜 세그먼트 1개를 한국어로 번역한다(#110). 용어 사전은 백엔드(§7.9)에 있고, 엔진은 **요청에 실려 온 용어만** 번역어로 고정한다. 백엔드는 세그먼트 원문에서 찾은 용어만 `terms`에 담는다 — 사전 전체를 보내지 않으므로 사전이 커져도 프롬프트 크기와 지연이 늘지 않는다.

| 필드       | 필수 | 설명                                                        |
| :--------- | :--: | :---------------------------------------------------------- |
| `ticker`   |  Y   | 종목 심볼                                                   |
| `call_id`  |  N   | 어닝콜 세션 식별자 (로그용)                                 |
| `sequence` |  Y   | 세그먼트 시퀀스. 응답에 그대로 돌려준다                     |
| `text`     |  Y   | 세그먼트 원문 (앞뒤 공백 제거 후 1~4000자)                  |
| `terms`    |  N   | 고정할 용어 `[{ "term", "ko" }]`, 최대 50개. 비면 일반 번역 |

    POST /v1/engine/transcript/translate
    { "ticker": "WMT", "call_id": "demo-wmt-q2fy27-1", "sequence": 3,
      "text": "Comp sales for Walmart U.S. were 2.6%, led by transactions.",
      "terms": [ { "term": "comp sales", "ko": "기존점 매출" }, { "term": "transactions", "ko": "거래 건수" } ] }

    200 OK
    { "available": true, "sequence": 3,
      "text_ko": "Walmart U.S.의 기존점 매출은 거래 건수 증가에 힘입어 2.6%를 기록했습니다.",
      "terms_used": ["comp sales", "transactions"], "warnings": [] }

- **번역 실패도 HTTP 200이다.** 실패는 `available=false`와 `warnings`로 알린다. 요청 형식이 틀리면(빈 `text`, 공백뿐인 `term`·`ko` 등) 422다. **실패 시 `text_ko`는 null이며, 원문을 대신 넣지 않는다.** 호출자는 `available`을 분기해야 한다.

| `warnings` 값                   | `available` | 의미                                                                           |
| :------------------------------ | :---------: | :----------------------------------------------------------------------------- |
| `translation_llm_timeout`       |    false    | 6초 안에 끝나지 않음                                                           |
| `translation_llm_failed`        |    false    | LLM 호출 실패. 429 할당량 초과 · 503 과부하 · API 키 누락이 모두 여기로 온다   |
| `translation_invalid_response`  |    false    | 응답에 `text_ko`가 없거나 형식이 틀림                                          |
| `translation_not_korean`        |    false    | 번역문 글자 중 한글 비율이 30% 미만 — 원문을 그대로 또는 일부만 옮긴 경우      |
| `translation_internal_error`    |    false    | 엔진 내부 오류. 엔진 로그에 스택이 남는다                                      |
| `translation_terms_not_applied` |    true     | 번역은 되었지만 `terms` 중 일부의 번역어가 번역문에 없음. 번역문은 그대로 쓴다 |

- **`terms_used`는 코드가 판정한다.** `terms` 중 `ko`가 번역문에 실제로 들어간 용어만 담는다. LLM의 자기 보고를 쓰지 않는다. 긴 번역어부터 찾으므로 "기존점 매출"만 쓰인 번역문에서 "매출"이 함께 잡히지 않는다.
- **실패한 세그먼트는 재시도하면 다시 호출된다.** 엔진의 Gemini 응답 캐시는 호출 실패 시의 폴백 응답도 저장하는데, 번역 경로는 그 항목을 지운다. 성공한 번역은 캐시에 남아 같은 세그먼트를 다시 재생하면 할당량을 쓰지 않는다.
- **타임아웃 뒤에도 Gemini 호출은 끝까지 진행된다.** 응답을 기다리지 않을 뿐 호출 자체는 취소되지 않으므로 할당량을 쓴다.
- **백엔드 호출 방식.** 백엔드는 세그먼트를 묶어(4.8 발행 시점 참고) 원문을 공백으로 이어 붙여 `text`로 보내고, 묶음의 첫 `sequence`를 `sequence`로 쓴다. `terms`의 `term`은 원문에 나온 표기 그대로이며, 겹치는 용어는 긴 표기만 담는다.
- **할당량 주의.** 무료 등급 Gemini는 모델별로 **분당 15요청**이다(`gemini-3.1-flash-lite` 실측, 429 `GenerateRequestsPerMinutePerProjectPerModel-FreeTier`). 번역은 팩트체크(§9.1)와 같은 모델을 쓰므로 할당량을 함께 쓴다. 세그먼트마다 번역을 부르면 시연(6초 간격 24세그먼트) 기준 분당 약 10회가 더해져, 팩트체크와 합쳐 한도를 넘는다.

## 10. [Contract 10] 질의응답 근거 조회 (logothea-assistant ➔ Backend · AI Engine)

어닝콜 질의응답 서비스(logothea-assistant, #112)가 답변 근거를 읽는 내부 계약입니다. ai-engine 은 `127.0.0.1` 에만
바인딩되어 같은 호스트에서만 닿습니다. backend 의 `/api/v1/internal/assistant/**` 는 Cloudflare Tunnel 이
`api.logothea.com` 전체를 backend 로 넘기므로 공개 호스트에서도 닿는 경로이고, 보호는 `X-Internal-Secret` 헤더로
합니다. 근거 시점(`as_of`)은 backend 가 확정해 넘기며, 아래 API 는
그 시점 이후의 정보를 돌려주지 않습니다. 10.6 은 반대 방향으로 backend 가 logothea-assistant 에 질문을 넘기는 계약입니다.

### 10.1. 콜 세그먼트 (`GET /api/v1/internal/assistant/calls/{callId}/segments?until_sequence=`)

- 인증: `X-Internal-Secret` (6.4 와 같음)
- backend 는 `/api/v1/internal/transcript-segment` 로 받은 세그먼트 중 레지스트리 검증을 통과해 발행한 것만 콜 단위로
  Redis 에 보관합니다(`app.assistant.segment-ttl-hours`, 기본 48시간). 보관은 비동기(단일 스레드, 대기열 1000건)로 처리하므로
  보관 실패는 자막 발행에 영향을 주지 않으며, Redis 장애 중에는 일부 세그먼트가 빠질 수 있습니다.

```json
{
  "call_id": "demo-wmt-q2fy27-1787227200000-1",
  "until_sequence": 17,
  "last_sequence": 17,
  "segments": [
    { "sequence": 3, "start_ms": 18000, "end_ms": 23000, "speaker": "John Furner", "text": "Comp sales for Walmart U.S. were 2.6%...", "timestamp": 1787227218 }
  ]
}
```

- `until_sequence` 는 필수이고 음수면 `400 {"error": "..."}` 입니다. 그 값 이하만 돌려줍니다. 저장된 마지막이 더 작으면 그만큼만 돌려주고 `last_sequence` 로 알려 줍니다.
- 저장된 세그먼트가 없으면 `404 {"error": "..."}` 입니다.

### 10.2. 실적 추정치 (`GET /api/v1/internal/assistant/stocks/{ticker}/estimates?as_of_epoch=`)

```json
{
  "ticker": "WMT",
  "as_of_epoch": 1787227200,
  "upcoming": { "scheduled_at": "2026-08-20T11:00:00Z", "eps_estimate": 0.74, "revenue_estimate": 176000000000.00 },
  "recent_results": [
    { "announced_at": "2026-05-15T11:00:00Z", "fiscal_period_label": "Q1 FY27", "eps_estimate": 0.60, "eps_actual": 0.61, "surprise_percent": 1.67, "price_reaction_percent": -2.1 }
  ]
}
```

- `recent_results` 는 `as_of` 하루 뒤까지 발표된 결과 중 최근 최대 4건입니다(실적 발표문은 콜 당일 콜보다 먼저 나옵니다).
- `price_reaction_percent` 는 발표 후 7일 종가까지 반영한 값이라, `announced_at` + 7일이 `as_of` 보다 뒤인 결과는 `null` 입니다.
- `upcoming` 은 `as_of` 하루 전 이후의 가장 이른 일정이며, 없으면 `null` 입니다. 모르는 종목은 `404` 입니다.

### 10.3. 용어 사전 (`GET /api/v1/internal/assistant/glossary`)

7.9 `GET /api/v1/glossary` 와 같은 본문을 내부 인증으로 제공합니다.

### 10.4. 시점 조건 뉴스 검색 (`POST /v1/engine/assistant/news-search`)

```json
// 요청
{ "ticker": "WMT", "query": "comp sales guidance", "as_of_epoch": 1787227200, "lookback_days": 30, "top_k": 6 }
// 응답
{ "ticker": "WMT", "as_of_epoch": 1787227200,
  "hits": [ { "doc_id": "...", "title": "...", "source": "Reuters", "url": "...", "published_at": 1787223600, "snippet": "...(최대 600자)", "score": 0.81 } ],
  "warnings": [] }
```

- `published_at <= as_of_epoch` 이고 `as_of_epoch - lookback_days` 이후인 기사만 돌려줍니다. 기존
  `/v1/engine/evidence/search` 는 시점 상한이 없어 질의응답에 쓰지 않습니다.
- 검색에 실패하면(임베딩 한도 등) `200` 에 `hits: []`, `warnings: ["news_search_failed"]` 입니다.
- 요청 검증에 실패하면(`top_k`·`lookback_days` 범위, 빈 `query`, 0 이하 `as_of_epoch` 등) `422` 입니다.

### 10.5. 직전 콜 원문 문장 (`GET /v1/engine/assistant/prior-call-statements?ticker=&before_epoch=`)

```json
{ "available": true, "ticker": "WMT", "document_id": "investing:WMT:...", "fiscal_quarter": "Q1 FY2027", "published_at_epoch": 1779000000,
  "statements": [ { "statement_id": "...", "order": 1, "topic": "guidance", "speaker": "John David Rainey", "text": "We are reiterating our full year guidance..." } ],
  "warnings": [] }
```

- `before_epoch` 이전에 발행된 가장 최근 콜의 핵심 문장(#145, 원문 그대로)을 순서대로 돌려줍니다.
- 직전 콜이 없으면 `available: false`, `warnings: ["prior_call_not_found"]` 입니다. 콜은 있지만 핵심 문장이 없으면
  `available: true`, `statements: []`, `warnings: ["key_statements_not_found"]` 입니다.
- 저장소가 직전 콜 조회를 지원하지 않으면 `available: false`, `warnings: ["prior_call_lookup_unsupported"]`, 조회 중
  예외가 나면 `200` 에 `available: false`, `warnings: ["prior_call_lookup_failed"]` 입니다.
- 요청 검증에 실패하면(`ticker` 누락, 0 이하 `before_epoch` 등) `422` 입니다.

### 10.6. 질의응답 요청 (`POST /v1/assistant/ask`, Backend ➔ logothea-assistant)

- logothea-assistant 는 `127.0.0.1:8100` 에만 바인딩되며, `X-Internal-Secret` 이 backend 의 `INTERNAL_SECRET` 과 같아야 합니다.
  다르거나 값이 설정되지 않았으면 `401`, 본문 검증에 실패하면 `422` 입니다.
- 본문은 외부 요청에 backend 가 확정한 `user_id`, `as_of_sequence`, `as_of_epoch`, `call_ended` 를 더한 것입니다.

```json
{ "user_id": "42", "ticker": "WMT", "call_id": "demo-wmt-q2fy27-1787227200000-1",
  "as_of_sequence": 17, "as_of_epoch": 1787227218, "anchor_sequence": 3, "call_ended": false,
  "question": "가이던스가 바뀌었어?", "suggested_question_id": null,
  "history": [ { "role": "user", "text": "..." }, { "role": "assistant", "text": "..." } ] }
```

- `call_ended` 는 질문 시점의 마지막 세그먼트가 콜 종료 신호인지이며, backend 가 정합니다.
- `question` 은 앞뒤 공백을 뺀 1~500자, `history` 는 최대 6개(후속 질문 3회), `anchor_sequence` 는 `as_of_sequence` 이하입니다.
  `suggested_question_id` 는 `summary`, `vs_last_quarter`, `guidance`, `vs_expectations`, `risks` 중 하나이며, 값이 있으면 질문 분류를 건너뜁니다.
- 응답은 `text/event-stream` 입니다. 생성하는 답은 `meta` → `delta`(여러 번) → `citations` → `done` 순서이고, 거절과 용어 사전 답은
  `citations` 없이 `meta` → `delta` → `done` 입니다. 실패하면 그 자리에서 `error` 를 보내고 끝납니다. 이미 보낸 `delta` 는 거두지 않습니다.

| 이벤트 | 데이터 |
|---|---|
| `meta` | `{scope: "anchor"\|"call", as_of_sequence, as_of_time, anchor_sequence, missing_sources[]}` — `as_of_sequence` 는 생성한 답에서는 실제로 근거에 쓴 마지막 세그먼트이고, 거절과 용어 사전 답에서는 요청 값입니다. `missing_sources` 는 `news`, `prior_call`, `estimates`, `segments_incomplete` 중 불러오지 못한 것입니다 |
| `delta` | `{text}` — 본문에 근거 표시 `[S12]`(세그먼트 sequence), `[N3]`(뉴스), `[P2]`(직전 콜 문장), `[E1]`(실적 추정치)가 들어 있습니다 |
| `citations` | `[{marker, type: "segment"\|"news"\|"prior_statement"\|"estimate"\|null, ref, title, source, published_at, start_ms, speaker, quote, verified}]` — 답에 처음 나온 순서입니다. 근거 목록에 없는 표시이거나 인용 문장의 수치가 원문과 맞지 않으면 `verified: false` 입니다 |
| `done` | `{status: "answered"\|"refused"\|"no_evidence", refusal_reason, suggested_question_ids[], warnings[], usage{input_tokens, output_tokens, cached_tokens}, latency_ms}` |
| `error` | `{code, message}` — `code` 는 `segments_not_found`, `context_unavailable`, `llm_timeout`, `llm_failed`, `llm_unparsable`, `internal` 입니다 |

- `refusal_reason` 은 `investment_advice`, `price_prediction`, `out_of_scope` 이며, `suggested_question_ids` 로 대신 볼 만한 추천 질문을 알려 줍니다.
- `warnings` 는 `uncited_number`(근거 표시 없이 수치를 말한 문장), `number_mismatch`, `unknown_marker:<표시>` 입니다.
- 근거 수집은 정보원마다 3초, OpenAI 호출은 1회 30초가 상한입니다. 세그먼트를 읽지 못하면 `error` 이고, 나머지 정보원은 빼고 답합니다.
- 연결이 끊기면 진행 중인 생성 호출도 닫습니다.
