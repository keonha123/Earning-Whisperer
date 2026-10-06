# 0001. 실시간 전달에 STOMP over WebSocket 을 사용합니다

- 날짜: 2026-03-25
- 상태: 채택
- 결정한 사람: @keonha123
- 대체한 ADR: 없음
- 대체된 ADR: 없음

## 배경

backend 는 클라이언트에 두 종류의 메시지를 밀어 보내야 했습니다. 모든 클라이언트에 같은 내용을 뿌리는
브로드캐스트(시세, 어닝콜 실시간 데이터)와, 특정 사용자의 터미널에만 보내는 개인 메시지(매매 명령)입니다.
`backend/docs/requirements.md`(현재 삭제, 커밋 `98d4ab2` 시점)는 출력을 Local Agent 로의 개인화된 메시지
푸시와 Frontend Web 으로의 브로드캐스트 두 갈래로 정의하고, 완료 기준에 대상 사용자의 전용 웹소켓 큐로만
라우팅되는 것을 두었습니다.

2026-03-13 기획안(커밋 `2357a78`)부터 backend 와 클라이언트 사이 실시간 통신은 STOMP 로 적혀 있었습니다.
2026-03-17 기획서(커밋 `301ee62`, 현재 삭제)의 기술 스택 한 줄에는 Socket.io 가 적혀 있었지만 같은 커밋의
backend·frontend README 는 STOMP 였습니다. STOMP 는 PR #4(2026-03-25)에서 처음 코드에 들어왔습니다.

## 결정

backend 는 Spring 의 `@EnableWebSocketMessageBroker` 로 STOMP 메시지 브로커를 엽니다(`WebSocketConfig`).

- 연결 엔드포인트는 두 개입니다. `/ws` 는 브라우저용으로 SockJS 폴백을 켜 두었고 `/ws-native` 는
  트레이딩 터미널용 순수 WebSocket 입니다.
- 브로커 목적지는 `/topic`(브로드캐스트)과 `/queue`(개인 메시지)이고 사용자 목적지 prefix 는 `/user` 입니다.
  `/queue` 와 `/user` 는 커밋 `a2a1738`(2026-04-03)에서 추가했습니다.
  브로드캐스트는 `convertAndSend`, 개인 메시지는 `convertAndSendToUser` 로 발행합니다.
- 트레이딩 터미널은 Electron main process 의 `StompService` 에서 `@stomp/stompjs` 와 `ws` 패키지로 연결합니다.
  `trading-terminal/docs/trading-terminal-architecture.md`(현재 삭제, 커밋 `98d4ab2` 시점)의 "ADR-001: WebSocket
  연결 위치" 는 main process 에 둔 이유로, 창 새로고침이나
  React 리렌더링에 연결이 끊기지 않는 점과 CONNECT 헤더에 실을 JWT 가 main 메모리에만 있다는 점을 적고 있습니다.

## 검토한 대안

### Socket.io

기획서 기술 스택에 한 줄 적혀 있었지만, 대안으로 비교·검토한 기록은 없습니다. 같은 시점의 다른 문서가 모두
STOMP 였으므로 기획서 표기가 어긋난 것으로 보입니다.

### 순수 WebSocket

`trading-terminal/docs/trading-terminal-prd.md`(현재 삭제, 커밋 `98d4ab2` 시점)의 "리스크 3" 은 STOMP 가
순수 WebSocket 보다 연결 상태 관리(CONNECT/SUBSCRIBE/DISCONNECT), heartbeat, 세션 만료 처리가 복잡하다고
비교하고 완화책으로 `@stomp/stompjs` 사용을 적었습니다. 순수 WebSocket 을 고르지 않은 이유 자체는 기록이 없습니다.

## 결과

좋아진 점

- 새 실시간 기능을 토픽 하나로 붙일 수 있었습니다. 현재 backend 는 `/topic/market/indices`,
  `/topic/prices`, `/topic/transcript/{ticker}`, `/topic/factcheck/{ticker}`, `/topic/evaluation/{ticker}`,
  `/topic/transcript-diff/{ticker}` 등을 발행합니다. 각 토픽의 페이로드는 [API 명세](../api-spec.md)에 있습니다.
- 사용자별 라우팅을 직접 구현하지 않고 Spring 의 사용자 목적지(`/user/queue/...`)를 씁니다.

감수한 비용

- `enableSimpleBroker` 는 backend 프로세스 메모리 안의 브로커입니다. 구독 정보가 인스턴스 사이에 공유되지
  않으므로 backend 를 여러 대로 늘리려면 브로커 구성을 다시 정해야 합니다.
- `convertAndSendToUser` 는 접속하지 않은 사용자에게 보낸 메시지를 조용히 버립니다. 이 때문에 매매 명령이
  PENDING 으로 남는 문제가 생겼고 `TradePendingExpiryScheduler` 의 TTL 만료와 터미널 재접속 시
  `GET /api/v1/trades/pending` 복구로 보완했습니다(커밋 `56fe0e8`, #64).
- 연결 수명 관리를 클라이언트가 맡습니다. 터미널에서 소켓 종료 감지, 재연결 타이머 중복, 교체된 client 의
  지연 close 콜백 문제를 따로 고쳤습니다(커밋 `236d612`, `2c8d658`).

후속 조치

- 2026-10-01 까지 `StompJwtChannelInterceptor` 는 CONNECT 의 토큰 검증에 실패해도 경고만 남기고 통과시켜
  토큰 없이 `/topic/**` 를 구독할 수 있었습니다(#136). PR #137(커밋 `53e160c`)에서 인증 없는 연결과 구독을
  거부하고 클라이언트 SEND 프레임을 전면 거부하도록 바꿨습니다. 터미널은 인증 실패 ERROR 프레임을 받으면
  토큰을 갱신한 뒤 재연결합니다.
- `/app` 애플리케이션 목적지 prefix 는 설정에 남아 있지만 위 변경 이후 클라이언트 SEND 를 받지 않으므로
  쓰이지 않습니다.
- 2026-10-05 PR #142(#127)에서 서버가 주문을 지시하던 경로를 걷어내면서 유일한 개인 메시지였던
  `/user/{userId}/queue/signals` 와 터미널 재접속 시 `GET /api/v1/trades/pending` 복구도 함께 제거했습니다.
  현재 backend 는 `convertAndSendToUser` 를 쓰지 않으므로 위 결과 절의 사용자 목적지와 미접속 사용자 문제는
  더 이상 해당하지 않습니다. `TradePendingExpiryScheduler` 는 사용자가 직접 낸 주문의 PENDING 만료만 맡습니다.
- `WebSocketConfig` 의 `/queue` 브로커와 `/user` prefix 는 설정에 남아 있지만 보내는 곳이 없습니다. PR #142 는
  이 설정을 닫는 일을 보안 설정 변경으로 보고 별도 PR 로 미뤘습니다.
