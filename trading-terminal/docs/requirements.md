# 🖥️ Trading Terminal (데스크톱 트레이딩 실행 엔진) 요구사항 정의서

## 1. 모듈의 역할 및 목표
이 모듈은 EarningWhisperer 시스템의 **'실행 엔진(Execution Engine)'**이자 **'개인용 보안 금고(Vault)'** 역할을 담당한다.
자본시장법(미등록 투자일임업 방지) 및 증권사 API 약관(키 중앙 집중화 금지)을 엄격히 준수하기 위해, 실제 매매 주문은 중앙 서버가 아닌 사용자의 로컬 PC(본 프로그램)에서 직접 실행된다. **제로 트러스트(Zero Trust) 보안 원칙**에 따라 사용자의 KIS API 키는 중앙 서버로 절대 전송되지 않으며, 오직 본 로컬 데스크톱 앱의 OS 보안 영역에만 암호화되어 저장된다.

## 2. 핵심 화면 및 기능 명세 (Core Pages)

### [Page 1] 인증 및 보안 금고 (Auth & Vault)
- SaaS JWT 로그인
- KIS 모의투자 앱키/시크릿/계좌번호 입력 → OS Credential Manager 암호화 저장

### [Page 2] 메인 대시보드 (Main Dashboard)
- KIS 잔고 API 직접 호출 → 총자산, 보유현금, 수익률
- 당일 어닝콜 예정 종목 Watchlist (LIVE 배지)

### [Page 3] 🔴 라이브 트레이딩 룸 (Live Trading Room) - 핵심 화면
- 백엔드 WebSocket Private 채널 실시간 신호 수신
- EMA 추세선 차트, Raw Score 게이지, 신호 피드
- 트레이딩 모드별 매매 실행 분기

### [Page 4] 체결 영수증 및 히스토리 (Execution History)
- 백엔드 시그널 ↔ 실제 체결 내역 대조

### [Page 5] 시스템 설정 및 트레이딩 통제권 (Settings & Control)
- 리스크 관리 파라미터 (매수비율, 보유비중, 쿨다운)
- 트레이딩 모드 3단계 토글 (MANUAL / 1-Click / AUTO-PILOT)
- KIS API 키 등록/삭제, 토큰 재발급

## 3. 트레이딩 모드 3단계

| 모드 | 동작 |
|------|------|
| Manual | 신호 피드만 수신. 유저가 직접 버튼 클릭 시에만 주문 |
| 1-Click (SEMI_AUTO) | 신호 수신 시 승인 팝업 노출. [승인] 클릭 또는 Enter 키 입력 시 주문 |
| Auto-Pilot | 신호 수신 즉시 백그라운드에서 자동 주문 |

## 4. 핵심 백그라운드 로직

### WebSocket Listener
- `/user/{userId}/queue/signals` 구독 (상시 대기)
- 신호 도착 시 OS 네이티브 알림 + 트레이딩 모드 분기

### KIS OpenAPI 통신
- Access Token 로컬 메모리 캐싱, 만료 전 선제 갱신
- **주문 수량 산출 주체:** 본 터미널. 백엔드는 비율(`order_ratio`)까지만 결정하고, 터미널이 실계좌 잔고·현재가를 조회하여 최종 수량을 산출한다. 서버 측 수량 결정을 배제함으로써 자본시장법상 미등록 투자일임업 리스크를 회피한다.
  - BUY: `floor(orderableCash × order_ratio / currentPrice)`
  - SELL: `floor(holdingQty × order_ratio)` (0이면 주문 안 함)
- **모의투자 URL:** `https://openapivts.koreainvestment.com:29443`

### 체결 결과 콜백
- 주문 완료 후 `POST /api/v1/trades/{tradeId}/callback` 전송 (필수)
- 기동 시 + 매매 완료 후 `POST /api/v1/portfolio/sync` 전송

## 5. Electron 아키텍처 (IPC 통신)
- **Renderer Process (UI/React):** 화면 렌더링, 사용자 이벤트 처리
- **Main Process (Node.js):** KIS API 키 복호화, HTTP 주문, 백엔드 WebSocket 연결
- **IPC 브릿지:** Renderer → Main 이벤트 전달 → Main이 KIS API 호출

## 6. 기술 스택
- **Framework:** `Electron` + `React` (Vite 빌드)
- **Main Process:** `Node.js`, `axios`, `sockjs-client`, `@stomp/stompjs`
- **Renderer Process:** `Tailwind CSS`, `Zustand`
- **Security:** `keytar` (OS Credential Manager)

## 7. 완료 기준 (Definition of Done - DoD)
1. [ ] **보안 저장 테스트:** KIS API 키가 평문으로 저장되지 않고, OS의 자격 증명 관리자를 통해 안전하게 암호화되어 보관되는가?
2. [ ] **IPC 및 주문 실행 레이턴시:** AUTO_PILOT 상태에서 신호 수신 시 KIS 서버로 주문이 전송되기까지의 지연 시간이 1초 이내인가?
3. [ ] **상태 동기화 무결성:** 로컬 주문 실행 직후 KIS 응답(성공/실패)과 최신 잔고 현황이 백엔드 Callback API로 누락 없이 전송되는가?
