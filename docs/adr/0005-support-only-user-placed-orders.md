# 0005. 매매는 사용자가 직접 낸 주문만 지원합니다

- 날짜: 2026-10-05
- 상태: 채택
- 결정한 사람: @keonha123
- 대체한 ADR: 없음
- 대체된 ADR: 없음

## 배경

ai-engine 이 Redis `trading-signals` 로 매매 신호를 발행하면 backend 가 구독해 룰을 평가하고, 매매 모드에 따라
PENDING 거래를 만들어 `/user/queue/signals` 로 터미널에 주문을 지시하는 경로가 있었습니다. 어닝콜은 장 마감 후
열리고 장외에는 이 경로로 매매하지 않는 방향으로 정리되면서, Trading Room 에서 신호 피드 패널을 뺐습니다.

경로 자체는 부르는 곳이 없어 휴면 상태였지만, `data_pipeline` STT 워커를 켜면 그대로 동작해, 신호를 받아 바로 실행하도록
설정한 사용자에게는 주문이 나갈 수 있었습니다(#127). #136 에서 막은 위조 신호 문제도 이 경로를 통해 실주문으로 이어질 수 있었습니다. 시연 경로는
이 경로를 쓰지 않았습니다.

## 결정

서버가 주문을 지시하는 경로를 모두 제거하고, 매매는 사용자가 Trading Room 에서 직접 낸 주문만 지원합니다.
backend 는 주문을 지시하지 않고 터미널이 보고한 결과만 기록합니다. #127 에서 2026-10-02 에 방향을 정했고
PR #142(머지 커밋 `22c8c1f`)로 반영했습니다.

- backend: Redis `trading-signals` 구독(`TradingSignalSubscriber`), 룰 엔진(`RuleEngine`, `SignalService`,
  `SignalHistory`), 주문 지시 전송(`TradeCommandPublisher`), `LiveSignalPublisher`(`/topic/live/{ticker}` 발행), `PortfolioSettings` 와
  `TradingMode` 를 지웠습니다. REST 에서는 `GET /api/v1/trades/pending`, `GET`·`PUT /api/v1/portfolio/settings`,
  `PUT /api/v1/users/settings` 를 지웠고, 주문 방향 `TradeAction` 에서 `HOLD` 를 빼 `BUY`·`SELL` 만 받습니다.
- trading-terminal: 신호 구독, 매매 모드 3단계와 모드 선택 UI, 승인 다이얼로그, 신호 피드, `TradeExecutor` 를
  지웠습니다. 직접 주문, 계좌 전환, KIS 자격증명은 그대로 남았습니다.
- DB: `trades.signal_id`·`order_ratio`·`ai_score`, `signal_history`, `portfolio_settings` 를 엔티티에서 지웠습니다.
  `ddl-auto` 가 지우지 않으므로 서버 DB 는 `infra/DEPLOY.md` 5-4 절차로 따로 정리합니다.
- 유지: 직접 주문 기록(`POST /api/v1/trades/manual`), 체결 콜백, PENDING 의 TTL 만료(`TRADE_MANUAL_PENDING_TTL_SECONDS`,
  기본 24시간)는 이 경로와 독립적이라 그대로 둡니다.

## 검토한 대안

### 그대로 둔다

부르는 곳이 없으니 아무것도 흐르지 않는 상태입니다. 다만 STT 워커를 켜면 주문이 생성될 수 있어 고르지
않았습니다.

### 화면과 구독만 제거한다

terminal 쪽 미사용 코드만 정리하는 방식입니다. backend 가 여전히 PENDING 거래를 만들기 때문에 고르지
않았습니다.

### 주문 생성만 빼고 신호 이력 저장은 남긴다 (범위를 넓혀 채택)

#127 본문의 세 번째 방향은 `TradingSignalSubscriber` 의 거래 생성만 빼고 신호 이력 저장을 남기는 것이었습니다.
#127 에서는 이 방향을 골랐지만, 반영하면서 매매 모드까지 함께 없애고 신호 이력 저장도 범위에 넣어 지웠습니다.
이력만 따로 남기지 않은 이유는 기록이 없습니다.

## 결과

좋아진 점

- 서버나 신호가 사용자 계좌로 주문을 내게 만드는 경로가 코드에서 사라졌습니다. 위조 신호가 실주문으로 이어질
  여지도 함께 없어졌습니다.
- 직접 주문 기록이 `side=HOLD` 를 받으면 SELF_PAPER 체결 반영에서 매도로 계산돼 예수금이 늘어나던 문제가
  `HOLD` 제거로 함께 해결되었습니다. 이제 400 으로 거부합니다.

감수한 비용

- 기존 REST·STOMP 계약 일부와 DB 컬럼·테이블이 사라져, 서버 배포 뒤 DB 를 수동으로 정리해야 합니다. 새 backend 를
  먼저 배포하고 정리해야 하며, 남는 컬럼은 모두 nullable 이라 그 사이에 시간이 떠도 동작에는 영향이 없습니다.

후속 조치

- ai-engine 의 `/api/v1/analyze` 와 Redis `trading-signals` 발행은 그대로 남아 있습니다. 받는 곳이 없어졌으므로
  발행을 멈출지는 별도로 논의합니다.
- `WebSocketConfig` 의 `/queue` 브로커와 `/user` prefix 는 보내는 곳이 없어졌습니다. 보안 설정 변경이라 별도
  PR 로 닫을 예정입니다([0001](0001-use-stomp-for-realtime-delivery.md) 후속 조치).
- `TRADE_EXECUTED`·`TRADE_FAILED` IPC 는 지금 받는 화면이 없지만 #126 에서 쓸 예정이라 남겼습니다.
