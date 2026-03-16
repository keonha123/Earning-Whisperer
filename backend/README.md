# ⚙️ Backend (매매 및 비즈니스 서버) 요구사항 정의서

## 1. 모듈의 역할 및 목표
이 모듈은 EarningWhisperer 프로젝트의 '심장'이자 '손' 역할을 담당합니다. 
AI 엔진(Python)은 상태를 기억하지 않고 순수 점수만 뱉어내므로, 백엔드(Java) 서버가 이 점수들을 수집하여 **시계열 추세(EMA)를 계산**하고 최종 매매 방향을 결정합니다. 이후 유저의 설정과 리스크 관리 룰(Rule)을 통과한 신호에 한해, **실제 증권사 오픈 API(모의투자 계좌)**를 호출하여 매매 주문을 체결하고 모든 상황을 프론트엔드 대시보드에 실시간으로 중계합니다.

## 2. 핵심 기능 요구사항 (Core Features)

### [Feature 1] 시그널 수신 및 EMA(지수이동평균) 상태 연산 (핵심)
- Redis의 `trading-signals` 채널을 구독하여 AI 서버가 발행하는 JSON(`raw_score`, `rationale`)을 비동기적으로 수신합니다.
- **상태 유지 연산:** 단순히 `raw_score`에 반응하는 것이 아니라, 백엔드 메모리나 Redis에 저장된 이전 점수들을 바탕으로 **EMA(Exponential Moving Average)**를 계산하여 단기적인 노이즈를 필터링한 `ema_score`를 도출합니다.

### [Feature 2] 포트폴리오 룰 엔진 및 리스크 관리
- 도출된 `ema_score`를 바탕으로 방향이 결정되면, 증권사 API를 통해 현재 계좌의 실제 예수금과 보유 종목(잔고)을 조회하여 '주문 가능한 최적 수량'을 계산합니다.
- **방어 로직:** `ema_score`가 임계치(예: +0.6)를 넘지 못하거나, 해당 종목이 이미 목표 비중을 초과했다면 주문을 생성하지 않고(Hold) 관망합니다.

### [Feature 3] 증권사 오픈 API 연동 및 매매 실행 (모의투자)
- 한국투자증권(또는 타 증권사) 오픈 API를 연동하여 모의투자 계좌에 매수/매도 주문 REST API 요청을 보냅니다.
- **제약사항 (API 핸들링):** - 정기적인 접근 토큰(Access Token) 발급 및 갱신 로직이 구현되어야 합니다.
  - 외부 API의 초당 호출 제한(Rate Limit)을 넘지 않도록 요청 속도를 제어하거나 큐(Queue)를 활용해야 합니다.
  - 타임아웃(Timeout) 등 네트워크 실패 시 재시도(Retry)하는 예외 처리가 필수적입니다.

### [Feature 4] 프론트엔드 실시간 중계 (WebSocket)
- 실시간 `raw_score` 및 `ema_score`의 변동, AI의 논리적 해설(`rationale`), 증권사 API로 전송한 최종 주문 내역 및 체결 결과를 프론트엔드(React/Next.js) 대시보드로 실시간 브로드캐스팅합니다.
- **제약사항:** 클라이언트가 새로고침을 하지 않아도 화면의 차트와 거래 로그가 부드럽게 업데이트되도록 양방향 통신 채널(STOMP)을 안정적으로 유지해야 합니다.

## 3. 입출력 명세 (I/O Specification)
- **Input 1:** Redis Pub/Sub 메시지 수신 (AI의 `raw_score`, `rationale`)
- **Input 2:** Frontend의 HTTP Request (사용자 포트폴리오 설정 등)
- **Input 3:** 증권사 API Response (계좌 잔고, 체결 확인 내역)
- **Output 1:** 외부 증권사 오픈 API로의 HTTP POST Request (매매 주문)
- **Output 2:** Frontend로의 WebSocket(STOMP) 메시지 푸시 (실시간 데이터 종합 전송)

## 4. 기술 스택 (Java)
- **Core:** `Java 17` 이상 / `Spring Boot 3.x`
- **External API Client:** `WebClient` 또는 `OpenFeign` (증권사 API 비동기/동기 호출 및 토큰 관리)
- **Database:** `Spring Data JPA` / `MySQL` (회원 정보 및 자체 거래 로그 저장)
- **Cache & Message Broker:** `Spring Data Redis` (AI 시그널 수신 및 토큰 캐싱)
- **Real-time Communication:** `Spring WebSocket` + `STOMP`

## 5. 완료 기준 (Definition of Done - DoD)
이 모듈의 개발이 완료되었다고 평가받으려면 다음 테스트를 통과해야 합니다.
1. [ ] **AI 연동:** Redis 채널에 가짜 시그널을 던졌을 때, 백엔드가 누락 없이 수신하여 EMA 점수를 계산하는가?
2. [ ] **증권사 API 연동:** 인증 토큰을 정상 발급받고, 매수/매도 신호 발생 시 증권사 모의투자 API 서버로 주문을 전송하여 '체결 완료(또는 접수)' 응답 코드를 성공적으로 받아오는가?
3. [ ] **실시간 통신:** 프론트엔드와 WebSocket이 연결된 상태에서 시그널 수신 및 체결 완료 시, 1초 이내에 프론트엔드로 모든 데이터가 도달하는가?