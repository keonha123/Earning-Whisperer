# EarningWhisperer — Trading Terminal

![Electron](https://img.shields.io/badge/Electron-31-47848F?logo=electron&logoColor=white)
![React](https://img.shields.io/badge/React-18-61DAFB?logo=react&logoColor=black)
![Tailwind CSS](https://img.shields.io/badge/Tailwind%20CSS-v3-06B6D4?logo=tailwindcss&logoColor=white)
![KIS](https://img.shields.io/badge/KIS%20OpenAPI-모의투자-E31837)

> **KIS API 키는 이 앱의 OS 보안 영역에만 암호화 저장됩니다. 중앙 서버로 절대 전송되지 않습니다.**

백엔드가 내린 AI 매매 신호를 수신하여 사용자의 KIS 모의투자 계좌로 실제 주문을 실행하는 **로컬 실행 엔진(Execution Engine)** 겸 **보안 금고(Vault)**입니다. 자본시장법(미등록 투자일임업 방지) 및 KIS API 약관을 준수하기 위해 모든 주문은 사용자의 로컬 PC에서 직접 실행됩니다.

---

## 보안 아키텍처

```mermaid
graph TB
    subgraph Renderer["Renderer Process (React)"]
        UI["5개 페이지\nAuth · Dashboard · Trading Room\nHistory · Settings"]
        Stores["Zustand 스토어 4개\nUser / Connection / Trading / Portfolio"]
        UI <--> Stores
    end

    subgraph Preload["Preload (contextBridge)"]
        Bridge["window.terminalApi\n.invoke() / .on()\n— Node.js API 완전 차단 —"]
    end

    subgraph Main["Main Process (Node.js)"]
        IPC["IPC Handlers"]
        KisSvc["KisService\nAPI 키 관리·토큰 발급·주문"]
        StompSvc["StompService\nWS 연결·신호 수신·재연결"]
        TradeExec["TradeExecutor\n잔고 조회·수량 보정·주문"]
        BackendSvc["BackendClient\n콜백·잔고 동기화·설정"]
        IPC --> KisSvc & StompSvc & BackendSvc
        KisSvc --> TradeExec --> BackendSvc
    end

    subgraph Secure["OS 보안 영역 (keytar)"]
        Vault["Credential Manager\nAppKey · AppSecret · 계좌번호"]
    end

    UI <-->|"ipcRenderer.invoke/on"| Bridge
    Bridge <-->|"ipcMain.handle\nwebContents.send"| IPC
    KisSvc <-->|"암호화 저장/조회"| Vault
    KisSvc <-->|"HTTPS 주문/잔고"| KIS["KIS OpenAPI\n모의투자"]
    StompSvc <-->|"STOMP /ws-native"| Backend["Backend\n:8082"]
    BackendSvc <-->|"REST API"| Backend
```

**핵심 보안 원칙:**
- Renderer Process는 `fs`, `path`, Node.js API에 직접 접근할 수 없습니다.
- KIS API 키는 `keytar`를 통해 OS Credential Manager에 암호화 저장되며, 조회 시마다 OS에서 복호화합니다. 메모리에 캐시하지 않습니다.
- 모든 민감 작업(주문, API 키 복호화)은 Main Process에서만 실행됩니다.

---

## 트레이딩 모드 3단계

| 모드 | 표시명 | 동작 | Pro 전용 |
|------|--------|------|---------|
| `MANUAL` | 수동 | 신호 피드만 수신. 사용자가 직접 버튼을 클릭해야 주문 실행 | — |
| `SEMI_AUTO` | 1-Click | 신호 수신 시 30초 타임아웃 승인 팝업 표시. Enter/클릭 시 주문, Esc/타임아웃 시 FAILED 콜백 전송 | — |
| `AUTO_PILOT` | 자동 | 신호 수신 즉시 Main Process가 백그라운드에서 자동 주문. UI 개입 없음 | ✓ |

**Fallback:** 백엔드 WebSocket 연결이 끊기면 즉시 `MANUAL`로 강제 전환 + OS 네이티브 알림 표시.

```mermaid
flowchart TD
    Signal["신호 수신\n(STOMP /user/queue/signals)"]
    Signal --> Mode{현재 모드}

    Mode -->|MANUAL| Feed["신호 피드에 표시\nIGNORED 상태"]
    Mode -->|SEMI_AUTO| Dialog["승인 팝업 표시\n30초 타임아웃"]
    Mode -->|AUTO_PILOT| Auto["즉시 TradeExecutor 실행"]

    Dialog -->|승인 / Enter| Execute
    Dialog -->|거절 / Esc / 타임아웃| Cancel["TRADE_CANCEL IPC\n→ FAILED 콜백 전송"]

    Auto --> Execute["KIS 잔고 조회\n→ 수량 보정\n→ KIS 주문 실행"]
    Execute --> Callback["결과 콜백\nPOST /trades/{id}/callback\n(EXECUTED / FAILED)"]
    Execute --> Sync["잔고 동기화\nPOST /portfolio/sync"]
```

---

## 기술 스택

| 분류 | 기술 | 버전 |
|------|------|------|
| 데스크톱 프레임워크 | Electron | 31 |
| UI | React | 18 |
| 스타일링 | Tailwind CSS | v3 |
| 빌드 도구 | electron-vite | 2 |
| 패키징 | electron-builder | 24 |
| 상태 관리 | Zustand | 4 |
| 보안 저장소 | keytar (OS Credential Manager) | 7 |
| HTTP 클라이언트 | axios | 1.7 |
| WebSocket (Main) | @stomp/stompjs + ws | — |
| 차트 | lightweight-charts | 4 |
| 언어 | TypeScript | 5 |

---

## 빠른 시작

### Prerequisites

- Node.js 18+
- Python & C++ 빌드 도구 (keytar 네이티브 모듈 컴파일 필요)
  - **Windows:** Visual Studio Build Tools + `windows-build-tools`
  - **macOS:** Xcode Command Line Tools (`xcode-select --install`)
- 백엔드 서버 실행 중 (기본 `http://localhost:8082`)
- KIS 모의투자 계좌 및 API 키 ([KIS Developers](https://apiportal.koreainvestment.com) 발급)

### 1. 의존성 설치

```bash
cd trading-terminal
npm install
# postinstall 스크립트가 자동으로 keytar 네이티브 모듈을 컴파일합니다
# electron-rebuild -f -w keytar
```

### 2. 환경 변수 설정 (선택)

`BACKEND_URL` 기본값은 `http://localhost:8082`입니다. 변경하려면:

```bash
# .env 파일 생성
BACKEND_URL=http://your-backend-server:8082
```

### 3. 개발 모드 실행

```bash
npm run dev
```

Vite 개발 서버와 Electron이 동시에 시작되며, 소스 변경 시 자동 리로드됩니다.

---

## 빌드 및 패키징

```bash
# TypeScript + React 빌드
npm run build

# 최종 설치 파일 생성 (build → electron-builder)
npm run package
```

| 플랫폼 | 출력 파일 |
|--------|---------|
| Windows | `dist/EarningWhisperer Terminal Setup 0.1.0.exe` |
| macOS | `dist/EarningWhisperer Terminal-0.1.0.dmg` |

빌드 중간 산출물은 `out/`에 생성됩니다.

---

## 페이지 구성

| 페이지 | 경로 | 역할 |
|--------|------|------|
| 인증 & Vault | `/auth` | JWT 로그인 + KIS API 키 OS 암호화 저장 (2-Step) |
| 대시보드 | `/dashboard` | 포트폴리오 현황(잔고·보유 종목) + 최근 신호 5건 |
| 트레이딩 룸 | `/trading-room` | **핵심** — EMA 차트 + 신호 피드 + 실시간 EMA 게이지 |
| 체결 내역 | `/history` | 페이지네이션된 체결 내역 테이블 |
| 설정 | `/settings` | 리스크 파라미터 + KIS 연동 상태 + 모드 토글 |

---

## IPC 채널 레퍼런스

### Renderer → Main (`ipc.invoke`)

| 채널 | 역할 |
|------|------|
| `terminal:auth:login` | 백엔드 JWT 로그인 |
| `terminal:auth:logout` | 로그아웃 + 민감 데이터 소거 |
| `terminal:vault:save-credentials` | KIS API 키 OS Credential Manager에 저장 |
| `terminal:vault:has-credentials` | KIS API 키 저장 여부 확인 |
| `terminal:vault:delete-credentials` | KIS API 키 삭제 |
| `terminal:kis:get-balance` | KIS 잔고 조회 (해외주식) |
| `terminal:kis:place-order` | KIS 주문 실행 (TradeExecutor 경유) |
| `terminal:kis:get-token-status` | KIS OAuth 토큰 상태 조회 |
| `terminal:kis:issue-token` | KIS OAuth 토큰 발급 |
| `terminal:settings:update` | 트레이딩 모드 / 리스크 파라미터 저장 |
| `terminal:ws:connect` | 백엔드 STOMP 연결 시작 |
| `terminal:ws:disconnect` | 백엔드 STOMP 연결 해제 |
| `terminal:trades:get` | 체결 내역 페이지네이션 조회 |
| `terminal:trade:cancel` | 신호 취소 + 백엔드 FAILED 콜백 전송 |

### Main → Renderer (`ipc.on`)

| 채널 | 역할 |
|------|------|
| `terminal:signal:received` | 백엔드로부터 수신한 매매 신호 |
| `terminal:trade:executed` | 주문 체결 성공 결과 |
| `terminal:trade:failed` | 주문 실패 결과 |
| `terminal:ws:status-changed` | WebSocket 연결 상태 변화 |
| `terminal:mode:forced-manual` | 강제 MANUAL 전환 알림 (연결 끊김) |
| `terminal:kis:token-refreshed` | KIS 토큰 자동 갱신 완료 |

---

## KIS API 주요 정보

**모의투자 베이스 URL:** `https://openapivts.koreainvestment.com:29443`

| 작업 | TR_ID |
|------|-------|
| 해외주식 매수 | `VTTT1002U` |
| 해외주식 매도 | `VTTT1006U` |

**토큰 관리 전략:** 발급 후 Main Process 메모리 캐싱 → 만료 1시간 전 선제 갱신 → 갱신 실패 시 알림

---

## 환경 변수

| 변수 | 기본값 | 설명 |
|------|--------|------|
| `BACKEND_URL` | `http://localhost:8082` | 백엔드 REST API + WebSocket 서버 주소 |

WebSocket URL은 `BACKEND_URL`에서 자동 파생됩니다: `http://...` → `ws://.../ws-native`

---

## 관련 문서

| 문서 | 설명 |
|------|------|
| [`docs/api-spec.md`](../docs/api-spec.md) | 서비스 간 API & 데이터 컨트랙트 전체 명세 |
| [`docs/trading-terminal-architecture.md`](docs/trading-terminal-architecture.md) | Electron 기술 아키텍처 상세 |
| [`docs/trading-terminal-prd.md`](docs/trading-terminal-prd.md) | 제품 요구사항 정의서 (PRD) |
| [`docs/trading-terminal-ui-spec.md`](docs/trading-terminal-ui-spec.md) | UI 컴포넌트 스펙 |
| [`docs/trading-terminal-ux-spec.md`](docs/trading-terminal-ux-spec.md) | UX 플로우 스펙 |
| [`docs/requirements.md`](docs/requirements.md) | Trading Terminal 요구사항 정의서 (원문) |
