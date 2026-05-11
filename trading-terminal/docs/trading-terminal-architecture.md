# Trading Terminal 기술 아키텍처

## 문서 개요

본 문서는 EarningWhisperer Trading Terminal(Electron 데스크톱 앱)의 구현 전 기술 아키텍처를 정의한다.
개발자가 코드 작성에 즉시 착수할 수 있는 수준의 설계 결정과 그 근거를 포함한다.

---

## 1. Electron 프로세스 역할 분리

Electron 앱은 두 개의 분리된 실행 환경으로 구성된다. 역할 분리 원칙은 단순하다.
**보안 경계를 넘는 모든 I/O는 Main 프로세스가 독점한다.**

### Main 프로세스 책임

| 책임 영역 | 구체적 역할 |
|-----------|-------------|
| Credential 관리 | keytar를 통한 KIS API 키 저장/조회/삭제 |
| KIS API 호출 | OAuth 토큰 발급, 주문 실행, 잔고 조회 (Node.js HTTP) |
| WebSocket STOMP 연결 | 백엔드 Private 채널 구독 및 생명주기 관리 |
| 백엔드 HTTP 콜백 | 체결 결과 POST, 포트폴리오 Sync POST |
| OS 알림 | Electron Notification API 호출 |
| 앱 생명주기 | BrowserWindow 생성, System Tray, 자동 업데이트 |
| JWT 토큰 관리 | 메모리 내 보관 (디스크 기록 금지) |

### Renderer 프로세스 책임

| 책임 영역 | 구체적 역할 |
|-----------|-------------|
| UI 렌더링 | React 컴포넌트 트리, Tailwind 스타일 |
| 사용자 인터랙션 | 버튼 클릭, 폼 입력, 모드 전환 |
| 상태 구독 | Zustand store 읽기/업데이트 |
| 차트 렌더링 | 주가 틱 차트, EMA 추세선, Raw Score 게이지 |
| IPC 호출 | contextBridge를 통해 노출된 API만 사용 |

### 설계 근거

Renderer에서 `require('keytar')`나 `require('net')`을 직접 호출하는 구조는 `nodeIntegration: true`를 요구하며, 이는 XSS 공격 시 시스템 전체를 노출시키는 치명적 보안 결함이다. `nodeIntegration: false` + `contextIsolation: true` 조합에서 Renderer는 순수한 브라우저 환경으로 격리된다.

---

## 2. IPC 채널 설계

### 설계 원칙

- Renderer → Main: `ipcRenderer.invoke` (Promise 기반, 응답 대기)
- Main → Renderer: `webContents.send` (단방향 이벤트 push)
- 모든 채널명은 `terminal:` 네임스페이스 prefix 사용

### Renderer → Main (invoke/handle)

```
terminal:auth:login           { email, password } → { token, user }
terminal:auth:logout          {} → void

terminal:vault:save-credentials   { appKey, appSecret, accountNo } → { success }
terminal:vault:get-credentials    {} → { appKey: string | null, ... }
terminal:vault:delete-credentials {} → { success }
terminal:vault:has-credentials    {} → boolean

terminal:kis:get-balance           {} → KisBalanceDto
terminal:kis:place-order           { action, ticker, qty } → KisOrderResultDto
terminal:kis:get-token-status      {} → { isValid, expiresAt }

terminal:settings:update  { tradingMode, riskParams } → void

terminal:ws:connect       {} → void
terminal:ws:disconnect    {} → void
```

### Main → Renderer (send)

```
terminal:signal:received        TradeSignalDto        // 신호 수신
terminal:trade:executed         TradeExecutionDto     // 체결 완료
terminal:trade:failed           TradeErrorDto         // 체결 실패
terminal:ws:status-changed      WsStatusDto           // 연결 상태 변경
terminal:mode:forced-manual     { reason: string }    // 강제 Manual 전환
terminal:kis:token-refreshed    { expiresAt: number } // KIS 토큰 갱신
terminal:notification           NotificationDto       // OS 알림 트리거
```

### Preload 스크립트 (contextBridge)

Preload는 두 개의 메서드 그룹만 노출한다.

```typescript
// preload/index.ts
contextBridge.exposeInMainWorld('terminalApi', {
  // Renderer가 Main에 요청하는 invoke 래퍼
  invoke: (channel: string, payload?: unknown) =>
    ipcRenderer.invoke(channel, payload),

  // Main이 Renderer에 push하는 이벤트 구독/해제
  on: (channel: string, listener: (payload: unknown) => void) => {
    const wrapped = (_event: IpcRendererEvent, payload: unknown) =>
      listener(payload);
    ipcRenderer.on(channel, wrapped);
    return () => ipcRenderer.removeListener(channel, wrapped);
  },
});
```

Renderer에서는 `window.terminalApi.invoke('terminal:vault:has-credentials')` 형태로만 접근 가능하다. Node.js API는 일절 노출하지 않는다.

---

## 3. 상태 관리 설계

### 원칙: 진실 공급원 위치 결정

Electron에서 상태는 두 곳에 존재할 수 있다. Main 프로세스 메모리와 Renderer의 Zustand store다.
**단일 진실 공급원은 Renderer의 Zustand store**로 설정한다. Main은 이벤트를 push하고, Renderer store가 해당 이벤트를 소비하여 상태를 갱신한다. Main이 별도로 상태를 유지하면 두 곳의 상태가 분기하는 문제가 생긴다.

단, 다음 두 가지는 Main 메모리에만 존재한다.
- JWT 액세스 토큰 (XSS로부터 격리)
- KIS OAuth access_token (디스크/Renderer 노출 금지)

### Zustand Store 구조

```typescript
// store/useConnectionStore.ts
interface ConnectionState {
  wsStatus: 'DISCONNECTED' | 'CONNECTING' | 'CONNECTED' | 'RECONNECTING';
  kisTokenStatus: 'VALID' | 'EXPIRED' | 'UNKNOWN';
  hasCredentials: boolean;
  isAuthenticated: boolean;
}

// store/useTradingStore.ts
interface TradingState {
  mode: 'MANUAL' | 'SEMI_AUTO' | 'AUTO_PILOT';
  activeSignal: TradeSignalDto | null;      // 현재 처리 중인 신호
  pendingConfirm: TradeSignalDto | null;    // SEMI_AUTO 확인 대기 신호
  lastExecutedTrade: TradeExecutionDto | null;
  signalHistory: TradeSignalDto[];          // 최근 50건
}

// store/usePortfolioStore.ts
interface PortfolioState {
  cash: number;
  totalAsset: number;
  holdings: HoldingDto[];
  lastSyncedAt: number | null;             // Unix timestamp
}

// store/useUserStore.ts
interface UserState {
  userId: string | null;
  email: string | null;
  plan: 'FREE' | 'PRO';
  settings: UserSettings;
}
```

### IPC 이벤트 → Store 갱신 연결

앱 최상위 컴포넌트(`App.tsx`)에서 Main 이벤트를 구독하고 store를 갱신한다.

```typescript
// renderer/App.tsx (최상위)
useEffect(() => {
  const unsubs = [
    window.terminalApi.on('terminal:signal:received', (payload) => {
      useTradingStore.getState().receiveSignal(payload as TradeSignalDto);
    }),
    window.terminalApi.on('terminal:ws:status-changed', (payload) => {
      useConnectionStore.getState().setWsStatus((payload as WsStatusDto).status);
    }),
    window.terminalApi.on('terminal:mode:forced-manual', () => {
      useTradingStore.getState().forceManual();
    }),
    // ... 나머지 채널 구독
  ];
  return () => unsubs.forEach(fn => fn());
}, []);
```

---

## 4. WebSocket STOMP 연결 관리

### Main에서 관리하는 이유

WebSocket 연결을 Renderer에서 관리하면 창 새로고침이나 React 리렌더링 사이클에서 연결이 끊길 수 있다.
Main 프로세스는 BrowserWindow와 독립적으로 실행되므로 안정적인 연결 생명주기를 보장한다.
또한 JWT 토큰을 STOMP CONNECT 헤더에 첨부해야 하는데, 토큰은 Main 메모리에만 존재한다.

### 연결 생명주기 및 재연결 전략

```
[초기 연결 시퀀스]
Main 기동
  → JWT 토큰 확인 (메모리)
  → 토큰 없으면 연결 보류 (DISCONNECTED 상태 유지)
  → Renderer에서 terminal:ws:connect invoke 수신
  → STOMP 연결 시도
  → 성공: CONNECTED push → Renderer store 갱신
  → 실패: RECONNECTING push → 재시도 스케줄

[재연결 전략 - Exponential Backoff]
재시도 간격: 2s → 4s → 8s → 16s → 30s (상한선 고정)
최대 재시도: 무제한 (앱 실행 중 계속 시도)
재연결 시도마다: terminal:ws:status-changed(RECONNECTING) push

[연결 끊김 감지]
STOMP heartbeat: 10초 간격 (서버 설정에 맞춤)
heartbeat 미수신 3회 초과 → 강제 종료 후 재연결 시퀀스 진입

[강제 Manual 전환 트리거]
DISCONNECTED 상태 전환 시 즉시:
  1. terminal:mode:forced-manual 이벤트 push
  2. OS 네이티브 알림 발송 ("백엔드 연결 끊김 — 수동 모드로 전환됨")
```

### 신호 수신 → UI 업데이트 흐름

```
[Main Process]
STOMP 메시지 수신 (/user/{userId}/queue/signals)
  → JSON 파싱 → TradeSignalDto 검증
  → 현재 tradingMode 확인 (Main 메모리 캐시)
  → AUTO_PILOT: 즉시 주문 흐름 진입
  → SEMI_AUTO/MANUAL: Renderer에 이벤트 push

webContents.send('terminal:signal:received', signalDto)

[Renderer Process]
useTradingStore.receiveSignal(signal)
  → activeSignal 업데이트
  → MANUAL: signalHistory에 추가, UI 알림만 표시
  → SEMI_AUTO: pendingConfirm 설정 → 확인 다이얼로그 표시
  → AUTO_PILOT: 자동 실행 (store 레벨에서 invoke 호출)
```

---

## 5. KIS API 통합 설계

### OAuth 토큰 관리

KIS access_token은 발급 후 24시간 유효하다. Main 프로세스가 이 토큰을 메모리에 보관하며 만료 1시간 전 자동 갱신한다.

```
[토큰 발급 시퀀스]
1. keytar에서 appKey, appSecret 조회
2. POST https://openapi.koreainvestment.com:9443/oauth2/tokenP
   body: { grant_type: "client_credentials", appkey, appsecret }
3. 응답 { access_token, token_type, expires_in } 메모리 저장
4. expiresAt = Date.now() + (expires_in * 1000)
5. 만료 1시간 전 자동 갱신 스케줄 등록 (setTimeout)
6. 갱신 실패 시: terminal:kis:token-refreshed(EXPIRED) push

[토큰 상태 전이]
UNKNOWN → (발급 시도) → VALID
VALID → (만료 1시간 전) → 자동 갱신 시도 → VALID
VALID → (갱신 실패 / 앱 재기동 후 만료) → EXPIRED
EXPIRED → (사용자 재인증 또는 자동 재시도) → VALID
```

### 주문 실행 흐름

신호 수신부터 콜백 전송까지의 전체 흐름이다.

```
[신호 수신]
TradeSignalDto { trade_id, action, ticker, target_qty, ema_score }

[Step 1] 사전 검증 (Main)
  - KIS 토큰 유효성 확인 → 만료면 즉시 갱신 후 진행
  - Credential 존재 확인

[Step 2] 잔고 조회 (Main → KIS API)
  GET /uapi/domestic-stock/v1/trading/inquire-balance
  응답: { cash, holdings: [{ ticker, qty, avgPrice }] }

[Step 3] 수량 보정 (Main 비즈니스 로직)
  BUY 케이스:
    - 1주당 현재가 추정 (별도 시세 조회 또는 마지막 수신 price 사용)
    - 주문 가능 수량 = floor(cash * MAX_POSITION_RATIO / currentPrice)
    - 최종 수량 = min(target_qty, 주문 가능 수량)
    - 최종 수량 <= 0 이면 → FAILED 콜백 전송 (예수금 부족)
  SELL 케이스:
    - 보유 수량 조회
    - 최종 수량 = min(target_qty, 보유 수량)
    - 최종 수량 <= 0 이면 → FAILED 콜백 전송 (보유 없음)

[Step 4] KIS 주문 API 호출 (Main)
  POST /uapi/domestic-stock/v1/trading/order-cash
  headers: { authorization, appkey, appsecret, tr_id: "VTTC0802U"(BUY) | "VTTC0801U"(SELL) }
  body: { CANO, ACNT_PRDT_CD, PDNO: ticker, ORD_DVSN: "00", ORD_QTY, ORD_UNPR: "0" }

[Step 5] 체결 확인 (Main, 폴링 최대 3회)
  GET /uapi/domestic-stock/v1/trading/inquire-ccnl
  성공 조건: 체결 수량 > 0

[Step 6] 백엔드 콜백 전송 (Main → Backend)
  POST /api/v1/trades/{tradeId}/callback
  성공: { status: "EXECUTED", broker_order_id, executed_price, executed_qty, error_message: null }
  실패: { status: "FAILED", broker_order_id: null, executed_price: null, executed_qty: 0, error_message }

[Step 7] 포트폴리오 Sync (Main → Backend, 비동기)
  Step 6 완료 후 비동기로 실행
  POST /api/v1/portfolio/sync

[Step 8] Renderer 업데이트 (Main → Renderer)
  terminal:trade:executed 또는 terminal:trade:failed 이벤트 push
```

### 에러 처리 전략

| 에러 유형 | 처리 방식 |
|-----------|-----------|
| KIS 토큰 만료 (401) | 즉시 토큰 재발급 후 1회 재시도 |
| KIS 토큰 재발급 실패 | FAILED 콜백 전송, OS 알림, Renderer 에러 표시 |
| 예수금 부족 | 수량 보정 단계에서 조기 종료, FAILED 콜백 |
| KIS API 5xx | 3회 재시도 (1s 간격), 실패 시 FAILED 콜백 |
| 네트워크 타임아웃 | 10초 타임아웃, FAILED 콜백 |
| SEMI_AUTO 미승인 | 30초 타임아웃, 자동 취소, FAILED 콜백 |

모든 에러는 Main에서 처리하며 Renderer는 결과 이벤트만 수신한다.
Renderer에서 에러 처리 로직이 분산되지 않도록 주의한다.

---

## 6. 보안 아키텍처

### Credential 저장/조회 흐름

```
[저장 (최초 설정)]
Renderer: 폼 입력 { appKey, appSecret, accountNo }
  → invoke('terminal:vault:save-credentials', payload)
  → [IPC 경계]
  → Main: keytar.setPassword('EarningWhisperer', 'kis-appKey', appKey)
           keytar.setPassword('EarningWhisperer', 'kis-appSecret', appSecret)
           keytar.setPassword('EarningWhisperer', 'kis-accountNo', accountNo)
  → OS Credential Manager에 암호화 저장
  → 성공 응답 반환 (값 자체는 반환하지 않음)

[조회 (주문 실행 시)]
Main 내부에서만 실행:
  const appKey = await keytar.getPassword('EarningWhisperer', 'kis-appKey')
  → KIS API 호출에 사용
  → Renderer에 appKey 값 절대 전달 금지

[조회 (Renderer 화면 표시용)]
invoke('terminal:vault:has-credentials')
  → Main: 세 키 모두 존재하면 true, 아니면 false
  → Renderer: boolean만 수신 (실제 키 값 미수신)
  → 화면에는 "API 키 등록됨 ●●●●●●●●" 마스킹 표시
```

### BrowserWindow 보안 설정

```typescript
const win = new BrowserWindow({
  webPreferences: {
    nodeIntegration: false,          // Node.js API Renderer 접근 차단
    contextIsolation: true,          // Preload 스크립트 격리
    sandbox: true,                   // Chromium 샌드박스 활성화
    preload: path.join(__dirname, 'preload/index.js'),
    webSecurity: true,
    allowRunningInsecureContent: false,
    experimentalFeatures: false,
  },
});
```

### CSP (Content Security Policy)

```typescript
// Main 프로세스에서 헤더 설정
session.defaultSession.webRequest.onHeadersReceived((details, callback) => {
  callback({
    responseHeaders: {
      ...details.responseHeaders,
      'Content-Security-Policy': [
        "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline';"
      ],
    },
  });
});
```

### JWT 토큰 보안

- 로그인 성공 후 access_token은 Main 프로세스 메모리에만 저장
- 디스크(localStorage, electron-store, 파일) 기록 금지
- Renderer는 토큰 값 자체를 알 필요 없음 (HTTP 요청을 Main이 대신 수행)
- 앱 종료 시 메모리에서 자동 소거

---

## 7. 디렉토리 구조

```
trading-terminal/
├── package.json
├── tsconfig.json
├── electron.vite.config.ts        # electron-vite 빌드 설정
├── electron-builder.config.ts     # 패키징 설정 (Windows/macOS)
│
├── src/
│   ├── main/                      # Main 프로세스
│   │   ├── index.ts               # 진입점, BrowserWindow 생성
│   │   ├── ipc/                   # IPC 핸들러 등록
│   │   │   ├── authHandlers.ts    # 로그인/로그아웃
│   │   │   ├── vaultHandlers.ts   # keytar Credential 관리
│   │   │   ├── kisHandlers.ts     # KIS API 래퍼
│   │   │   ├── settingsHandlers.ts
│   │   │   └── wsHandlers.ts      # WebSocket 연결 제어
│   │   ├── services/              # Main 비즈니스 로직
│   │   │   ├── StompService.ts    # WebSocket STOMP 연결 관리
│   │   │   ├── KisService.ts      # KIS API 호출, 토큰 관리
│   │   │   ├── TradeExecutor.ts   # 주문 실행 오케스트레이터
│   │   │   ├── BackendClient.ts   # 백엔드 HTTP REST 클라이언트
│   │   │   └── NotificationService.ts  # OS 네이티브 알림
│   │   └── store/                 # Main 메모리 상태 (토큰 등)
│   │       └── mainState.ts
│   │
│   ├── preload/                   # Preload 스크립트
│   │   └── index.ts               # contextBridge 노출
│   │
│   └── renderer/                  # Renderer 프로세스 (React)
│       ├── index.html
│       ├── main.tsx               # React 진입점
│       ├── App.tsx                # 루트 컴포넌트, IPC 이벤트 구독
│       ├── pages/
│       │   ├── AuthPage.tsx       # 로그인 + Vault 설정
│       │   ├── DashboardPage.tsx  # 메인 대시보드
│       │   ├── TradingRoomPage.tsx # 라이브 트레이딩 룸
│       │   ├── HistoryPage.tsx    # 체결 히스토리
│       │   └── SettingsPage.tsx   # 시스템 설정
│       ├── components/
│       │   ├── layout/
│       │   │   ├── TopHeader.tsx
│       │   │   ├── LeftSidebar.tsx
│       │   │   └── StatusBar.tsx
│       │   ├── trading/
│       │   │   ├── SignalFeed.tsx
│       │   │   ├── TradeConfirmDialog.tsx  # SEMI_AUTO 확인
│       │   │   ├── RawScoreGauge.tsx
│       │   │   ├── EmaChart.tsx
│       │   │   └── OrderButtons.tsx
│       │   └── common/
│       │       ├── ConnectionBadge.tsx
│       │       └── ModeToggle.tsx
│       ├── store/
│       │   ├── useConnectionStore.ts
│       │   ├── useTradingStore.ts
│       │   ├── usePortfolioStore.ts
│       │   └── useUserStore.ts
│       └── lib/
│           ├── ipc.ts             # window.terminalApi 타입 래퍼
│           └── constants.ts       # IPC 채널명 상수
│
└── resources/                     # 앱 아이콘 등 정적 리소스
    └── icon.png
```

---

## 8. 핵심 패키지 의존성

### 런타임 의존성

| 패키지 | 버전 목표 | 선택 이유 |
|--------|-----------|-----------|
| `electron` | 30.x | 앱 런타임 |
| `@stomp/stompjs` | 7.x | STOMP over WebSocket. 브라우저/Node 양쪽에서 동작, 재연결 API 내장 |
| `keytar` | 7.x | OS 네이티브 Credential Manager 추상화. macOS Keychain / Windows Credential Manager 통일 인터페이스 |
| `axios` | 1.x | KIS API 및 백엔드 HTTP 통신. 인터셉터로 토큰 헤더 자동 첨부 |
| `zustand` | 4.x | 웹앱과 동일한 상태관리 패턴 유지 |
| `react` + `react-dom` | 18.x | UI 렌더링 |
| `lightweight-charts` | 4.x | TradingView 제공 오픈소스 주가 차트. 성능 최적화된 Canvas 기반 |

### 개발 의존성

| 패키지 | 선택 이유 |
|--------|-----------|
| `electron-vite` | Electron 전용 Vite 번들러. Main/Preload/Renderer를 각각 올바른 타겟으로 빌드 |
| `electron-builder` | Windows/macOS 배포 패키지 생성. NSIS(Windows), DMG(macOS) |
| `typescript` | 타입 안전성, Main/Renderer 간 DTO 타입 공유 |
| `tailwindcss` | 웹앱과 동일한 스타일 시스템 |

### keytar 네이티브 빌드 주의사항

keytar는 Node.js 네이티브 모듈이다. 패키징 시 Electron의 Node.js 버전에 맞게 재컴파일해야 한다.

```json
// package.json
{
  "scripts": {
    "postinstall": "electron-rebuild -f -w keytar"
  }
}
```

`@stomp/stompjs`를 Main 프로세스(Node.js 환경)에서 사용할 때 `WebSocket` 전역 객체가 없으므로 Node.js 내장 `ws` 패키지를 WebSocket 구현체로 주입해야 한다.

```typescript
// main/services/StompService.ts
import { Client } from '@stomp/stompjs';
import WebSocket from 'ws';

const client = new Client({
  webSocketFactory: () => new WebSocket(WS_URL) as unknown as globalThis.WebSocket,
  // ...
});
```

---

## 9. 핵심 아키텍처 결정 사항 (ADR 요약)

### ADR-001: WebSocket 연결 위치

**결정**: Main 프로세스에서 관리

**근거**: Renderer의 React 생명주기(언마운트, HMR)와 독립된 안정적인 연결이 필요하다. JWT 토큰이 Main 메모리에만 존재하므로 Renderer에서 연결을 관리하면 토큰을 Renderer에 노출해야 하는 모순이 생긴다.

**trade-off**: Main에서 연결 상태를 IPC로 Renderer에 전파해야 하는 간접 레이어가 추가된다.

---

### ADR-002: JWT 토큰 저장 위치

**결정**: Main 프로세스 메모리에만 저장, 디스크 기록 금지

**근거**: electron-store나 localStorage에 저장하면 파일 시스템 접근 권한이 있는 공격자에게 노출된다. 앱 종료 시 자동 소거되는 메모리가 가장 안전한 저장소다.

**trade-off**: 앱 재기동 시 매번 재로그인이 필요하다. 이를 완화하려면 Refresh Token을 keytar에 저장하는 방식을 별도로 설계해야 한다 (MVP 이후 고려).

---

### ADR-003: 트레이딩 모드 상태 위치

**결정**: Renderer Zustand store를 단일 진실 공급원으로 사용, Main은 복사본을 캐시

**근거**: UI에서 모드를 전환하고 표시하는 주체가 Renderer이므로 Renderer가 원본을 소유하는 것이 자연스럽다.

**trade-off**: Main에서 신호를 수신할 때 현재 모드를 알아야 AUTO_PILOT 즉시 실행을 결정할 수 있다. 이 때문에 Main이 모드 캐시를 별도로 유지하며, 모드 변경 시 IPC로 Main에 알려야 한다. 상태가 두 곳에 존재하는 구조적 비용이 있다.

---

### ADR-004: KIS API 호출 위치

**결정**: Main 프로세스에서만 호출, Renderer는 invoke로 요청

**근거**: KIS API 호출에는 appKey, appSecret, access_token이 모두 필요하다. 이 값들은 보안상 Main에서만 접근 가능하다. Renderer에서 직접 호출하려면 이 값들을 Renderer에 노출해야 하므로 불가하다.

**trade-off**: 모든 KIS API 응답이 IPC를 통해 직렬화되어 전달되므로 미세한 지연이 추가된다. 매매 주문의 특성상 이 수준의 지연은 무시 가능하다.
