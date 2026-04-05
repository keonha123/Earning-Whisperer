# ⚙️ Backend (시그널 분석 및 라우팅 서버) 요구사항 정의서

## 1. 모듈의 역할 및 목표
이 모듈은 EarningWhisperer 프로젝트 전체 시스템의 데이터 흐름을 통제하는 **'오케스트레이터이자 중앙 관제탑(Control Tower)'** 역할을 담당한다. 

AI 엔진(Python)은 상태를 기억하지 않고 순수 점수만 산출하므로, 백엔드(Java) 서버가 이 점수들을 수집하여 **시계열 추세(EMA)를 계산**하고 1차 매매 방향을 결정한다. 자본시장법 규제(미등록 투자일임업 방지) 및 보안을 준수하기 위해 **중앙 서버에서 직접 증권사 API를 호출하지 않는다.** 대신, 사용자의 개인 설정과 자체 장부(Ledger) 기반의 리스크 관리 룰을 통과한 최종 매매 신호(Signal)를 사용자의 로컬 에이전트(Desktop App)로 실시간 라우팅하며, 에이전트가 실행한 실제 체결 결과를 수집하여 대시보드에 중계하는 통제 센터 역할을 수행한다.

## 2. 핵심 기능 요구사항 (Core Features)

### [Feature 1] 시그널 수신 및 EMA(지수이동평균) 상태 연산 (핵심)
- Redis의 `trading-signals` 채널을 구독하여 AI 서버가 발행하는 JSON(`raw_score`, `rationale`)을 비동기적으로 수신한다.
- **상태 유지 연산:** 단순히 `raw_score`에 반응하는 것이 아니라, DB 또는 캐시에 저장된 이전 점수들을 바탕으로 **EMA(Exponential Moving Average)**를 계산하여 단기적인 노이즈를 필터링한 `ema_score`를 도출한다.
- **⚠️ 현재 구현의 한계 (추후 개선 예정):** EMA 이전 상태값은 현재 서버 메모리(`InMemoryEmaStateStore`)에만 보관된다. 서버 재시작 시 ticker별 EMA 상태가 초기화되는 문제가 있으며, 프로젝트 중후반에 MySQL 또는 Redis Persistent 저장 방식으로 전환하여 해결할 예정이다.
- **⚠️ 현재 구현의 한계 (추후 개선 예정):** Redis Pub/Sub 특성상 백엔드가 일시적으로 다운된 후 복구되면 그 사이 AI Engine이 발행한 신호가 유실될 수 있다. 프로젝트 중후반에 **Redis Streams** 또는 **Kafka** 도입을 검토하여 메시지 내구성을 확보할 예정이다.

### [Feature 2] 포트폴리오 룰 엔진 및 장부(Ledger) 기반 리스크 관리
- 로컬 에이전트가 주기적으로 동기화해 주는 계좌 정보를 바탕으로 서버 내에 유저별 **자체 추정 장부(Internal Ledger)**를 구축 및 관리한다.
- 도출된 `ema_score`가 사용자의 포트폴리오 설정(임계치, 쿨다운 타임 등)과 자체 장부 상의 잔고/비중 조건을 통과하는지 교차 검증을 수행한다.
- **방어 로직:** 조건을 충족하지 못하면 신호를 생성하지 않고 관망(Hold)하며, 조건을 충족한 경우에 한해 거래 상태를 `PENDING(대기)`으로 DB에 기록한다.

### [Feature 3] 프라이빗 신호 라우팅 및 상태 동기화 콜백(Callback)
- 결정된 매매 신호(`BUY`/`SELL`)를 전체 브로드캐스트가 아닌, 대상 사용자 전용의 **프라이빗 WebSocket 채널**(`/user/{userId}/queue/signals`)로 라우팅하여 발송한다.
- **결과 수신 (REST API):** 로컬 에이전트가 증권사 API를 통해 실제 주문을 처리한 뒤 전송하는 체결 결과(주문 번호, 성공 여부 등) 및 최신 잔고 데이터를 수신하기 위한 콜백 엔드포인트(`POST /api/v1/trades/{tradeId}/callback`, `POST /api/v1/portfolio/sync`)를 제공한다.
- 수신된 데이터를 바탕으로 DB의 거래 상태를 `EXECUTED` 또는 `FAILED`로 최종 업데이트하고 장부를 동기화한다.

### [Feature 4] 프론트엔드 웹 실시간 중계 (WebSocket)
- 실시간 `raw_score` 및 `ema_score`의 변동, AI의 논리적 해설(`rationale`), 그리고 콜백을 통해 최종 확인된 거래 로그 및 포트폴리오 변동 내역을 프론트엔드 웹(SaaS 화면)으로 실시간 브로드캐스팅한다.

### [Feature 5] 쇼케이스 데모룸 리플레이 (DemoReplayService)
- 회원가입 없이 서비스를 체험할 수 있는 **쇼케이스 데모룸** 전용 채널(`/topic/live/demo`)로 과거 어닝콜 스크립트를 반복 재생한다.
- **라디오 방송국 모델:** 서버 기동 시부터 `DemoReplayService`가 백그라운드에서 스크립트를 처음부터 끝까지 무한 반복 재생한다.

## 3. 입출력 명세 (I/O Specification)
- **Input 1:** Redis Pub/Sub 메시지 수신 (AI의 `raw_score`, `rationale`)
- **Input 2:** Frontend Web의 HTTP Request (사용자 설정 변경, 웹 대시보드 데이터 조회 등)
- **Input 3:** Local Agent의 HTTP POST Request (실제 매매 체결 결과 콜백 및 잔고 동기화)
- **Output 1:** Local Agent로의 WebSocket(STOMP) 메시지 푸시 (개인화된 매매 실행 명령 신호)
- **Output 2:** Frontend Web으로의 WebSocket 브로드캐스트 (대시보드 시각화용 통합 데이터)

## 4. 기술 스택 (Java)
- **Core:** `Java 17` 이상 / `Spring Boot 3.x`
- **Database:** `Spring Data JPA` / `MySQL`
- **Cache & Message Broker:** `Spring Data Redis`
- **Real-time Communication:** `Spring WebSocket` + `STOMP`

## 5. 완료 기준 (Definition of Done - DoD)
1. [ ] **AI 및 룰 엔진 연동:** Redis 채널에 가짜 시그널을 주입했을 때, 백엔드가 이를 수신하여 EMA를 계산하고 포트폴리오 룰을 적용하여 정확한 `PENDING` 상태의 거래 기록을 DB에 생성하는가?
2. [ ] **프라이빗 신호 전송:** 생성된 매매 명령이 대상 사용자의 전용 웹소켓 큐(Queue)로만 독립적이고 정확하게 라우팅되어 발송되는가?
3. [ ] **콜백 처리 무결성:** 로컬 에이전트(모사 클라이언트)가 체결 완료 콜백 API를 호출했을 때, 해당 거래의 상태가 `EXECUTED`로 안전하게 변경되고 자체 장부가 갱신되며, 대시보드에 즉각 반영되는가?
