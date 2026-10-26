# 모듈 간 계약 (API 명세)

EarningWhisperer 의 모듈(trading-terminal, backend, ai-engine, logothea-assistant, data_pipeline, frontend)이 주고받는
REST · STOMP · Redis 메시지의 형식을 정리한 문서입니다. 모듈을 고치는 팀원이 상대 모듈과 맞춰야 하는 필드와
상태 코드를 확인할 때 씁니다. 모듈 구성과 흐름은 [아키텍처](developer/architecture.md)에서 다룹니다.

- 절 번호는 코드 주석과 다른 문서가 참조하므로 바꾸지 않습니다. 없어진 계약은 "제거됨" 으로 남기고, 새 계약은
  해당 장의 끝에 번호를 이어 붙입니다.
- 계약을 바꾸는 PR 에서 이 문서의 해당 절을 함께 고칩니다.
- JSON 키는 계약마다 다릅니다. backend 는 전역 이름 규칙 없이 DTO 마다 snake_case 를 지정하므로, 같은 서버에서도
  요청은 snake_case, 응답은 camelCase 인 엔드포인트가 있습니다. 각 절의 표기를 그대로 따릅니다.

---

## 1. 전체 데이터 흐름

| # | 보내는 쪽 → 받는 쪽 | 방식 | 내용 | 절 |
|---|---|---|---|---|
| 1 | Trading Terminal → Backend | REST | 로그인, 주문 기록, 잔고 동기화, 종목 · 일정 · 사전 조회, 시연 제어, 질문 | 5, 7 |
| 2 | Backend → Trading Terminal | STOMP | 자막, 팩트체크, 직전 콜 대조, 번역, 종합 판단, 시장 지수, 종목 시세 | 4 |
| 3 | Trading Terminal → KIS OpenAPI | REST | 사용자가 입력한 주문, 잔고 · 체결 조회. backend 를 거치지 않습니다 | 범위 밖 |
| 4 | Backend → AI Engine | REST | 팩트체크, 직전 콜 대조, 번역, 종합 판단, 근거 준비 확인 | 9 |
| 5 | Backend ↔ logothea-assistant ↔ AI Engine | REST · SSE | 어닝콜 질의응답과 근거 조회 | 7.10, 10 |
| 6 | Data Pipeline → Backend | REST | 실시간 어닝콜 자막 세그먼트 | 6.4 |
| 7 | Data Pipeline → AI Engine | REST | 라이브 STT 청크 분석, 뉴스 · 녹취록 근거 적재 | 2 |
| 8 | Backend → Redis → Backend | Pub/Sub | 시장 지수 스냅샷(backend 가 발행하고 스스로 구독) | 6.3 |
| 9 | Backend → Frontend Web | STOMP | 쇼케이스 데모룸. 현재 frontend 는 연결하지 않습니다 | 4.1 |

시연에서는 data_pipeline 대신 backend 의 시연 재생(7.8)이 세그먼트를 넣습니다. 팩트체크 · 직전 콜 대조 · 종합
판단은 지금 시연 재생 경로에서만 호출하며, data_pipeline 이 넣은 세그먼트에는 자막과 번역만 나갑니다.

> 매매 신호로 주문을 내던 경로(AI Engine → Redis `trading-signals` → Backend 룰 엔진 → `/user/queue/signals` →
> Terminal)는 #127 에서 제거했습니다([ADR 0005](adr/0005-support-only-user-placed-orders.md)). 주문은 사용자가
> 터미널에서 직접 내는 주문만 있습니다.

---

## 2. [Contract 1] Data Pipeline ➔ AI Engine

### 2.1. 라이브 STT 청크 분석 (`POST /api/v1/analyze`)

- **현재 상태:** 이전 매매 신호 경로의 입구로 남아 있는 엔드포인트입니다(`api/routers/legacy_analysis.py`). 운영
  경로에서 호출하는 곳은 data_pipeline STT 워커(`stt_worker/take.py`)이며(시험 도구 `tools/mock/mock_webcast_e2e.py` 도 부릅니다), `SEND_TO_AI_ENGINE` 이 켜져 있을 때만 보냅니다.
  코드 기본값은 `true`, `data_pipeline/.env.example` 은 `false` 입니다.
- **통신 방식:** HTTP POST, 동기 호출(타임아웃 `STT_HTTP_TIMEOUT_SECONDS`, 기본 10초).
- AI Engine 은 받은 청크를 분석해 Redis `trading-signals`(3장)에 발행하고 결과를 응답으로도 돌려줍니다.

| 필드명       | 타입    | 필수 | 설명                                         |
| :----------- | :------ | :--: | :------------------------------------------- |
| `ticker`     | String  |  Y   | 종목 심볼 (예: "NVDA")                       |
| `text_chunk` | String  |  Y   | STT 텍스트 청크                              |
| `sequence`   | Integer |  N   | 청크 순번. 기본 0                            |
| `timestamp`  | Long    |  N   | 캡처 시점(Unix Epoch Second). 기본 현재 시각 |
| `is_final`   | Boolean |  N   | 어닝콜 세션 종료 여부. 기본 `false`          |

`market_data`, `section_type`, `source_type`, `request_priority`, `route_profile`, `needs_review`, `universe_profile`,
`investment_profile` 같은 선택 필드도 받지만 data_pipeline 은 보내지 않습니다(`models/legacy_contract_models.py`).

### 2.2. 뉴스 근거 적재 (`POST /api/v1/integration/collector/news`)

팩트체크(9.1)와 질의응답 뉴스 검색(10.4)이 쓰는 근거 뉴스를 넣습니다. data_pipeline 의 Finnhub 뉴스 작업(10분
간격)과 시연 도구 `tools/demo/collect_demo_evidence.py` 가 호출합니다.

- 요청: `{ "items": [ ... ] }`

| 필드명         | 타입            | 필수 | 설명                                                              |
| :------------- | :-------------- | :--: | :---------------------------------------------------------------- |
| `provider_id`  | String          |  Y   | 공급자 쪽 기사 ID                                                 |
| `ticker`       | String          |  Y   | 종목 심볼. 대문자로 맞춥니다                                      |
| `headline`     | String          |  Y   | 제목                                                              |
| `provider`     | String          |  N   | 기본 `"finnhub"`                                                  |
| `summary`      | String          |  N   | 요약                                                              |
| `content`      | String          |  N   | 본문. 없으면 `headline` + `summary` 로 적재합니다                 |
| `url`          | String          |  N   | 원문 주소                                                         |
| `source`       | String          |  N   | 매체 이름. 팩트체크 관련성 게이트가 서로 다른 매체를 셀 때 씁니다 |
| `published_at` | Long 또는 날짜  |  N   | 발행 시각                                                         |
| `metadata`     | Object          |  N   | 부가 정보                                                         |

- 응답: `{status, accepted_count, skipped_count, document_ids[], warnings[]}`. 적재할 본문이 비면 그 항목을 건너뛰고
  `empty_news_text:{ticker}:{provider_id}` 를 남깁니다.

### 2.3. 녹취록 적재 (`POST /api/v1/integration/collector/earnings-transcripts`)

직전 콜 대조(9.11)와 질의응답의 직전 콜 문장(10.5)이 쓰는 지난 어닝콜 녹취록을 넣습니다. data_pipeline 의 수동
가져오기(`collectors/transcripts/manual_import.py`)와 시연 도구 `tools/demo/ingest_demo_transcript.py` 가 호출합니다.

- 요청: `{ "items": [ ... ] }`

| 필드명           | 타입   | 필수 | 설명                                    |
| :--------------- | :----- | :--: | :-------------------------------------- |
| `provider_id`    | String |  Y   | 공급자 쪽 ID                            |
| `ticker`         | String |  Y   | 종목 심볼. 대문자로 맞춥니다            |
| `title`          | String |  Y   | 제목                                    |
| `content`        | String |  Y   | 녹취록 본문                             |
| `provider`       | String |  N   | 기본 `"investing"`                      |
| `published_at`   | 날짜   |  N   | 발행 시각                               |
| `fiscal_quarter` | String |  N   | 회계 분기 (예: `Q1 FY2027`)             |
| `speaker_turns`  | Array  |  N   | `[{speaker, text, section}]`            |
| `metadata`       | Object |  N   | 부가 정보                               |

- 응답은 2.2 와 같은 필드에 `key_statement_counts{document_id: n}` 이 더해집니다. 적재 뒤 경영진 핵심 문장을 LLM 으로
  추출하며, 추출에 실패해도 적재는 유지하고 `key_statement_extraction_failed`(문서별로는 `key_statement_extraction_failed:{document_id}`)를 남깁니다.

---

## 3. [Contract 2] AI Engine ➔ Redis `trading-signals` (받는 곳 없음)

- **현재 상태:** backend 는 #127 에서 이 채널의 구독을 제거했습니다. AI Engine 은 2.1 을 처리할 때 여전히 발행하며
  (`LEGACY_REDIS_PUBLISH_ENABLED`, 기본 `true`), 같은 내용을 보강한 `trading-signals-enriched` 채널에도 발행합니다.
  받는 곳이 없으므로 형식은 기록으로만 남깁니다.
- 메시지 모델은 `LegacySignalMessage`(`models/legacy_contract_models.py`)입니다. 아래 필드 외에 `action`,
  `confidence`, `strategy`, `hold_days`, `signal_brief` 등 선택 필드와 `schema_version` 이 있습니다.

| 필드명           | 타입    | 설명                                        |
| :--------------- | :------ | :------------------------------------------ |
| `ticker`         | String  | 종목 심볼                                   |
| `raw_score`      | Double  | 감성 방향 및 강도 (-1.0 ~ +1.0)             |
| `rationale`      | String  | LLM 분석 근거                               |
| `text_chunk`     | String  | 분석에 쓴 원문                              |
| `timestamp`      | Long    | 분석 완료 시점 (Unix Epoch Second)          |
| `is_session_end` | Boolean | 어닝콜 세션 종료 신호                       |

---

## 4. [Contract 3] Backend ➔ Clients (STOMP)

### 연결과 인증

| 항목 | 값 |
|---|---|
| 엔드포인트 | `/ws-native`(native WebSocket, 터미널), `/ws`(SockJS, 웹) |
| broker prefix | `/topic`, `/queue`. 앱 prefix `/app` 과 사용자 prefix `/user` 는 설정만 있고 쓰지 않습니다 |
| 인증 | CONNECT 프레임의 `Authorization: Bearer {accessToken}` 을 `StompJwtChannelInterceptor` 가 검증합니다 |

- 인증에 실패하면 ERROR 프레임(`STOMP 인증 실패`)으로 끊습니다. 터미널은 이 문구를 보면 access token 을 한 번
  갱신해 다시 연결하므로, 문구도 계약에 포함됩니다.
- CONNECT 없이 보낸 SUBSCRIBE 와, 인증된 세션의 클라이언트 SEND 는 모두 거부합니다. STOMP 는 서버에서
  클라이언트로만 흐릅니다.
- 토픽별 권한 구분은 없습니다. 로그인한 사용자는 모든 토픽을 구독할 수 있고, 로그인하지 않으면 어떤 토픽도
  구독할 수 없습니다.

| 목적지 | 발행 클래스 | 절 | 구독 |
|---|---|---|---|
| `/topic/live/demo`, `/topic/live/demo/price` | `DemoReplayService`, `DemoPriceService` | 4.1 | 없음(웹이 연결하지 않음) |
| `/topic/market/indices` | `MarketIndicesPublisher` | 4.4 | 터미널 |
| `/topic/transcript/{ticker}` | `TranscriptPublisher` | 4.5 | 터미널 |
| `/topic/factcheck/{ticker}` | `FactCheckPublisher` | 4.6 | 터미널 |
| `/topic/evaluation/{ticker}` | `EarningsSummaryPublisher` | 4.7 | 터미널 |
| `/topic/transcript-translation/{ticker}` | `TranscriptTranslationPublisher` | 4.8 | 터미널 |
| `/topic/transcript-diff/{ticker}` | `TranscriptDiffPublisher` | 4.9 | 터미널 |
| `/topic/prices` | `StockPricePublisher` | 4.10 | 터미널 |

### 4.1. Demo Replay Broadcast (웹 쇼케이스 데모룸)

- **Topic:** `/topic/live/demo`, `/topic/live/demo/price`
- **현재 상태:** backend 는 기동하면서부터 계속 발행하지만, 웹(frontend)은 #136 이후 비인증 연결이 거부되면서
  연결을 시도하지 않습니다(`frontend/src/hooks/useDemoWebSocket.ts`). 터미널은 구독하지 않습니다.
- `/topic/live/demo`: `DemoReplayService` 가 `data/mock-nvda-replay.json` 을 10초 간격으로 끝까지 재생하고, 마지막
  이벤트를 `is_session_end=true` 로 한 번 더 보낸 뒤 5초 쉬고 다시 시작합니다.

| 필드명           | 타입    | 설명                                     |
| :--------------- | :------ | :--------------------------------------- |
| `ticker`         | String  | 종목 심볼 (`NVDA`)                       |
| `text_chunk`     | String  | 원문 텍스트                              |
| `ai_score`       | Double  | 감성 점수                                |
| `rationale`      | String  | 분석 근거                                |
| `action`         | String  | `BUY` / `SELL` / `HOLD` (스크립트 값)    |
| `timestamp`      | Long    | 원본 어닝콜 시점 (Unix Epoch Second)     |
| `is_session_end` | Boolean | 루프 종료 신호. 항상 들어갑니다          |

- `/topic/live/demo/price`: `DemoPriceService` 가 1초마다 NVDA 가격을 무작위로 움직여 보냅니다.
  필드는 `ticker`, `price`, `change`, `change_percent`, `timestamp`(Unix Epoch Second)입니다.

### 4.2. Public Broadcast `/topic/live/{ticker}` (제거됨)

Redis `trading-signals` 수신을 계기로 발행하던 토픽입니다. #127 에서 구독을 제거한 뒤로 발행하는 코드가 없습니다.

### 4.3. Private Routing `/user/{userId}/queue/signals` (제거됨)

매매 명령을 보내던 개인 큐는 #127 에서 제거했습니다. 재접속 시 대기 명령을 복원하던 `GET /api/v1/trades/pending`
도 함께 제거했습니다.

### 4.4. Global Market Indices Broadcast (시장 지수 1분 스냅샷)

- **Topic:** `/topic/market/indices`
- **인증:** 로그인 필요(다른 토픽과 같습니다). 같은 데이터를 REST `GET /api/v1/market/indices`(7.7)는 인증 없이
  돌려줍니다.
- **설명:** 미국 주요 지수를 추종하는 ETF 5종의 스냅샷입니다. 원지수 시세는 유료라 ETF 시세를 그대로 씁니다.
- **발행 시점:** backend `MarketIndicesScheduler` 가 Redis `market-indices`(6.3)에 낸 메시지를 `MarketIndicesSubscriber`
  가 받을 때마다 심볼별로 한 건씩 보냅니다. 지원하지 않는 심볼은 버립니다.
- **backend 가공:** `trend` 를 계산하고(`change_percent > +0.05` 면 `up`, `< -0.05` 면 `down`, 그 밖은 `neutral`)
  `format` 을 붙입니다. `schema_version`, `source`, `published_at` 은 클라이언트에 보내지 않습니다.

| 필드명           | 타입   | 설명                                                   |
| :--------------- | :----- | :----------------------------------------------------- |
| `symbol`         | String | `SPY` \| `QQQ` \| `DIA` \| `IWM` \| `VIXY`             |
| `price`          | Double | 현재가                                                 |
| `change_percent` | Double | 전일 대비 등락률                                       |
| `trend`          | String | `up` \| `down` \| `neutral`                            |
| `format`         | String | 지금은 5종 모두 `index`. `percent` 는 정의만 있습니다  |
| `timestamp`      | Long   | 데이터 기준 시각 (Unix Epoch Second)                   |

### 4.5. Live Earnings Call Transcript Broadcast (어닝콜 자막)

- **Topic:** `/topic/transcript/{ticker}`
- **발행 시점:** `TranscriptService` 가 세그먼트를 받아 검증을 통과하면 바로 보냅니다. 세그먼트는 data_pipeline 의
  인입(6.4)이나 backend 시연 재생(7.8)에서 옵니다.
- 같은 처리에서 질의응답용 세그먼트 기록(10.1)과 번역 묶음(4.8)도 함께 시작합니다. 자막은 이들을 기다리지 않습니다.
- **순서:** 같은 `call_id` 안에서 `sequence` 는 증가하고, 같은 세그먼트를 다시 보내지 않습니다.

| 필드명           | 타입    | 설명                                                            |
| :--------------- | :------ | :-------------------------------------------------------------- |
| `ticker`         | String  | 종목 심볼                                                       |
| `call_id`        | String  | 어닝콜 세션 식별자                                              |
| `sequence`       | Integer | 세그먼트 번호                                                   |
| `start_ms`       | Long    | 세그먼트 시작 시각 (밀리초)                                     |
| `end_ms`         | Long    | 세그먼트 끝 시각 (밀리초)                                       |
| `text`           | String  | 세그먼트 텍스트                                                 |
| `speaker`        | String  | 발화자 라벨. 값이 없으면 키가 빠집니다                          |
| `timestamp`      | Long    | 세그먼트 시각 (Unix Epoch Second). 인입 값을 그대로 넘깁니다    |
| `is_session_end` | Boolean | 어닝콜 세션 종료 신호. 항상 들어갑니다                          |

### 4.6. Live Fact-Check Broadcast (실시간 팩트체크)

- **Topic:** `/topic/factcheck/{ticker}`
- **설명:** 어닝콜 발언의 검증 가능한 주장을 AI Engine 이 뉴스 근거와 대조한 결과입니다(9.1).
- **발행 시점:** AI Engine 이 `status=COMPLETED` 이고 `claims[]` 가 비어 있지 않은 결과를 돌려줄 때만 보냅니다.
  `BUFFERING` · `REJECTED` · `DISCARDED` 와 주장이 0건인 결과는 보내지 않습니다.
- **호출 경로:** 지금은 시연 재생(7.8)에서만 AI Engine 에 제출합니다. data_pipeline 인입(6.4)으로 들어온
  세그먼트에는 팩트체크가 돌지 않습니다. `ai-engine.fact-check-enabled` 로 끕니다.
- **지연:** 검증에 LLM 호출이 최대 2번 들어가 해당 발언보다 늦게 도착합니다. 클라이언트는
  `batch_start_sequence` ~ `batch_end_sequence` 범위로 어느 발언의 판정인지 짝짓습니다.

| 필드명                 | 타입    | 설명                                              |
| :--------------------- | :------ | :------------------------------------------------ |
| `ticker`               | String  | 종목 심볼                                         |
| `call_id`              | String  | 어닝콜 세션 식별자 (4.5 와 같은 값)               |
| `batch_start_sequence` | Integer | 검증한 세그먼트 범위의 시작 `sequence`            |
| `batch_end_sequence`   | Integer | 검증한 세그먼트 범위의 끝 `sequence`              |
| `claims`               | Array   | 판정 목록. 항목은 9.3 과 같습니다 (1건 이상)      |

판정의 화면 표기는 9.5 를 따릅니다.

### 4.7. Earnings Call Summary Broadcast (콜 종료 후 종합 판단)

- **Topic:** `/topic/evaluation/{ticker}`
- **설명:** 시연 재생이 끝난 뒤 회차당 한 번 보내는 종합 판단입니다. 콜 전체를 놓고 낸 방향 · 강도 · 신뢰도와
  회피 지표 · 파급 영향 · 손절 계획이 들어 있습니다.
- **발행 시점:** 재생이 정상 완료되고(중지된 회차 제외) 세그먼트가 1건 이상 발행되었으며, AI Engine 이 판단
  본문(`judgment`)을 돌려준 경우에만 보냅니다. 지금은 시연 재생 경로에만 있습니다.
- **소요 시간:** 마지막 세그먼트 직후 제출되지만 `analyze`(9.6)와 `earnings/intelligence`(9.7)를 차례로 부르므로
  수 초에서 십수 초가 걸립니다. `analyze` 가 읽기 타임아웃(`ai-engine.timeout-ms`, 기본 50초) 안에 응답하지 않으면
  보내지 않고 끝나며, `earnings/intelligence` 만 실패하면 `intelligence_available=false` 로 판단만 보냅니다.
- **발행되지 않는 경우:** 중지된 회차, 세그먼트 0건인 회차, `ai-engine.summary-enabled=false`, 어닝콜 전문이 빈 경우,
  `analyze` 가 판단 본문을 돌려주지 않은 경우. 사유는 로그에 남습니다.
- **회차 대조:** 같은 종목을 연달아 재생하면 이전 회차의 판단이 늦게 도착할 수 있습니다. 클라이언트는 `call_id` 를
  지금 회차(4.5)와 비교해 다르면 버립니다. backend 도 종합 판단 생성을 시작하기 전에 같은 검사를 합니다.

| 필드명                   | 타입    | 필수 | 설명                                                        |
| :----------------------- | :------ | :--: | :---------------------------------------------------------- |
| `ticker`                 | String  |  Y   | 종목 심볼                                                   |
| `call_id`                | String  |  Y   | 어닝콜 세션 식별자                                          |
| `generated_at`           | String  |  Y   | 생성 시각 (ISO-8601)                                        |
| `judgment`               | Object  |  Y   | LLM 판단 본문. 9.6 응답의 `analysis` 와 같습니다            |
| `gate`                   | Object  |  N   | 실행 가능성 게이트. 9.6 응답의 `signal_brief` 와 같습니다   |
| `intelligence_available` | Boolean |  N   | 부가 정보(9.7) 조회 성공 여부                               |
| `evasion`                | Object  |  N   | 질문 회피 지표. 9.7 응답의 `omission_evasion`               |
| `impact_chain`           | Array   |  N   | 연쇄 영향 후보. 9.7 응답과 같습니다                         |
| `risk_plan`              | Object  |  N   | 손절 · 익절 계획. 9.7 응답과 같습니다                       |
| `warnings`               | Array   |  N   | 엔진이 붙인 주의사항 문자열                                 |

- **없는 값의 표현이 두 가지입니다.** 위 표의 최상위 필드는 값이 없으면 키가 빠집니다. 반면 `judgment` · `gate` ·
  `risk_plan` 같은 중첩 객체 안의 없는 값은 `null` 로 옵니다.
- **부가 정보 묶음.** `impact_chain`, `risk_plan`, `warnings` 는 9.7 한 번의 호출에서 나오므로 함께 오거나 함께
  빠집니다. `evasion` 은 시연 스크립트에 애널리스트 질문(`analyst_qa`)이 없으면 이 셋이 있어도 빠집니다.
  `intelligence_available=false` 는 조회 자체가 실패한 경우이고, `true` 인데 `risk_plan.available=false` 이면 엔진이
  계획을 낼 수 없다고 답한 경우입니다. 화면에서 둘을 다르게 안내합니다. 전자는 부가 정보를 가져오지 못했다는
  안내, 후자는 `risk_plan.invalidation_text` 의 사유입니다.
- **`judgment` 와 `gate` 는 다른 질문의 답입니다.** `gate.action` 은 판단 방향이 아니라 "이 판단대로 움직여도
  되는가" 의 답입니다. 뉴스 근거가 적재되지 않았으면 `missing_rag_evidence` 때문에 `judgment.direction=BULLISH` 와
  `gate.action=AVOID` 가 함께 나올 수 있습니다. 화면에서는 판단과 실행 보류 사유를 나눠 보여 줍니다.
- **`warnings` 는 화면에 보여 줍니다.** "RAG evidence is empty" 같은 항목이 옵니다. 숨기면 검증되지 않은 판단이
  검증된 것처럼 보입니다.

### 4.8. Transcript Translation Broadcast (어닝콜 자막 한국어 번역)

- **Topic:** `/topic/transcript-translation/{ticker}`
- **설명:** 4.5 로 나간 자막 세그먼트의 한국어 번역입니다(#110). backend 가 세그먼트를 몇 개씩 묶어 AI Engine(9.10)에
  번역을 요청하고 결과를 이 채널로 보냅니다. 용어 사전(7.9)에 있는 용어는 사전의 번역어로 고정됩니다.
  data_pipeline 인입과 시연 재생 모두 이 경로를 탑니다.
- **발행 시점:** 다음 중 하나가 되면 묶음을 보냅니다. 값은 `transcript-translation.*` 설정으로 바꿉니다. 번역은 AI Engine
  응답 시간만큼 더 늦게 도착합니다.
  - 세그먼트 3개가 모였을 때
  - 묶음의 첫 세그먼트가 들어온 지 10초가 지났을 때
  - 글자 수 상한(1,200자)에 닿았을 때. 붙이면 상한을 넘는 세그먼트는 다음 묶음으로 넘깁니다
  - 세션 종료 세그먼트(`is_session_end=true`)가 들어왔을 때
- **발행되지 않는 경우:** 사유는 backend 로그에 남습니다. 원문을 번역 대신 보내지 않습니다.
  - 번역이 꺼져 있을 때(`ai-engine.translation-enabled=false`)
  - AI Engine 호출이 실패하거나 번역에 실패했을 때(`available=false`)
  - 응답의 `sequence` 가 요청한 묶음의 첫 번호와 다를 때
  - 대기열에서 30초(`transcript-translation.max-age-ms`) 넘게 밀렸을 때
- **자막과의 관계:** 4.5 원문은 번역을 기다리지 않고 먼저 나갑니다. 클라이언트는 `sequences` 로 어느 세그먼트들의
  번역인지 짝짓습니다. 묶음 단위로 한 문단이 오며 세그먼트별로 나뉘어 있지 않습니다.

| 필드명       | 타입           | 설명                                                                 |
| :----------- | :------------- | :------------------------------------------------------------------- |
| `ticker`     | String         | 종목 심볼                                                            |
| `call_id`    | String         | 어닝콜 세션 식별자 (4.5 와 같은 값)                                  |
| `sequences`  | Array<Integer> | 이 번역에 담긴 4.5 세그먼트의 `sequence`. 오름차순, 1개 이상         |
| `text_ko`    | String         | 한국어 번역문                                                        |
| `terms_used` | Array<String>  | 사전 번역어가 번역문에 실제로 들어간 용어 (원문 표기). 없으면 빈 배열 |

### 4.9. Transcript Diff Broadcast (직전 콜 대조)

- **Topic:** `/topic/transcript-diff/{ticker}`
- **설명:** 이번 발언을 직전 콜 경영진 발언과 비교한 결과입니다(9.11).
- **발행 시점:** 시연 재생이 세그먼트마다 AI Engine 에 대조를 요청하고, 응답이 `available=true` 이며 `items` 가
  1건 이상일 때만 보냅니다. 지금은 시연 재생 경로에만 있습니다. `ai-engine.transcript-diff-enabled` 로 끕니다.

| 필드명              | 타입    | 설명                                                    |
| :------------------ | :------ | :------------------------------------------------------ |
| `ticker`            | String  | 종목 심볼                                               |
| `call_id`           | String  | 어닝콜 세션 식별자 (4.5 와 같은 값)                     |
| `sequence`          | Integer | 대조한 세그먼트의 `sequence`                            |
| `previous_document` | Object  | 비교에 쓴 직전 콜. `document_id`, `title`, `published_at`, `fiscal_quarter`, `source_url` |
| `items`             | Array   | 대조 항목. 9.11 응답의 `items[]` 와 같습니다            |

### 4.10. Stock Price Broadcast (종목 시세)

- **Topic:** `/topic/prices`
- **설명:** 1초마다 그 사이 시세가 바뀐 종목만 모아 보냅니다(`StockPricePublisher`). 시세는 Finnhub WebSocket 체결과
  일봉 동기화(전일 종가)로 바뀝니다. Finnhub 키가 없으면 체결 갱신이 없습니다.
- 페이로드는 배열이고 키는 camelCase 입니다. 같은 형식을 REST `GET /api/v1/stocks/prices`(7.11)도 돌려줍니다.

| 필드명          | 타입   | 설명                                                  |
| :-------------- | :----- | :---------------------------------------------------- |
| `ticker`        | String | 종목 심볼                                             |
| `currentPrice`  | Double | 현재가                                                |
| `previousClose` | Double | 전일 종가                                             |
| `changePercent` | Double | 전일 대비 등락률                                      |
| `updatedAt`     | Long   | 갱신 시각. **Unix Epoch 밀리초**입니다(8.5 의 예외)   |

---

## 5. [Contract 4] Trading Terminal ➔ Backend (체결 보고 · 잔고 동기화)

### 5.1. 체결 결과 보고 (`POST /api/v1/trades/{tradeId}/callback`)

- **설명:** `PENDING` 으로 기록한 수동 주문(7.3)이 나중에 체결되거나 실패했을 때 결과를 보고해 `EXECUTED` 또는
  `FAILED` 로 확정합니다. 지금 터미널은 `EXECUTED` 만 보내며 `FAILED` 를 보내는 곳은 없습니다. 터미널은 체결 내역 화면 진입, 새로고침, KIS 체결통보 때 `GET /api/v1/trades` 에서
  `PENDING` 이고 `brokerOrderId` 가 있는 주문을 골라 KIS 체결을 조회한 뒤 이 엔드포인트로 보냅니다.
- **인증:** JWT

| 필드명            | 타입    | 필수 | 설명                                                    |
| :---------------- | :------ | :--: | :------------------------------------------------------ |
| `status`          | String  |  Y   | `EXECUTED` \| `FAILED`                                  |
| `broker_order_id` | String  |  N   | 증권사 주문번호. `EXECUTED` 이면 필수                   |
| `executed_price`  | Double  |  N   | 체결 평균가. 없으면 0                                   |
| `executed_qty`    | Integer |  N   | 체결 수량. 없으면 0. 받으면 주문 수량을 이 값으로 덮어씁니다 |
| `error_message`   | String  |  N   | 실패 사유. 저장하지 않고 로그에만 남깁니다              |

```json
{ "status": "EXECUTED", "broker_order_id": "ODNO_123456789", "executed_price": 125.50, "executed_qty": 10, "error_message": null }
```

| 상태 | 의미 |
|---|---|
| 200 | 반영함. 본문 없음. 같은 값으로 다시 보내도 200 입니다 |
| 400 | 형식 위반 (`EXECUTED` 인데 `broker_order_id` 없음 등) |
| 409 | 상태 충돌. 이미 `EXECUTED` 인 주문에 다른 체결값, `FAILED` 주문에 `EXECUTED`, `EXECUTED` · `EXPIRED` 주문에 `FAILED` 가 왔을 때. `FAILED` 주문에 `FAILED` 가 다시 오면 200 입니다 |
| 503 | 같은 주문의 동시 처리로 잠금을 얻지 못함. `Retry-After: 1` |

- `EXPIRED` 상태에서 `EXECUTED` 를 받으면 정정 전이로 처리합니다.
- 자체 페이퍼 계정(`SELF_PAPER`)의 주문이면 이 시점에 backend 가 보유 종목과 예수금을 직접 반영하도록 되어 있습니다.
  다만 지금 터미널은 자체 페이퍼 계정 주문에 이 보고를 보내지 않습니다(8.6).

### 5.2. 계좌 잔고 동기화 (`POST /api/v1/portfolio/sync`)

- **설명:** 터미널이 KIS 계좌로 주문을 낸 뒤 KIS 계좌 잔고를 backend 에 덮어씁니다.
- **인증:** JWT

| 필드명              | 타입   | 필수 | 설명                                                  |
| :------------------ | :----- | :--: | :---------------------------------------------------- |
| `cash_balance`      | Double |  Y   | 예수금                                                |
| `positions`         | Array  |  N   | `[{ticker, quantity, avg_price}]`                     |
| `synced_at`         | Long   |  N   | 동기화 시각 (Unix Epoch Second)                       |
| `broker_account_id` | Long   |  N   | 대상 계좌. 없으면 활성 계좌                           |

```json
{ "cash_balance": 15000000, "positions": [ { "ticker": "NVDA", "quantity": 15, "avg_price": 120.00 } ] }
```

- 성공은 200, 본문 없음입니다. 활성 계좌가 없으면 `KIS_PAPER` 계좌를 만들어 반영합니다.
- `broker_account_id` 가 활성 계좌와 다르면 409(본문 없음)입니다.
- 터미널은 `cash_balance` 와 `positions` 만 보냅니다.

---

## 6. [Contract 6] 시장 데이터와 자막 인입

### 6.1. 어닝콜 일정과 종목 목록

어닝콜 일정과 종목 목록은 data_pipeline 이 아니라 backend 스케줄러가 직접 가져옵니다. data_pipeline → backend
일정 전송 계약은 2026-04-03 에 폐기했습니다.

| 데이터 | 스케줄러 | 출처 | 주기 |
|---|---|---|---|
| 어닝콜 일정(오늘부터 90일) | `FmpEarningsScheduler` | FMP `/stable/earnings-calendar` | 기동 시 1회, 매일 06:00 UTC. `FMP_API_KEY` 가 없으면 꺼집니다 |
| 지난 실적 결과(EPS) | `EarningsResultSyncScheduler` | Finnhub `/stock/earnings` | 매주 일요일 02:00 UTC. 관심종목 대상 |
| S&P 500 구성 종목 | `Sp500SyncScheduler` | GitHub `datasets/s-and-p-500-companies` CSV | 1 · 4 · 7 · 10월 1일 09:00 UTC. 편입 제외 종목은 `active=false` |

클라이언트는 7.6 의 REST 로 DB 에 저장된 일정을 조회합니다.

### 6.2. 실시간 주가 Redis `market-data` (제거됨)

이 채널을 발행하거나 구독하는 코드는 없습니다. 종목 시세는 backend 가 Finnhub WebSocket 에서 직접 받아 4.10 으로
보냅니다.

### 6.3. 시장 지수 Redis `market-indices`

- **통신 방식:** Redis Pub/Sub, 채널 `market-indices`
- **발행:** backend `MarketIndicesScheduler` 가 기동 시 한 번, 이후 60초마다 Finnhub `/quote` 로 ETF 5종(`SPY`, `QQQ`,
  `DIA`, `IWM`, `VIXY`)을 조회해 심볼별로 한 건씩 발행합니다. 장 시간과 관계없이 같은 주기입니다.
- **구독:** 같은 backend 의 `MarketIndicesSubscriber` 가 받아 캐시(`MarketIndicesCache`)를 심볼별 마지막 값으로
  덮어쓰고 4.4 로 보냅니다.
- **실패 처리:** 조회에 실패한 심볼은 그 회차에 발행하지 않고 직전 값을 다시 보내지도 않습니다. 캐시는 직전 값을
  유지합니다. 한 건도 발행하지 못한 회차에는 경고 로그만 남깁니다.

| 필드명           | 타입   | 필수 | 설명                                                         |
| :--------------- | :----- | :--: | :----------------------------------------------------------- |
| `schema_version` | String |  Y   | `"1.0"`                                                      |
| `source`         | String |  Y   | `"finnhub-quote"`                                            |
| `symbol`         | String |  Y   | `SPY` \| `QQQ` \| `DIA` \| `IWM` \| `VIXY`                   |
| `price`          | Double |  Y   | 현재가 (소수 2자리)                                          |
| `change_percent` | Double |  Y   | 전일 대비 등락률 (소수 2자리)                                |
| `timestamp`      | Long   |  Y   | 데이터 기준 시각 (Finnhub quote 의 `t`, 없으면 발행 시각)    |
| `published_at`   | Long   |  Y   | 발행 시각 (Unix Epoch Second)                                |

```json
{ "schema_version": "1.0", "source": "finnhub-quote", "symbol": "SPY", "price": 543.21, "change_percent": 0.42,
  "timestamp": 1730000000, "published_at": 1730000003 }
```

### 6.4. 실시간 어닝콜 자막 세그먼트 (`POST /api/v1/internal/transcript-segment`)

- **통신 방식:** HTTP POST, 세그먼트 단위
- **인증:** `X-Internal-Secret` (8.3)
- **호출하는 곳:** data_pipeline STT 워커(`stt_worker/take.py`), 질의응답 평가 하네스(`logothea-assistant/eval/seed.py`)
- **설명:** 받은 세그먼트를 검증해 바로 4.5 로 보내고, 질의응답용 기록(10.1)과 번역 묶음(4.8)을 시작합니다. 응답은
  자막 발행까지 마친 뒤 돌려주며, 질의응답 기록은 그 뒤에 비동기로 저장합니다.

| 필드명           | 타입    | 필수 | 설명                                              |
| :--------------- | :------ | :--: | :------------------------------------------------ |
| `ticker`         | String  |  Y   | 종목 심볼                                         |
| `call_id`        | String  |  Y   | 어닝콜 세션 식별자. 같은 종목의 콜과 재방송을 구분 |
| `sequence`       | Integer |  Y   | 세그먼트 번호. 0 이상                             |
| `start_ms`       | Long    |  Y   | 세그먼트 시작 시각 (밀리초, 0 이상)               |
| `end_ms`         | Long    |  Y   | 세그먼트 끝 시각 (밀리초, 0 이상)                 |
| `text`           | String  |  Y   | 세그먼트 텍스트                                   |
| `speaker`        | String  |  N   | 발화자 라벨                                       |
| `timestamp`      | Long    |  Y   | 세그먼트 시각 (Unix Epoch Second, 0 이상). 시연은 `call_started_at + start_ms`, data_pipeline 은 전송 시각 |
| `is_session_end` | Boolean |  N   | 어닝콜 세션 종료 신호. 없으면 `false`             |

```json
{ "ticker": "NVDA", "call_id": "NVDA-20261023-210000", "sequence": 142, "start_ms": 873000, "end_ms": 883000,
  "text": "We saw record demand in data center this quarter.", "speaker": null, "timestamp": 1730000000, "is_session_end": false }
```

| 상태 | 의미 |
|---|---|
| 202 | 받음. 본문 없음 |
| 400 | 필드 검증 실패(`{"error": "<필드>: <메시지>"}`, 필드 이름은 Java 이름), 또는 `sequence` 가 직전 값 이하(`{"error": "sequence regress detected for call_id=..."}`) |
| 401 | `X-Internal-Secret` 불일치 또는 서버에 시크릿이 설정되지 않음 |
| 409 | `is_session_end: true` 뒤 같은 `call_id` 로 다시 보냄(`{"error": "session already ended for call_id=..."}`) |

- `sequence` 는 직전 값보다 크기만 하면 됩니다. 0 에서 시작하거나 1씩 늘 필요는 없지만, 같은 번호를 다시 보내면
  400 입니다.
- 어닝콜이 끝나면 마지막 세그먼트에 `is_session_end: true` 를 한 번 보내고, 같은 `call_id` 로 더 보내지 않습니다.
  종료된 `call_id` 는 backend 를 다시 시작하기 전까지 종료 상태로 남습니다.
- **data_pipeline 의 현재 전송 방식:** 오디오를 약 10초씩 겹침 없이 잘라 인식한 텍스트를 그대로 보내며, 2.1 에 보내는
  `text_chunk` 와 같은 문자열입니다. `speaker` 는 늘 `null` 이고, `start_ms` · `end_ms` 는 캡처를 시작한 뒤 흐른
  시간입니다. `call_id` 기본값은 `{TICKER}-YYYYMMDD-HHMMSS` 입니다. 시크릿이 없으면 backend 로 보내지 않습니다.

---

## 7. [Contract 7] Terminal · Web ➔ Backend (REST API)

인증이 필요한 엔드포인트는 `Authorization: Bearer {accessToken}` 헤더가 필요합니다. 인증 규칙은 8.1, 오류 형식은
8.4 에 있습니다. "호출" 열은 지금 그 엔드포인트를 부르는 클라이언트입니다.

### 7.1. 인증 (Auth)

| Method | Endpoint | 인증 | 호출 | 설명 |
| :----- | :------- | :--: | :--- | :--- |
| POST | `/api/v1/auth/signup` | 불필요 | 웹 | 이메일 회원가입 |
| POST | `/api/v1/auth/login` | 불필요 | 터미널, 웹 | 이메일 로그인 |
| POST | `/api/v1/auth/refresh` | 쿠키 | 터미널, 웹 | access token 재발급과 refresh token 회전 |
| POST | `/api/v1/auth/logout` | 쿠키 | 터미널, 웹 | refresh token 폐기 |
| POST | `/api/v1/auth/oauth/callback` | 불필요 | 터미널, 웹 | Google · Kakao 로그인 |

- **signup:** 요청 `{email, password, nickname}`. `email` 은 이메일 형식이고 `.local` · `.invalid` · `.test` · `.example`
  도메인은 받지 않습니다. `password` 는 8자 이상, `nickname` 은 50자 이하입니다. 성공은 201 `{"userId": N}`, 이메일
  중복은 400 입니다.
- **login:** 요청 `{email, password}`. 성공은 200 `{"access_token": "...", "token_type": "Bearer"}` 와 refresh token
  쿠키입니다. 실패는 400 입니다.
- **refresh token 쿠키:** 이름 `refresh_token`, HttpOnly, SameSite=Strict, Path `/api/v1/auth`, 수명 7일입니다. Secure 속성은
  `JWT_COOKIE_SECURE` 로 정하며 시연 서버는 `true` 입니다.
- **refresh:** 본문 없이 쿠키만 보냅니다. 성공하면 login 과 같은 응답과 새 쿠키를 줍니다. 쿠키가 없거나 무효면 401,
  같은 토큰으로 동시에 갱신하면 429 이며 둘 다 본문이 없습니다. 이미 회전된 토큰을 다시 쓰면 같은 계열(family)의
  토큰을 모두 무효화합니다.
- **logout:** 204 와 쿠키 삭제(Max-Age=0)입니다. 서버에서도 그 계열을 무효화합니다.
- **oauth/callback:** 요청 `{code, redirect_uri, provider, code_verifier}`. `provider` 는 `GOOGLE` · `KAKAO`(대소문자
  무관), `code_verifier` 는 PKCE 를 쓸 때만 보냅니다. 성공은 login 과 같습니다. provider 가 틀리면 400, 코드 교환에
  실패하면 401, 그 밖의 오류는 500 이며 모두 본문이 없습니다.

### 7.2. 사용자 (Users)

| Method | Endpoint | 인증 | 호출 | 설명 |
| :----- | :------- | :--: | :--- | :--- |
| GET | `/api/v1/users/me` | 필요 | 터미널, 웹 | 내 정보 |

- 응답 `{id, email, nickname, role, provider, createdAt}`. `role` 은 `FREE` · `PRO` 중 하나지만 지금은 가입하면 늘
  `FREE` 이고 바꾸는 경로가 없습니다(8.2). `provider` 는 `LOCAL` · `GOOGLE` · `KAKAO`, `createdAt` 은 시간대 없는
  ISO 날짜 문자열입니다.
- `PUT /api/v1/users/settings` 와 `GET` · `PUT /api/v1/portfolio/settings`(매매 모드와 룰 엔진 설정)는 #127 에서
  제거했습니다.

### 7.3. 거래 내역 (Trades)

| Method | Endpoint | 인증 | 호출 | 설명 |
| :----- | :------- | :--: | :--- | :--- |
| GET | `/api/v1/trades` | 필요 | 터미널, 웹 | 내 거래 내역. `page`(기본 0), `size`(기본 20), `startDate`(ISO 날짜시각, 이 시각 이후만) |
| POST | `/api/v1/trades/manual` | 필요 | 터미널 | 수동 주문 기록 (아래) |
| POST | `/api/v1/trades/{tradeId}/callback` | 필요 | 터미널 | 체결 결과 보고 (5.1) |

**`GET /api/v1/trades` 응답:** Spring `Page` 형식(`content`, `totalElements`, `totalPages`, `number`, `size` 등)이며
`content` 는 생성 시각 내림차순의 아래 항목입니다.

| 필드 | 타입 | 설명 |
| :--- | :--- | :--- |
| `id` | Long | 거래 ID |
| `ticker` | String | 종목 |
| `side` | Enum | `BUY` \| `SELL` |
| `orderType` | Enum | `MARKET` \| `LIMIT` |
| `orderQty` | Integer | 주문 수량 |
| `price` | Double | 주문 지정가. 미체결 주문에도 있습니다 |
| `executedQty` | Integer | 체결 수량. 미체결이면 0 |
| `executedPrice` | Double | 체결 평균가. 미체결이면 `null` |
| `status` | Enum | `PENDING` \| `EXECUTED` \| `FAILED` \| `EXPIRED` |
| `brokerOrderId` | String | 증권사 주문번호(KIS ODNO). 미체결 주문에도 보존합니다 |
| `createdAt` | String | 주문 생성 시각. 시간대 없는 ISO 날짜 문자열 |

#### `POST /api/v1/trades/manual`

사용자가 터미널에서 직접 낸 주문의 결과를 기록합니다. backend 가 주문을 지시하지 않으므로 터미널이 KIS 에 주문한
뒤 결과를 그대로 보고합니다.

| 필드 | 타입 | 필수 | 설명 |
| :--- | :--- | :--: | :--- |
| `ticker` | String | Y | 종목 |
| `side` | String | Y | `BUY` \| `SELL` |
| `order_type` | String | Y | `LIMIT` \| `MARKET` |
| `order_qty` | Integer | Y | 주문 수량. 1 이상 |
| `price` | Double | Y | 브로커에 보낸 지정가. 0 이상 |
| `executed_qty` | Integer | Y | 체결 수량. 0 이상 |
| `executed_price` | Double | N | 체결 평균가 |
| `broker_order_id` | String | N | 증권사 주문번호, 50자 이하. `EXECUTED` 이면 필수 |
| `status` | String | Y | `EXECUTED` \| `PENDING` \| `FAILED` |
| `error_message` | String | N | 500자 이하. 저장하지 않습니다 |

```json
{ "ticker": "WMT", "side": "BUY", "order_type": "LIMIT", "order_qty": 1, "price": 107.47, "executed_qty": 0,
  "executed_price": null, "broker_order_id": "0000044600", "status": "PENDING", "error_message": null }
```

- 성공은 201 `{"tradeId": 123}` 입니다. 활성 증권 계좌(`BrokerAccount`)가 없으면 422 입니다.
- `PENDING` 은 KIS 가 주문을 접수했지만(주문번호 반환) 아직 체결되지 않은 상태입니다. 살아 있는 주문이므로
  `FAILED` 로 적지 않습니다. 체결되면 5.1 로 확정합니다.
- `PENDING` 은 `app.trade.manual-pending-ttl-seconds`(기본 24시간)가 지나면 `EXPIRED` 로 바뀝니다. KIS 당일 주문이
  장 마감에 취소되는 것에 맞춘 값이며, 뒤에 체결이 확인되면 5.1 로 `EXECUTED` 로 정정합니다.
- KIS 해외주식 매수에는 시장가 코드가 없어 터미널의 "즉시 체결" 도 현재가 기준 지정가로 바꿔 보냅니다. 그래서 KIS
  주문은 `order_type=LIMIT` 이고 `price` 는 실제로 보낸 지정가입니다. 현재가를 조회하지 못해 주문 전에 실패하면
  `MARKET` · `price: 0` 으로 기록합니다.
- `EXECUTED` 로 기록하면 주문 수량을 `executed_qty` 로 덮어씁니다.

### 7.4. 포트폴리오 (Portfolio)

| Method | Endpoint | 인증 | 호출 | 설명 |
| :----- | :------- | :--: | :--- | :--- |
| POST | `/api/v1/portfolio/sync` | 필요 | 터미널 | 계좌 잔고 동기화 (5.2) |
| GET | `/api/v1/portfolio/broker-accounts` | 필요 | 터미널 | 내 증권 계좌 목록 `[{id, accountType, alias, cashBalance, active}]`. `accountType` 은 `KIS_REAL` \| `KIS_PAPER` \| `SELF_PAPER` |
| PUT | `/api/v1/portfolio/broker-accounts/{brokerAccountId}/activate` | 필요 | 없음 | 활성 계좌 변경. 200, 본문 없음 |
| GET | `/api/v1/portfolio/asset-history` | 필요 | 터미널 | 자산 추이 `[{date, totalAssetUsd}]`. `days` 는 7 · 30 · 90(기본 30), 다른 값은 400. `date` 는 `YYYY-MM-DD` |
| GET | `/api/v1/portfolio/positions` | 필요 | 터미널 | 활성 계좌의 보유 종목 `[{ticker, quantity, avgPrice}]`. 활성 계좌가 없으면 `[]` |

### 7.5. 관심종목 (Watchlist)

| Method | Endpoint | 인증 | 호출 | 설명 |
| :----- | :------- | :--: | :--- | :--- |
| GET | `/api/v1/watchlist` | 필요 | 터미널, 웹 | 내 관심종목 `[{ticker, companyName, sector}]` |
| POST | `/api/v1/watchlist` | 필요 | 터미널, 웹 | 관심종목 추가. 요청 `{ticker}`, 응답 200 `{ticker, companyName, sector}` |
| DELETE | `/api/v1/watchlist/{ticker}` | 필요 | 터미널, 웹 | 관심종목 삭제. 204 |
| GET | `/api/v1/watchlist/search?q={query}` | 필요 | 웹 | 종목 검색. 티커 · 회사명 부분 일치(대소문자 무시), 편입 종목만, 최대 20건. 빈 `q` 는 `[]` |

- POST 는 이미 추가한 종목이면 400("이미 관심종목에 추가된 종목입니다."), `stocks` 테이블에 없는 종목이면
  400("지원하지 않는 종목입니다: X")입니다.
- DELETE 는 목록에 없는 종목이면 400 입니다.

### 7.6. 어닝콜 일정 (Earnings Calendar)

| Method | Endpoint | 인증 | 호출 | 설명 |
| :----- | :------- | :--: | :--- | :--- |
| GET | `/api/v1/earnings-calendar` | 필요 | 웹 | 내 관심종목의 앞으로 남은 일정 `[{ticker, companyName, scheduledAt, confirmed}]`. `days` 파라미터는 받지만 쓰지 않습니다 |
| GET | `/api/v1/earnings-calendar/terminal-timeline` | 필요 | 터미널 | S&P 500 전체의 `days`일(기본 90, 최대 90) 일정 `[{ticker, companyName, scheduledAt, confirmed, marketSession}]` |
| POST | `/api/v1/earnings-calendar/sync` | 필요 | 없음 | 일정 수동 갱신(개발용). 200 텍스트. `FMP_API_KEY` 가 없으면 409 텍스트 |

- `scheduledAt` 은 Unix Epoch Second 입니다. `marketSession` 은 `bmo`(장 시작 전) · `amc`(장 마감 후) · `dmh`(장중) ·
  `null` 입니다. 날짜별 묶기는 터미널이 합니다.

### 7.7. 시장 지수 (Market Indices)

| Method | Endpoint | 인증 | 호출 | 설명 |
| :----- | :------- | :--: | :--- | :--- |
| GET | `/api/v1/market/indices` | 불필요 | 터미널 | backend 캐시의 ETF 5종 스냅샷. 필드는 4.4 와 같습니다. 첫 조회 전에는 `[]` |

```json
[ { "symbol": "SPY", "price": 543.21, "change_percent": 0.42, "trend": "up", "format": "index", "timestamp": 1730000000 },
  { "symbol": "VIXY", "price": 14.20, "change_percent": -1.10, "trend": "down", "format": "index", "timestamp": 1730000000 } ]
```

터미널은 화면을 열 때 이 엔드포인트로 한 번 받고, 이후 `/topic/market/indices` 로 갱신합니다. 빈 배열이면 자리 표시를
유지하다가 STOMP 메시지가 오면 그립니다.

### 7.8. 어닝콜 시연 재생 제어 (Demo Earnings Call)

| Method | Endpoint | 인증 | 호출 | 설명 |
| :----- | :------- | :--: | :--- | :--- |
| POST | `/api/v1/demo/earnings-call/start` | 필요 | 터미널 | 준비된 어닝콜 스크립트 재생 시작 |
| POST | `/api/v1/demo/earnings-call/stop` | 필요 | 터미널 | 재생 중지 |
| GET | `/api/v1/demo/earnings-call/status?ticker=` | 필요 | 없음 | 진행 상황 조회. `ticker` 필수 |
| GET | `/api/v1/demo/earnings-call/speakers` | 필요 | 터미널 | 콜 참가자 명부 |

- **설명:** 시연에서 data_pipeline 의 STT 를 준비된 스크립트가 대신합니다. 재생한 세그먼트는 실제 인입 경로
  (`TranscriptService` 검증 → 4.5)를 그대로 지나고, 같은 세그먼트로 팩트체크(9.1 → 4.6)와 직전 콜 대조(9.11 → 4.9)를
  요청합니다. 재생이 끝나면 종합 판단(4.7)을 만듭니다. 클라이언트가 가짜 데이터를 그리는 구조가 아닙니다.
- **요청 본문:** `{"ticker": "WMT"}`. start 에서 생략하면 스크립트의 기본 종목을 씁니다. stop 은 `ticker` 가 있어야
  하며, 없으면 진행 중인 재생을 찾지 못해 404 입니다.

| 상태 | 엔드포인트 | 의미 |
| :--- | :--- | :--- |
| 202 | start | 재생 시작(비동기). `{ticker, call_id, segment_count, interval_ms, evidence_warning?}` |
| 200 | stop | `{ticker, stopped: true}` |
| 404 | stop | 진행 중인 재생이 없음 |
| 409 | start | 해당 종목이 이미 재생 중. `{error, ticker, call_id}` |
| 500 | start · speakers | 스크립트 파일을 읽을 수 없음 |

```json
{ "ticker": "WMT", "call_id": "demo-wmt-q2fy27-1787227200000-1", "segment_count": 24, "interval_ms": 6000 }
```

- **`evidence_warning` 은 근거가 부족하다는 뜻입니다.** AI Engine 근거 준비 확인(9.8)의 문서 수가 최소 기준
  (`minimum_expected`, 20건) 미만이면 start 응답에 붙습니다. 재생은 그대로 진행되지만 팩트체크가 대부분
  `INSUFFICIENT_EVIDENCE` 로 나옵니다. 이 값을 사용자에게 보여 주지 않으면 "근거 없는 주장" 과 "근거를 넣지 않은
  것" 이 화면에서 구별되지 않습니다.

```json
{ "ticker": "WMT", "call_id": "...", "segment_count": 24, "interval_ms": 6000,
  "evidence_warning": "근거 뉴스가 0건뿐입니다. 팩트체크가 대부분 '근거 부족'으로 나옵니다. 시연 전 뉴스를 적재하세요." }
```
- **`call_id` 는 재생 회차마다 새로 만듭니다.** 같은 값을 다시 쓰면 `TranscriptSessionRegistry` 가 종료된 세션으로
  보고 세그먼트를 모두 거부합니다.
- **status 는 끝난 재생의 결과도 알려 줍니다.** 재생 중이면 `{running: true, ticker, call_id, published_count,
  total_segments}`, 끝났으면 `{running: false, ticker, last_run: {call_id, outcome, published_count, total_segments}}`,
  기록이 없으면 `{running: false, ticker}` 입니다. `outcome` 은 `COMPLETED` · `STOPPED` · `NO_SEGMENT_PUBLISHED` 이며,
  마지막은 세그먼트를 하나도 내보내지 못하고 끝난 경우입니다.
- **스크립트 교체 시 규칙.** 시작 시점에 검증하며, 어기면 500 `{"error": "<사유>"}` 로 거부합니다.
  1. `sequence` 는 0부터 1씩 늘어야 합니다. AI Engine 은 `call_id` 가 아니라 `ticker` 로 팩트체크 버퍼를 잡고
     `sentence_sequence=0` 에서만 비우므로, 0 에서 시작하지 않으면 중지 후 재시작 때 팩트체크만 조용히 사라집니다.
  2. `text` 는 비어 있을 수 없습니다.
  3. 세그먼트 수는 3의 배수를 권장합니다. AI Engine 이 3개 단위로 검증하므로 나머지 1~2개는 `DISCARDED` 되어 마지막
     발언의 팩트체크가 나오지 않습니다. 어겨도 시작은 되며 경고 로그가 남습니다.
  4. 과거 어닝콜이면 `call_started_at`(ISO-8601)을 채웁니다. 비우면 세그먼트 시각을 재생 시점의 현재 시각으로 찍는데,
     AI Engine 은 그 값을 기준으로 지난 30일을 근거 검색 창으로 잡습니다. 채우면 시각이 `call_started_at + start_ms`
     로 계산되어 검색 창이 그 콜 시점에 맞춰집니다. 형식이 틀리면 현재 시각으로 돌아가며 경고 로그가 남습니다.
  5. `related_tickers` 와 `analyst_qa` 는 종합 판단(4.7)에 쓰입니다. 앞의 것이 없으면 파급 영향이 비고, 뒤의 것이
     없으면 회피 지표가 빠집니다. `analyst_qa` 는 Q&A 에서 실제로 오간 질문 · 답변 한 쌍이어야 하며, `PLACEHOLDER` 로
     시작하는 문자열은 backend 가 걸러 냅니다.
  6. `speakers` 에는 트랜스크립트에서 확인되는 사실(이름 · 직책 · 소속 · 애널리스트 여부)만 적습니다. 화법 성향이나
     과거 가이던스 달성률처럼 원문에서 확인할 수 없는 값은 넣지 않습니다. 터미널은 이
     명부에 이번 회차에 실제로 받은 발언 수와 팩트체크 판정을 붙여 보여 줍니다. 비어 있으면 발화자 프로필 진입점이
     나타나지 않습니다. `speakers[].match_key` 는 세그먼트의 `speaker` 문자열과 정확히 같아야 합니다. 세그먼트 라벨은
     "CEO · John Furner" 처럼 직책이 붙고 이름은 "John Furner" 라서, 키가 없으면 클라이언트가 부분 일치를 추측해야
     하기 때문입니다. 비워 두면 `name` 을 키로 씁니다. 세그먼트에 발언이 없는 참가자는 발언 0건으로 표시됩니다.
- **speakers 응답.** 재생 중이 아니어도 조회됩니다. 명부가 없으면 `[]` 이고, 스크립트 파일을 읽지 못하면 500 입니다.
  빈 값은 `""` 로 옵니다.

```json
[ { "name": "John Furner", "match_key": "CEO · John Furner", "title": "CEO", "affiliation": "Walmart Inc.", "analyst": false },
  { "name": "Kate McShane", "match_key": "Kate McShane", "title": "Analyst", "affiliation": "Goldman Sachs", "analyst": true } ]
```

- **관련 설정:** `demo.earnings-call.script-path`, `demo.earnings-call.interval-ms`, `ai-engine.base-url`,
  `ai-engine.fact-check-enabled`, `ai-engine.timeout-ms`. `fact-check-enabled=false` 로 두면 AI Engine 없이 자막 재생만
  합니다.

### 7.9. 어닝콜 용어 사전 (Glossary)

| Method | Endpoint | 인증 | 호출 | 설명 |
| :----- | :------- | :--: | :--- | :--- |
| GET | `/api/v1/glossary` | 필요 | 터미널 | 어닝콜 용어 사전 전체 |

- **설명:** 어닝콜 영어의 금융 용어와 한국어 표기를 담은 사전입니다. 실시간 번역(#110)은 세그먼트에서 찾은 용어의
  `ko` 로 번역어를 고정하고, 용어 설명(#111)은 `definition_ko` · `why_ko` 를 팝오버에 보여 줍니다. 질의응답(10.3)도
  같은 사전으로 용어 질문에 답합니다.
- **사전은 backend 리소스(`data/glossary_ko.json`)입니다.** 기동할 때 한 번 읽어 끝까지 같은 값을 내려주므로,
  클라이언트는 로그인 직후 한 번만 조회하면 됩니다. AI Engine 가동 여부와 관계없이 응답합니다.
- **`ko` 는 번역문에 그대로 들어가는 표기입니다.** 설명을 괄호로 붙이면(예: "가이던스(실적 전망치)") 번역문에도
  매번 괄호째 들어가므로, 설명은 `definition_ko` 에 둡니다. 약어 병기("주당순이익(EPS)")처럼 번역문에 함께 보여야
  하는 것만 괄호를 씁니다.
- **`definition_ko` · `why_ko` 는 선택 필드이며 값이 없으면 키가 빠집니다.** 정의가 없는 용어는 번역 고정에만 쓰이고
  밑줄 대상이 아닙니다. 현재 사전(version 3)은 232개 용어 모두에 정의가 있습니다. version 3 은 S&P 500 어닝콜
  자막에서 여러 회사가 쓰는 공통 용어를 더한 것이며 한 회사만 쓰는 표현은 넣지 않습니다. 고른 방법은 `backend/tools/glossary-mining/README.md` 에
  있습니다. `definition_ko` 는 용어의 쉬운 뜻이고, `why_ko` 는 어닝콜에서 그 용어가 무엇을 알려 주는지 덧붙인 보충
  설명입니다. 특정 콜의 수치에 대한 판단은 넣지 않습니다.
- **`category`** 는 `accounting` · `capital` · `guidance` · `metric` · `market`(금리 · 신용 · 거시 환경) · `retail` ·
  `regulation` 중 하나입니다.

```json
{ "version": 3,
  "terms": [
    { "term": "comp sales", "aliases": ["comparable sales", "comps"], "ko": "기존점 매출", "category": "retail",
      "definition_ko": "1년 이상 운영된 점포만 집계한 매출 증가율입니다.", "why_ko": "신규 출점 효과를 뺀 실제 영업력을 보여줍니다." },
    { "term": "guidance", "aliases": [], "ko": "가이던스", "category": "guidance", "definition_ko": "...", "why_ko": "..." } ] }
```

- **사전 교체 시 규칙.** 기동 시점에 검증하며, 어기면 애플리케이션이 뜨지 않습니다. 빈 사전이나 잘못된 사전으로
  뜨면 번역이 용어 고정 없이 도는데, 화면만으로는 원인을 알 수 없기 때문입니다.
  1. `version` 은 1 이상, `terms` 는 1개 이상이어야 합니다.
  2. `term` · `ko` 는 비어 있을 수 없습니다.
  3. `term` 과 `aliases` 전체에서 같은 표기가 두 번 나올 수 없습니다(대소문자 · 앞뒤 공백 무시). 한 표기가 두 용어에
     걸리면 어느 번역어로 고정할지 정해지지 않습니다.
  4. 정의된 필드 외의 키는 거부합니다. `definiton_ko` 같은 오타가 조용히 버려지는 것을 막기 위해서입니다.
- **관련 설정:** `glossary.path` (기본 `data/glossary_ko.json`).

### 7.10. 어닝콜 질의응답 (Assistant)

| Method | Endpoint | 인증 | 호출 | 설명 |
| :----- | :------- | :--: | :--- | :--- |
| POST | `/api/v1/assistant/ask` | 필요 | 터미널 | 어닝콜 질문을 보내고 답을 SSE 로 받습니다 |

```json
{ "ticker": "WMT", "call_id": "demo-wmt-q2fy27-1787227200000-1", "as_of_sequence": 17,
  "anchor_sequence": 3, "question": "가이던스가 바뀌었어?", "suggested_question_id": null,
  "history": [ { "role": "user", "text": "..." }, { "role": "assistant", "text": "..." } ] }
```

- **요청.** `as_of_sequence` 는 터미널이 마지막으로 받은 세그먼트 번호입니다. backend 는 이 값을 저장된 마지막
  세그먼트 이하로 낮추고, 그 세그먼트의 발행 시각을 근거 시점으로 씁니다. `anchor_sequence` 는 사용자가 고른 대목이며
  없으면 `null` 입니다. 낮춘 `as_of_sequence` 보다 크면 오류 없이 버립니다. `suggested_question_id` 가 있으면 대목 지정은
  무시하고 콜 전체 범위로 답합니다.
- **필드 제한.** `ticker` 10자, `call_id` 200자, `question` 500자 이하입니다. `suggested_question_id` 는 `summary`,
  `vs_last_quarter`, `guidance`, `vs_expectations`, `risks` 중 하나입니다. `history` 는 6개(후속 질문 3회)까지이고 각
  `role` 은 `user` · `assistant`, `text` 는 4000자 이하입니다. 대화 기록은 터미널이 보관합니다.
- **Accept.** 성공은 `text/event-stream`, 실패는 JSON 이므로 `Accept: text/event-stream, application/json` 으로 보냅니다.
- **성공(200).** 이벤트는 10.6 과 같습니다(`meta` → `delta` → `citations` → `done`, 실패 시 `error`). backend 가 덧붙이는
  `error` 의 `code` 는 `assistant_unavailable`(질의응답 서비스 연결 실패), `assistant_stream_interrupted`(완료 이벤트
  없이 끊김), `timeout`(60초 초과)입니다.
- **실패.** 본문은 `{"error": "<메시지>", "code": "<code>"}` 입니다. 검증 오류 400 과 401 의 본문에는 `code` 가 없습니다.

| 상태 | code | 의미 |
|---|---|---|
| 400 | (검증 오류) / `ticker_mismatch` | 형식 · 길이 위반, 또는 콜과 종목 불일치 |
| 401 | | JWT 없음 · 만료 |
| 404 | `segments_not_found` | 이 콜의 저장된 자막이 없음 |
| 409 | `assistant_busy` | 같은 사용자의 이전 질문 답변이 진행 중 |
| 429 | `daily_limit_exceeded` | 하루 질문 수(기본 50, 한국 시간 자정 초기화) 초과. `reset_at` 에 다음 초기화 시각(UTC ISO-8601) |
| 503 | `assistant_overloaded` / `assistant_unavailable` | 중계가 가득 참 / 자막 · 한도 저장소(Redis) 장애 |

- 처리 순서는 요청 검증 → 질문 시점 확정(404 · 400) → 동시 질문 잠금(409) → 하루 횟수 차감(429) → 중계 시작입니다.
  404 · 400 · 409 는 횟수를 쓰지 않습니다. 차감한 뒤에는 답이 실패해도 돌려주지 않으며, 503 `assistant_overloaded` 도
  차감한 뒤 거절합니다.
- 사용자가 연결을 끊으면 backend 는 다음 전송 시점이나 2초마다 보내는 keep-alive 주석으로 몇 초 안에 알아채고
  질의응답 서비스 연결을 닫습니다. 질의응답 서비스는 진행 중인 생성을 멈춥니다.
- 스트림에는 2초마다 SSE 주석 줄(`:`)이 섞여 나오며 클라이언트는 무시합니다.
- **관련 설정:** `app.assistant.base-url`, `app.assistant.daily-limit`, `app.assistant.stream-timeout-seconds`.

### 7.11. 종목 (Stocks)

| Method | Endpoint | 인증 | 호출 | 설명 |
| :----- | :------- | :--: | :--- | :--- |
| GET | `/api/v1/stocks/sp500` | 불필요 | 터미널 | S&P 500 종목 목록 `[{ticker, companyName, sector, marketCapUsd, currentPrice, changePercent}]`. 뒤의 세 값은 `null` 일 수 있습니다 |
| GET | `/api/v1/stocks/prices` | 불필요 | 터미널 | backend 캐시의 종목 시세. 형식은 4.10 과 같습니다 |
| GET | `/api/v1/stocks/{ticker}/detail` | 필요 | 터미널 | 종목 상세 (아래) |

**`GET /api/v1/stocks/{ticker}/detail`** 은 `ticker` 가 `^[A-Z0-9.-]{1,10}$` 이어야 합니다. 키는 camelCase 입니다.

| 필드 | 설명 |
| :--- | :--- |
| `ticker`, `companyName`, `sector`, `active` | 종목 기본 정보 |
| `basic` | `{marketCapUsd, high52w, low52w, dividendYield}`. `null` 가능 |
| `chart30d` | `[{date, close, volume}]`. `date` 는 `YYYY-MM-DD` |
| `currentPrice` | 현재가 |
| `earningsHistory` | `[{fiscalPeriodLabel, announcedAt, epsEstimate, epsActual, surprisePercent, priceReactionPercent}]`. `announcedAt` 은 Unix Epoch Second |
| `nextEarning` | `{scheduledAt, epsEstimate, revenueEstimate, confirmed}`. `null` 가능 |
| `partial` | 일부 데이터를 가져오지 못했는지 여부 |
| `ai` | 자리만 있으며 늘 `null` |

| 상태 | 의미 |
|---|---|
| 200 | 성공 |
| 400 | `{"error": "invalid ticker"}` |
| 503 | `{"error": "stock detail unavailable — external sync failed"}` |
| 500 | `{"error": "internal error"}` |

### 7.12. 개발용 (Dev)

| Method | Endpoint | 인증 | 설명 |
| :----- | :------- | :--: | :--- |
| POST | `/api/v1/dev/sync-daily-bars` | 불필요 | 일봉 동기화를 바로 실행합니다. `local` 프로필에서만 등록됩니다. 200 `{"result": "triggered"}` |

---

## 8. 공통 규칙 (Common Rules)

### 8.1. 인증

- REST 는 `Authorization: Bearer {accessToken}` 입니다. access token 은 로그인 응답의 `access_token` 이며 수명은 15분입니다.
- access token 이 만료되면 `POST /api/v1/auth/refresh`(7.1)로 다시 받습니다. refresh token 은 HttpOnly 쿠키라
  클라이언트 코드가 직접 다루지 않습니다. 터미널은 응답의 `Set-Cookie` 에서 값을 꺼내 main 프로세스 메모리에 두고
  갱신할 때 `Cookie` 헤더로 보냅니다.
- STOMP 는 CONNECT 프레임의 `Authorization` 헤더로 보냅니다(4장 머리말).
- 인증 없이 열린 경로는 `/api/v1/auth/**`, `/api/v1/market/indices`, `/api/v1/stocks/sp500`, `/api/v1/stocks/prices`,
  `/ws/**`, `/ws-native/**`, `/actuator/health`, `/api/v1/dev/**` 입니다. `/api/v1/internal/**` 은 JWT 대신 8.3 의
  시크릿으로 검사합니다.

### 8.2. 요금제별 접근 제어

없습니다. 사용자에게 `role`(`FREE` · `PRO`) 필드는 있지만 모든 로그인 사용자가 같은 권한(`ROLE_USER`)을 받고, 역할을
바꾸는 경로도 없습니다. 예전 계약의 "`action` 신호와 Trading Terminal 은 PRO 전용" 규칙은 매매 신호 경로와 함께
없어졌습니다. 접근 제어를 넣게 되면 이 절에 규칙을 적습니다.

### 8.3. 내부 API 인증

- `/api/v1/internal/` 로 시작하는 경로는 `InternalSecretFilter` 가 `X-Internal-Secret` 헤더를 backend 의
  `INTERNAL_SECRET` 과 비교합니다. 호출하는 곳은 data_pipeline(6.4)과 logothea-assistant(10.1~10.3)입니다.
- 서버에 시크릿이 설정되지 않았으면 401 `{"error": "internal secret not configured"}`, 헤더가 다르면 401
  `{"error": "invalid internal secret"}` 입니다.
- 이 경로는 Cloudflare Tunnel 로 공개 호스트에서도 닿으므로, 보호는 이 헤더 하나입니다.

### 8.4. 오류 응답

- 기본 형식은 HTTP `4xx` · `5xx` 와 `{"error": "<원인>"}` 입니다(`GlobalExceptionHandler`). 다음 예외를 이 형식으로
  바꿉니다.
  - `IllegalArgumentException`: 400
  - 요청 필드 검증 실패: 400. 메시지는 첫 위반의 `"<필드>: <메시지>"` 이고 필드 이름은 Java 이름(camelCase)입니다.
  - 거래 상태 충돌: 409
  - 잠금 획득 실패: 503 과 `Retry-After: 1`
- 다음은 이 형식을 따르지 않습니다.
  - 본문 없는 오류: refresh 401 · 429, oauth/callback 400 · 401 · 500, portfolio/sync 409, asset-history 400
  - 텍스트 본문: earnings-calendar/sync 409
  - 필드가 더 붙는 오류: assistant 의 `code` · `reset_at`(7.10), 시연 start 409 의 `ticker` · `call_id`
  - 위 핸들러가 잡지 않는 예외(필수 쿼리 파라미터 누락, 잘못된 JSON · enum, 없는 리소스, 다른 사용자의 리소스 등):
    응답 형식이 정해져 있지 않습니다.
- **401 과 403 을 구분합니다.** 인증이 없거나 토큰이 만료 · 위조되면 401 `{"error": "인증이 필요합니다."}` 와
  `WWW-Authenticate: Bearer realm="api"` 입니다. 만료와 위조는 응답에서 구분하지 않습니다. 권한 부족(403,
  `{"error": "접근 권한이 없습니다."}`)은 핸들러만 있고 지금 403 이 나가는 경로는 없습니다(8.2). 클라이언트는 401
  에서만 refresh 로 갱신하고 원래 요청을 다시 보냅니다.

### 8.5. 시각 표기

- 기본은 UTC 기준 Unix Epoch Second 입니다. 클라이언트가 받은 뒤 사용자 시간대로 바꿔 보여 줍니다.
- 예외는 다음과 같습니다.

| 값 | 형식 |
|---|---|
| `/topic/prices` · `GET /api/v1/stocks/prices` 의 `updatedAt` | Unix Epoch 밀리초 |
| 4.5 · 6.4 의 `start_ms` · `end_ms` | 세그먼트 기준 밀리초 |
| `/topic/evaluation` 의 `generated_at`, 10.2 의 `scheduled_at` · `announced_at` | ISO-8601 문자열(UTC) |
| `GET /api/v1/trades` · `GET /api/v1/users/me` 의 `createdAt` | 시간대 없는 ISO 날짜시각 문자열 |
| `asset-history` 의 `date`, 종목 상세 `chart30d[].date` | `YYYY-MM-DD` |

### 8.6. 자산 상태의 기준

backend 는 KIS API 키를 갖지 않습니다. KIS 계좌의 최종 자산 상태는 터미널이 보내는 동기화(5.2) 값을 기준으로 덮어씁니다.
자체 페이퍼 계정(`SELF_PAPER`)은 KIS 를 거치지 않습니다. backend 에는 체결 보고(5.1) 때 보유 종목과 예수금을 직접
계산하는 경로가 있지만, 지금 터미널은 이 보고를 보내지 않습니다. 터미널이 앱 안에서 바로 가상 체결해 예수금과 보유
수량을 바꾸고, 결과를 `POST /api/v1/trades/manual` 에 `EXECUTED` · `broker_order_id: null` 로 기록하려 합니다. 이 기록은
`EXECUTED` 에 `broker_order_id` 가 필수라는 검증에 걸려 400 으로 거부되므로, backend 의 거래 내역과 보유 종목에는
남지 않습니다.
수동 기록 경로는 거래만 저장하고 보유 종목과 예수금은 바꾸지 않으므로, 검증을 통과하더라도 보유 종목에는 반영되지 않습니다.

### 8.7. 주문 주체

모든 주문은 사용자가 터미널에서 직접 입력한 수동 주문입니다. backend 의 룰 엔진과 터미널의 매매 모드는 #127 에서
제거했습니다.

---

## 9. [Contract 9] Backend ➔ AI Engine (팩트체크 · 직전 콜 대조 · 번역 · 종합 판단)

backend 는 `AiEngineClient` 로 아래 엔드포인트를 부릅니다. 호출 실패(타임아웃, 4xx, 5xx, 역직렬화 오류)는 모두 빈
결과로 처리하고 해당 발행만 건너뜁니다. 미리 만든 응답으로 대신하지 않습니다. 읽기 타임아웃은 `ai-engine.timeout-ms`
(기본 50초, 번역은 `ai-engine.translation-timeout-ms` 15초)입니다.

### 9.1. 실시간 팩트체크 요청 (`POST /v1/engine/live-fact-check/sentence`)

- **통신 방식:** HTTP POST(동기). backend 는 세션별 단일 스레드에서 비동기로 제출하므로 자막 발행을 막지 않습니다.
- **설명:** 시연 재생의 세그먼트를 하나씩 제출합니다. AI Engine 은 `ticker` 별로 3개 버퍼를 유지하다가 3개가 모이면
  검증 가능한 주장을 추출하고, 관련성 게이트를 통과한 근거가 있는 주장만 LLM 으로 대조해 판정합니다(LLM 호출 최대
  2번). backend 는 결과를 4.6 으로 보냅니다.
- 필드 이름은 "sentence" 지만 backend 는 세그먼트 원문 하나를 그대로 보냅니다. 엔진의 3개 버퍼도 세그먼트 3개입니다.
- 다른 엔드포인트 `/v1/engine/fact-check` 는 LLM 을 쓰지 않는 단발 유사도 검증이라 숫자 모순을 잡지 못합니다. 비교는
  `ai-engine/docs/LIVE_FACT_CHECK_API.md` 에 있습니다.

| 필드명               | 타입    | 필수 | 설명                                                              |
| :------------------- | :------ | :--: | :---------------------------------------------------------------- |
| `ticker`             | String  |  Y   | 종목 심볼. 공백을 지우고 대문자로 맞춥니다                        |
| `sentence`           | String  |  Y   | 세그먼트 원문. 공백 제거 후 1자 이상                              |
| `sentence_sequence`  | Integer |  Y   | 세션 내 순번(0 이상, 증가). `0` 을 보내면 버퍼를 비웁니다         |
| `sentence_timestamp` | Long    |  Y   | Unix Epoch Second, 0 보다 큼. 근거 검색 기준 시점 (9.4)           |
| `is_session_end`     | Boolean |  N   | 어닝콜 세션 종료 여부 (기본 `false`)                              |

### 9.2. 응답

HTTP 상태는 정상 흐름 전체가 200 이고, 요청 형식 위반만 422 입니다. 호출자는 본문 `status` 로 분기합니다.

| `status`    | 발생 조건                                  | backend 처리             |
| :---------- | :----------------------------------------- | :----------------------- |
| `BUFFERING` | 버퍼에 1~2개                               | 발행 없음                |
| `COMPLETED` | 3개가 모여 검증을 마침                     | `claims[]` 가 있으면 4.6 |
| `REJECTED`  | 중복 · 역행 순번                           | 로그만. 다시 보내지 않음 |
| `DISCARDED` | 3개가 차지 않은 채 세션 종료               | 남은 세그먼트 폐기       |

| 필드명                  | 타입    | 설명                                                                 |
| :---------------------- | :------ | :------------------------------------------------------------------- |
| `ticker`                | String  | 대문자 종목 심볼                                                     |
| `status`                | String  | 위 4종                                                               |
| `buffered_count`        | Integer | 버퍼에 남은 수 (0~2)                                                 |
| `batch_start_sequence`  | Integer | 이번 묶음의 시작 순번. `BUFFERING` · `REJECTED` 이면 `null`          |
| `batch_end_sequence`    | Integer | 이번 묶음의 끝 순번. `BUFFERING` · `REJECTED` 이면 `null`            |
| `claims`                | Array   | 판정한 주장 목록 (9.3)                                               |
| `excluded_count`        | Integer | 검증할 수 없어 걸러진 주장 수 (수사적 표현 등)                       |
| `extraction_llm_used`   | Boolean | 주장 추출 LLM 실행 여부                                              |
| `verification_llm_used` | Boolean | 근거 대조 LLM 실행 여부. `false` 면 근거 부족으로 생략됨             |
| `warnings`              | Array   | 진단 코드 (아래)                                                     |
| `generated_at`          | String  | 응답 생성 시각 (ISO-8601 UTC)                                        |

`warnings` 값은 `buffer_expired`(버퍼 TTL `FACT_CHECK_SENTENCE_BUFFER_TTL_SECONDS`, 기본 900초 경과),
`buffer_reset_on_sequence_zero`, `duplicate_or_regressed_sequence`, `sequence_gap`, `partial_batch_discarded`,
`claim_extraction_failed`(이때도 `status=COMPLETED`, `claims` 는 빈 배열), `invalid_or_duplicate_claims_discarded`,
`claim_retrieval_failed`, `claim_verification_failed`, `invalid_or_missing_claim_verdicts` 입니다.

### 9.3. `claims[]` 항목

| 필드명            | 타입    | 설명                                                                    |
| :---------------- | :------ | :---------------------------------------------------------------------- |
| `claim_id`        | String  | `{TICKER}:{시작seq}-{끝seq}:c{n}` 형식                                  |
| `sentence_index`  | Integer | 묶음 안의 위치 (0~2)                                                    |
| `source_text`     | String  | 원문에서 잘라낸 구간                                                    |
| `claim`           | String  | 정규화한 주장                                                           |
| `claim_type`      | String  | `numeric_fact` / `current_fact` / `historical_fact` / `event_fact`      |
| `verdict`         | String  | `SUPPORTED` / `CONTRADICTED` / `INSUFFICIENT_EVIDENCE`                  |
| `confidence`      | Double  | 0.0 ~ 1.0                                                               |
| `explanation_ko`  | String  | 한국어 판정 설명. 클라이언트에 그대로 보여 줍니다                       |
| `reason_code`     | String  | `supported_by_news` / `contradicted_by_news` / `insufficient_relevance` / `evidence_not_specific` / `retrieval_failed` / `llm_failed` / `invalid_llm_response` |
| `evidence`        | Array   | `doc_id`, `title`, `snippet`(최대 600자), `url`, `source`, `published_at`(Unix Epoch Second), `relevance_score` |
| `retrieved_count` | Integer | 검색된 근거 수                                                          |
| `accepted_count`  | Integer | 관련성 게이트를 통과한 근거 수                                          |

`evidence[].source` 는 적재 때의 `source` · `publisher` · `provider` 순서로 찾고, 없으면 URL 호스트 이름을 씁니다.

### 9.4. 통합 시 주의사항

1. **`sentence_timestamp` 는 콜 시점 기준 시각입니다.** 근거 검색이 이 값에서 과거 N일을 조회하므로, 콜과 동떨어진
   값을 넣으면 근거가 적재되어 있어도 검색 결과가 0건이 되어 전부 `INSUFFICIENT_EVIDENCE` 가 됩니다. backend 시연
   재생은 `call_started_at + start_ms` 를 보내고, `call_started_at` 이 없을 때만 현재 시각을 씁니다(7.8 규칙 4).
2. **근거는 미리 적재해야 합니다.** 검증할 종목의 뉴스를 2.2 로 넣어 둡니다. 관련성 게이트는 강한 관련도(strong)를
   넘는 문서가 하나라도 있으면 통과하고, 없으면 중간 관련도(moderate) 문서가 서로 다른 매체 2곳 이상이어야 합니다.
   채택하는 근거는 최대 3건입니다.
3. **저장소.** `VECTOR_STORE_BACKEND=qdrant`(`.env.example` 과 시연 서버)이면 근거가 Qdrant 에 남습니다. 코드 기본값
   `memory` 로 띄우면 AI Engine 을 다시 시작할 때 근거가 사라집니다.
4. **자막을 막지 않습니다.** 한 묶음 처리에 LLM 호출로 수 초가 걸리므로 backend 는 비동기로 제출하고 결과가 오는
   대로 보냅니다.

### 9.5. 클라이언트 표기 규칙

판정값은 AI Engine 의 3종을 기준으로 삼고, 화면 표기는 아래로 통일합니다.

| `verdict`               | 화면 표기   |
| :---------------------- | :---------- |
| `SUPPORTED`             | 사실 확인   |
| `CONTRADICTED`          | 사실과 다름 |
| `INSUFFICIENT_EVIDENCE` | 근거 부족   |

### 9.6. 종합 판단 (`POST /v1/engine/analyze`)

어닝콜 전문을 한 번에 넘겨 LLM 판단을 받습니다. 판단 본문이 만들어지는 유일한 엔드포인트입니다.

**요청**

| 필드명         | 타입    | 필수 | 설명                                                                |
| :------------- | :------ | :--: | :------------------------------------------------------------------ |
| `ticker`       | String  |  N   | 종목 심볼. 없으면 `"UNKNOWN"`                                       |
| `prompt`       | String  |  Y   | 어닝콜 전문(모든 세그먼트를 이어 붙인 것). `current_chunk` 와 같음 |
| `needs_review` | Boolean |  N   | 리뷰 모델까지 거칠지. 회차당 한 번이라 backend 는 늘 `true`        |
| `market_data`  | Object  |  N   | `current_price`, `prev_close`. 없으면 손절 계획이 빠집니다          |

backend 는 `market_data` 에 `symbol` 도 넣지만 AI Engine 모델의 필드 이름은 `ticker` 라서 이 값은 쓰이지 않습니다.

**응답 (화면이 쓰는 필드)**

- `analysis`: `direction`(BULLISH/BEARISH/NEUTRAL), `magnitude`(0~1), `confidence`(0~1), `catalyst_type`, `rationale`(영문),
  `risk_flags[]`, `hold_days`, `model_version`, `review_triggered`
- `signal_brief`: `action`, `gate_result`, `decision_state`, `institutional_grade`(A~E), `institutional_grade_score`,
  `institutional_approval_state`, `position_intent_ko`, `no_trade_summary_ko`, `risk_flags_ko[]`, `counter_thesis_ko`,
  `recommended_hold_days`

응답에는 이 밖에도 필드가 많습니다. backend 모델은 모르는 필드를 무시하도록 선언해 두어(`@JsonIgnoreProperties(ignoreUnknown = true)`)
엔진이 필드를 늘려도 깨지지 않습니다.

리뷰 모델 기본값은 `gemini-3.6-flash` 입니다. 무료 등급 Gemini 키는 pro 계열 할당량이 0이라, pro 모델을 지정하면
매번 429 로 실패하고 엔진은 `confidence: 0.0` 의 대체 응답을 돌려줍니다. 화면에는 늘 NEUTRAL 만 보이게 됩니다. 2026-10 기준 무료
키로 쓸 수 있는 모델은 `gemini-3.6-flash`, `gemini-3-flash-preview`, `gemini-3.1-flash-lite` 입니다.

### 9.7. 회피 · 파급 · 손절 (`POST /v1/engine/earnings/intelligence`)

LLM 을 쓰지 않는 규칙 기반 엔드포인트입니다. 근거 검색을 하므로 임베딩 호출은 생길 수 있습니다. 응답의
`fact_checks` 는 9.1 의 LLM 검증이 아니라 예전 휴리스틱이므로 화면에 쓰지 않습니다.

**요청**

| 필드명               | 타입    | 필수 | 설명                                                    |
| :------------------- | :------ | :--: | :------------------------------------------------------ |
| `ticker`             | String  |  Y   | 종목 심볼                                               |
| `event_text`         | String  |  Y   | 어닝콜 전문                                             |
| `question`           | String  |  N   | 애널리스트 질문. 없으면 회피 지표가 의미를 잃습니다     |
| `answer`             | String  |  N   | 그 질문에 대한 경영진 답변                              |
| `related_tickers`    | Array   |  N   | 연쇄 영향을 볼 종목                                     |
| `market_data`        | Object  |  N   | `current_price` 만 있어도 손절 계획을 계산합니다        |
| `direction_hint`     | String  |  N   | 9.6 의 `direction`. 손절 계획의 LONG/SHORT 를 정합니다  |
| `confidence_hint`    | Number  |  N   | 9.6 의 `confidence` (0~1)                               |
| `external_documents` | Array   |  N   | 검색 대신 쓸 근거 문서. backend 는 보내지 않습니다      |
| `top_k`              | Integer |  N   | 근거 검색 개수 (1~12, 기본 5)                           |

**응답 (화면이 쓰는 필드)**

- `omission_evasion`: `evasion_score`(0~1, 높을수록 회피), `directness`, `omission_score`, `pivot_detected`,
  `missing_topics[]`, `rationale_ko`
- `impact_chain[]`: `ticker`, `relationship`, `direction`, `impact_score`, `confidence`, `rationale_ko`
- `risk_plan`: `available`, `direction`, `reference_price`, `stop_loss`, `take_profit_1/2`, `stop_pct`,
  `take_profit_1/2_pct`, `risk_reward_1`, `time_stop_days`, `invalidation_text`, `sizing_note_ko`
- `warnings[]`: 영어 문장 (예: `"RAG evidence is empty; ..."`)

- **`related_tickers` 를 함께 보냅니다.** AI Engine 의 정적 관계 그래프에는 NVDA, MSFT, META, TSLA, AAPL 다섯 종목의
  관계만 있습니다. 시연 종목이 여기 없으면 `impact_chain` 이 빈 배열이 되며, 요청에 실어 보내면 그래프를 고치지 않고도
  잡힙니다.
- **근거 검색의 기준 시각은 현재 시각입니다.** 검색 창은 지금부터 지난 30일이라, 과거 콜을 재생하면 그 콜 시점의
  뉴스가 창 밖이어서 근거가 비고 `impact_score` 가 `null` 이 될 수 있습니다.
- **`impact_score` 는 `null` 일 수 있습니다.** 이 값은 그 종목이 이번 콜의 근거 문서에 함께 나오는 비율(함께 언급된
  문서 수 ÷ 전체 근거 문서 수)입니다. 근거 문서가 없으면 0.0 이 아니라 `null` 이 옵니다. "영향 없음" 과 "측정하지
  못함" 을 구분하기 위해서입니다. `confidence` 는 근거 문서 수를 20건 기준으로 환산한 값입니다.
- **`risk_plan.available=false` 이면 나머지 필드는 모두 `null` 입니다.** 가격 정보가 없거나 방향이 서지 않았다는
  뜻이므로, 화면에서 0으로 채우지 않고 `invalidation_text` 의 사유를 보여 줍니다.

### 9.8. 근거 준비 확인 (`GET /v1/engine/evidence/readiness`)

근거 저장소에 해당 종목 근거가 몇 건 있는지 셉니다. 임베딩 호출 없이 개수만 세므로 빨라서, backend 는 시연 재생
시작 경로에서 동기로 부릅니다.

| 쿼리 파라미터   | 필수 | 설명                                                                   |
| :-------------- | :--: | :--------------------------------------------------------------------- |
| `ticker`        |  Y   | 종목 심볼                                                              |
| `as_of`         |  N   | 기준 시각(Unix Epoch Second). 과거 콜을 재생하면 그 콜의 시각. 없으면 현재 |
| `lookback_days` |  N   | 검색 창 길이(1 이상). 없으면 `FACT_CHECK_NEWS_LOOKBACK_DAYS`           |

응답: `ticker`, `document_count`, `lookback_days`, `as_of_epoch`, `ready`, `minimum_expected`(20)

```json
{ "ticker": "WMT", "document_count": 391, "lookback_days": 30, "as_of_epoch": 1787230800, "ready": true, "minimum_expected": 20 }
```

- 근거를 하나도 넣지 않은 채로 재생하면 화면에는 "근거 부족" 판정만 이어집니다. 정말 근거 없는 주장을 검증한 결과와
  근거 적재를 잊은 것이 똑같이 보이므로, backend 는 재생 시작 전에 이 값을 확인해 7.8 의 `evidence_warning` 으로
  알립니다.
- 과거 콜을 재생하면서 `as_of` 를 빼면 그 콜 시점의 뉴스가 검색 창 밖이라 `document_count` 가 0 으로 나옵니다.
  backend 는 `as_of` 만 보내고 `lookback_days` 는 보내지 않습니다.
- `document_count` 는 `as_of - lookback_days` 이후의 근거를 셉니다. `as_of` 이후 발행분도 포함되며, 기사 수가 아니라
  저장 단위(청크) 수입니다.

### 9.9. 임베딩 설정 주의

근거 검색 품질은 `EMBEDDING_PROVIDER` 에 달려 있습니다. 코드 기본값 `hash` 는 단어 겹침 기반이라 의미 검색이 아니며,
이 상태로는 뉴스를 넣어도 관련도가 임계값을 넘지 못해 대부분 `INSUFFICIENT_EVIDENCE` 가 됩니다. `.env.example` 은
`gemini`(`gemini-embedding-001`, 768차원)를 씁니다. 무료 등급 키로 동작하며, 실측에서 한 번에 보내는 배치는
20건까지 통과했고 100건은 429 였습니다.

관련도 임계값은 임베딩 모델에 따라 달라집니다. Gemini 임베딩은 무관한 문서도 유사도가 0.48 정도로 높게 나왔습니다(실측).
코드 기본값 0.42 / 0.34 는 해시 임베딩 기준이라, `.env.example` 은 `FACT_CHECK_STRONG_RELEVANCE_SCORE=0.78`,
`FACT_CHECK_MODERATE_RELEVANCE_SCORE=0.70` 으로 다시 맞춰 두었습니다. 모델을 바꾸면 실제 근거로 다시 맞춥니다.

### 9.10. 세그먼트 한국어 번역 (`POST /v1/engine/transcript/translate`)

어닝콜 원문을 한국어로 번역합니다(#110). backend 는 세그먼트 몇 개를 묶어 한 번에 보냅니다(아래 "backend 호출 방식").
용어 사전은 backend(7.9)에 있고, 엔진은 요청에 실려 온 용어만 번역어로 고정합니다. backend 는 묶음 원문에서 찾은
용어만 `terms` 에 담습니다. 사전 전체를 보내지 않으므로 사전이 커져도 프롬프트 크기와 지연이 늘지 않습니다.

| 필드       | 필수 | 설명                                                                     |
| :--------- | :--: | :----------------------------------------------------------------------- |
| `ticker`   |  Y   | 종목 심볼 (16자 이하)                                                    |
| `call_id`  |  N   | 어닝콜 세션 식별자 (로그용)                                              |
| `sequence` |  Y   | 세그먼트 번호(묶음이면 첫 세그먼트). 응답에 그대로 돌려줍니다           |
| `text`     |  Y   | 세그먼트 원문, 묶음이면 이어 붙인 원문 (앞뒤 공백 제거 후 1~4000자)     |
| `terms`    |  N   | 고정할 용어 `[{ "term", "ko" }]`(각 120자 이하), 최대 50개. 비면 일반 번역 |

```json
// 요청
{ "ticker": "WMT", "call_id": "demo-wmt-q2fy27-1", "sequence": 3,
  "text": "Comp sales for Walmart U.S. were 2.6%, led by transactions.",
  "terms": [ { "term": "comp sales", "ko": "기존점 매출" }, { "term": "transactions", "ko": "거래 건수" } ] }
// 200 응답
{ "available": true, "sequence": 3,
  "text_ko": "Walmart U.S.의 기존점 매출은 거래 건수 증가에 힘입어 2.6%를 기록했습니다.",
  "terms_used": ["comp sales", "transactions"], "warnings": [] }
```

- **번역 실패도 HTTP 200 입니다.** 실패는 `available=false` 와 `warnings` 로 알립니다. 요청 형식이 틀리면(빈 `text`,
  공백뿐인 `term` · `ko` 등) 422 입니다. 실패하면 `text_ko` 는 `null` 이며 원문을 대신 넣지 않습니다. 호출자는
  `available` 로 분기합니다.

| `warnings` 값                   | `available` | 의미                                                                 |
| :------------------------------ | :---------: | :------------------------------------------------------------------- |
| `translation_llm_timeout`       |    false    | 6초 안에 끝나지 않음                                                 |
| `translation_llm_failed`        |    false    | LLM 호출 실패. 429 할당량 초과 · 503 과부하 · API 키 누락이 모두 여기 |
| `translation_invalid_response`  |    false    | 응답에 `text_ko` 가 없거나 형식이 틀림                               |
| `translation_not_korean`        |    false    | 번역문 글자 중 한글 비율이 30% 미만. 원문을 그대로나 일부만 옮긴 경우 |
| `translation_internal_error`    |    false    | 엔진 내부 오류. 엔진 로그에 스택이 남습니다                          |
| `translation_terms_not_applied` |    true     | 번역은 됐지만 `terms` 일부의 번역어가 번역문에 없음. 번역문은 씁니다 |

- **`terms_used` 는 코드가 판정합니다.** `terms` 중 `ko` 가 번역문에 실제로 들어간 용어만 담으며 LLM 의 자기 보고를
  쓰지 않습니다. 긴 번역어부터 찾으므로 "기존점 매출" 만 쓰인 번역문에서 "매출" 이 함께 잡히지 않습니다.
- **실패한 세그먼트는 다시 요청하면 다시 호출됩니다.** 엔진의 Gemini 응답 캐시는 호출 실패 때의 대체 응답도
  저장하는데, 번역 경로는 그 항목을 지웁니다. 성공한 번역은 캐시에 남아 같은 세그먼트를 다시 재생하면 할당량을 쓰지
  않습니다.
- **타임아웃 뒤에도 Gemini 호출은 끝까지 진행됩니다.** 응답을 기다리지 않을 뿐 호출을 취소하지 않으므로 할당량을
  씁니다.
- **backend 호출 방식.** backend 는 세그먼트를 묶어(4.8 발행 시점) 원문을 공백으로 이어 붙여 `text` 로 보내고, 묶음의
  첫 `sequence` 를 `sequence` 로 씁니다. `terms` 의 `term` 은 원문에 나온 표기 그대로이며, 겹치는 용어는 긴 표기만
  담습니다.
- **할당량 주의.** 무료 등급 Gemini 는 모델별로 분당 15요청입니다(`gemini-3.1-flash-lite` 실측, 429
  `GenerateRequestsPerMinutePerProjectPerModel-FreeTier`). 번역은 팩트체크(9.1)와 같은 모델이라 할당량을 함께 씁니다.
  세그먼트마다 번역을 부르면 시연(6초 간격 24세그먼트) 기준 분당 약 10회가 더해져 팩트체크와 합쳐 한도를 넘으므로,
  backend 가 묶어 보냅니다.

### 9.11. 직전 콜 대조 (`POST /v1/engine/transcript/diff`)

이번 발언을 직전 어닝콜의 경영진 발언과 비교합니다. 시연 재생이 세그먼트마다 세션 전용 스레드에서 부르며, 결과를
4.9 로 보냅니다. `/api/v1/transcript/diff` 도 같은 처리입니다.

**요청**

| 필드명             | 타입   | 필수 | 설명                                                                         |
| :----------------- | :----- | :--: | :--------------------------------------------------------------------------- |
| `ticker`           | String |  Y   | 종목 심볼. 대문자로 맞춥니다                                                 |
| `current_chunk`    | String |  Y   | 이번 발언 원문. `text_chunk` 로도 받습니다                                   |
| `source_type`      | String |  N   | 기본 `EARNINGS_CALL`. `NEWS` · `SOCIAL` · `FILING` · `OTHER` · `UNKNOWN` 이면 대조하지 않고, 목록 밖의 값은 422 |
| `request_metadata` | Object |  N   | `timestamp`(Unix Epoch Second). 이 시각 이전의 가장 최근 녹취록을 직전 콜로 고릅니다. 없으면 현재 시각 기준 |

backend 는 `{ticker, current_chunk, source_type: "EARNINGS_CALL", request_metadata: {timestamp}}` 를 보내며, `timestamp`
는 팩트체크(9.1)와 같은 세그먼트 시각입니다.

**응답**

| 필드명              | 타입    | 설명                                                                 |
| :------------------ | :------ | :------------------------------------------------------------------- |
| `available`         | Boolean | 대조할 수 있었는지                                                   |
| `ticker`            | String  | 종목 심볼                                                            |
| `previous_document` | Object  | 직전 콜 `{document_id, title, published_at, fiscal_quarter, source_url}`. 없으면 `null` |
| `items`             | Array   | 대조 항목, 최대 3개 (아래)                                           |
| `warnings`          | Array   | 진단 코드 (아래)                                                     |

`items[]`

| 필드명          | 타입   | 설명                                                                    |
| :-------------- | :----- | :---------------------------------------------------------------------- |
| `topic`         | String | 주제 (48자 이하)                                                        |
| `change_type`   | String | `improved` / `weakened` / `unchanged` / `mixed` / `new_claim`. 목록 밖의 값은 `mixed` |
| `summary_ko`    | String | 한국어 요약 (320자 이하)                                                |
| `current_claim` | String | 이번 발언의 주장 (320자 이하)                                           |
| `prior_claim`   | String | 직전 콜의 대응 발언. 핵심 문장 경로는 원문 문장 최대 2개를 ` … ` 로 이은 것, 청크 경로는 320자 이하 |
| `confidence`    | Double | 0~1                                                                     |
| `risk_score`    | Double | 0~1                                                                     |
| `evidence`      | Array  | `document_id`, `source`, `title`, `published_at`, `source_url`, `snippet`, `relevance_score`, `confidence_score` |

- 모든 실패가 HTTP 200 이고, 요청 형식 위반만 422 입니다.
- **직전 콜 핵심 문장이 있으면** 적재 때(2.3) 골라 둔 경영진 문장 중 관련 문장을 LLM 이 골라 대조합니다.
  `prior_claim` 은 저장된 원문 문장을 그대로 이은 것이고, `new_claim` 항목은 버립니다. 이 경로의 `evidence` 는
  `relevance_score` · `confidence_score` 가 `null` 이고 `statement_id`, `speaker`, `statement_topic` 이 더해집니다(backend
  는 이 세 필드를 버립니다). LLM 이 실패하면 항목을 만들지 않습니다(타임아웃 15초).
- **핵심 문장이 없으면** 직전 콜 녹취록 청크를 검색해 대조합니다. 이 경로는 LLM 이 실패하거나 결과가 비면 규칙으로
  만든 대체 항목을 채웁니다.

| `warnings` 값 | 의미 |
|---|---|
| `transcript_diff_not_applicable` | `source_type` 이 `EARNINGS_CALL` 이 아님. `available=false` |
| `transcript_repository_not_configured` | 저장소가 직전 콜 조회를 지원하지 않음(`memory` 백엔드). `available=false` |
| `previous_transcript_not_found` | 직전 콜 없음. `available=false` |
| `no_related_prior_statement`, `no_comparable_prior_statement` | 핵심 문장 중 대조할 문장이 없음 |
| `key_statements_not_found`, `key_statements_lookup_failed` | 핵심 문장이 없거나 조회 실패. 청크 검색으로 넘어갑니다 |
| `current_chunk_not_material` | 이번 발언이 짧거나 대조할 주제어가 없음. `available=true`, 항목 없음 |
| `weak_prior_transcript_evidence` | 관련도 기준을 넘는 직전 콜 근거가 없음 |
| `historical_transcript_diff_llm_failed` | 대조 LLM 실패. `warnings` 의 다음 원소에 사유 문자열이 들어갑니다 |
| `historical_transcript_diff_empty` | 청크 경로에서 LLM 결과가 비어 대체 항목을 씀 |
| `historical_transcript_diff_items_dropped:N`, `historical_transcript_diff_current_claim_replaced:N` | 핵심 문장 경로에서 문장 번호가 틀리거나 `new_claim` 인 항목을 버린 수, 이번 주장을 원문으로 바꾼 수 |

backend 는 호출 실패를 빈 결과로 처리하고, `available=false` 이면 경고 로그만 남기며, `items` 가 비면 발행하지 않습니다.

---

## 10. [Contract 10] 질의응답 근거 조회 (logothea-assistant ➔ Backend · AI Engine)

어닝콜 질의응답 서비스(logothea-assistant, #112)가 답변 근거를 읽는 내부 계약입니다. ai-engine 은 `127.0.0.1` 에만
바인딩되어 같은 호스트에서만 닿습니다. backend 의 `/api/v1/internal/assistant/**` 는 Cloudflare Tunnel 이 `api.logothea.com` 전체를 backend 로
넘기므로 공개 호스트에서도 닿는 경로이고, `X-Internal-Secret`(8.3)으로 보호합니다. 근거 시점(`as_of`)은 backend 가 정해 넘기며, 아래 API 는 그 시점 이후의
정보를 돌려주지 않습니다. 10.6 은 반대 방향으로 backend 가 logothea-assistant 에 질문을 넘기는 계약입니다.

### 10.1. 콜 세그먼트 (`GET /api/v1/internal/assistant/calls/{callId}/segments?until_sequence=`)

- 인증: `X-Internal-Secret` (8.3)
- backend 는 4.5 로 발행한 세그먼트만 콜 단위로 Redis 에 보관합니다(`transcript:segments:{callId}`,
  `app.assistant.segment-ttl-hours`, 기본 48시간, 추가할 때마다 갱신). 보관은 비동기(단일 스레드, 대기열 1000건)라
  보관 실패가 자막 발행에 영향을 주지 않으며, Redis 장애 중에는 일부 세그먼트가 빠질 수 있습니다.

```json
{
  "call_id": "demo-wmt-q2fy27-1787227200000-1",
  "until_sequence": 17,
  "last_sequence": 17,
  "segments": [
    { "sequence": 3, "start_ms": 18000, "end_ms": 23000, "speaker": "CEO · John Furner", "text": "Comp sales for Walmart U.S. were 2.6%...", "timestamp": 1787227218 }
  ]
}
```

- `until_sequence` 는 필수이고 음수면 `400 {"error": "..."}` 입니다. 그 값 이하만 돌려줍니다. 저장된 마지막이 더 작으면
  그만큼만 돌려주고 `last_sequence` 로 알립니다.
- `until_sequence` 이하의 저장된 세그먼트가 없으면 `404 {"error": "..."}` 입니다.

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

- `recent_results` 는 저장된 결과 중 가장 최근 4건을 먼저 고른 뒤, 그중 `as_of` 하루 뒤까지 발표된 것만 남깁니다(실적
  발표문은 콜 당일 콜보다 먼저 나옵니다). 그래서 `as_of` 뒤에 발표된 결과가 저장되어 있으면 4건보다 적게 나옵니다.
- `price_reaction_percent` 는 발표 후 7일 종가까지 반영한 값이라, `announced_at` + 7일이 `as_of` 보다 뒤인 결과는
  `null` 입니다.
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

- `published_at <= as_of_epoch` 이고 `as_of_epoch - lookback_days` 이후인 기사만 돌려줍니다. `lookback_days` 는 1~365
  (기본 30), `top_k` 는 1~20(기본 6)입니다. 기존 `/v1/engine/evidence/search` 는 시점 상한이 없어 질의응답에 쓰지 않습니다.
- 검색에 실패하면(임베딩 한도 등) `200` 에 `hits: []`, `warnings: ["news_search_failed"]` 입니다.
- 요청 검증에 실패하면(`top_k` · `lookback_days` 범위, 빈 `query`, 0 이하 `as_of_epoch` 등) `422` 입니다.

### 10.5. 직전 콜 원문 문장 (`GET /v1/engine/assistant/prior-call-statements?ticker=&before_epoch=`)

```json
{ "available": true, "ticker": "WMT", "document_id": "investing:WMT:...", "fiscal_quarter": "Q1 FY2027", "published_at_epoch": 1779000000,
  "statements": [ { "statement_id": "...", "order": 1, "topic": "guidance", "speaker": "John David Rainey", "text": "We are reiterating our full year guidance..." } ],
  "warnings": [] }
```

- `before_epoch` 이전에 발행된 가장 최근 콜의 핵심 문장(#145, 원문 그대로)을 순서대로 돌려줍니다.
- 직전 콜이 없으면 `available: false`, `warnings: ["prior_call_not_found"]` 입니다. 콜은 있지만 핵심 문장이 없으면
  `available: true`, `statements: []`, `warnings: ["key_statements_not_found"]` 입니다.
- 저장소가 직전 콜 조회를 지원하지 않으면(`memory` 백엔드) `available: false`, `warnings: ["prior_call_lookup_unsupported"]`,
  조회 중 예외가 나면 `200` 에 `available: false`, `warnings: ["prior_call_lookup_failed"]` 입니다.
- 요청 검증에 실패하면(`ticker` 누락, 0 이하 `before_epoch` 등) `422` 입니다.

### 10.6. 질의응답 요청 (`POST /v1/assistant/ask`, Backend ➔ logothea-assistant)

- logothea-assistant 는 `127.0.0.1:8100` 에만 바인딩되며, `X-Internal-Secret` 이 backend 의 `INTERNAL_SECRET` 과 같아야
  합니다. 다르면 `401`, 본문 검증에 실패하면 `422` 입니다. assistant 쪽 값이 비어 있으면 서비스가 뜨지 않습니다.
- 본문은 외부 요청(7.10)에 backend 가 정한 `user_id`, `as_of_sequence`, `as_of_epoch`, `call_ended` 를 더한 것입니다.

```json
{ "user_id": "42", "ticker": "WMT", "call_id": "demo-wmt-q2fy27-1787227200000-1",
  "as_of_sequence": 17, "as_of_epoch": 1787227218, "anchor_sequence": 3, "call_ended": false,
  "question": "가이던스가 바뀌었어?", "suggested_question_id": null,
  "history": [ { "role": "user", "text": "..." }, { "role": "assistant", "text": "..." } ] }
```

- `call_ended` 는 질문 시점의 마지막 세그먼트가 콜 종료 신호인지이며, backend 가 정합니다.
- `question` 은 앞뒤 공백을 뺀 1~500자, `history` 는 최대 6개(후속 질문 3회), `anchor_sequence` 는 `as_of_sequence`
  이하입니다. `suggested_question_id` 는 `summary`, `vs_last_quarter`, `guidance`, `vs_expectations`, `risks` 중 하나이며,
  값이 있으면 질문 분류를 건너뜁니다.
- 응답은 `text/event-stream` 입니다. 생성하는 답은 `meta` → `delta`(여러 번) → `citations` → `done` 순서이고, 거절과 용어
  사전 답은 `citations` 없이 `meta` → `delta` → `done` 입니다. 실패하면 그 자리에서 `error` 를 보내고 끝납니다. 이미 보낸
  `delta` 는 거두지 않습니다.

| 이벤트 | 데이터 |
|---|---|
| `meta` | `{scope: "anchor"\|"call", as_of_sequence, as_of_time, anchor_sequence, missing_sources[]}`. `as_of_sequence` 는 생성한 답에서는 실제로 근거에 쓴 마지막 세그먼트이고, 거절과 용어 사전 답에서는 요청 값입니다. `missing_sources` 는 `news`, `prior_call`, `estimates`, `segments_incomplete` 중 불러오지 못한 것입니다 |
| `delta` | `{text}`. 본문에 근거 표시 `[S12]`(세그먼트 sequence), `[N3]`(뉴스), `[P2]`(직전 콜 문장), `[E1]`(실적 추정치)가 들어 있습니다 |
| `citations` | `[{marker, type: "segment"\|"news"\|"prior_statement"\|"estimate"\|null, ref, title, source, published_at, start_ms, speaker, quote, verified}]`. 답에 처음 나온 순서입니다. 근거 목록에 없는 표시이거나 인용 문장의 수치가 원문과 맞지 않으면 `verified: false` 입니다 |
| `done` | `{status: "answered"\|"refused"\|"no_evidence", refusal_reason, suggested_question_ids[], warnings[], usage{input_tokens, output_tokens, cached_tokens}, latency_ms}` |
| `error` | `{code, message}`. `code` 는 `segments_not_found`, `context_unavailable`, `llm_timeout`, `llm_failed`, `llm_unparsable`, `internal` 입니다 |

- `refusal_reason` 은 `investment_advice`, `price_prediction`, `out_of_scope` 이며, `suggested_question_ids` 로 대신 볼 만한
  추천 질문을 알려 줍니다.
- `warnings` 는 `uncited_number`(근거 표시 없이 수치를 말한 문장), `number_mismatch`, `unknown_marker:<표시>` 입니다. 답변
  방식이 `agent`(`ANSWER_MODE=agent`)이면 도구 사용 상한(라운드 · 호출 수 · 시간)에 닿아 도구 없이 답을 마무리했을 때
  `agent_round_limit` 이 더해집니다.
- 뉴스 · 지난 분기 콜 · 실적 추정치는 정보원마다 3초 안에 오지 않으면 빼고 답합니다. 콜 세그먼트를 읽지 못하면
  `error` 로 끝납니다. OpenAI 호출은 1회 30초가 상한입니다.
- 연결이 끊기면 진행 중인 생성 호출도 닫습니다.
