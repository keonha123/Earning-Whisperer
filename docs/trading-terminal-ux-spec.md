# Trading Terminal UX 스펙

## EarningWhisperer Trading Terminal — UX 설계 문서

**버전:** 1.0  
**작성일:** 2026-04-04  
**대상:** Frontend Developer (Renderer 구현 담당)  
**참조 문서:** `docs/trading-terminal-architecture.md`, `docs/trading-terminal-prd.md`

---

## 1. 정보 아키텍처

### 1.1 화면 네비게이션 구조

```
App.tsx (루트 — IPC 이벤트 구독 + 전역 다이얼로그 레이어)
│
├── [미인증 경로]
│   └── AuthPage
│       ├── Step 1: 로그인 폼 (email + password)
│       └── Step 2: KIS API 키 등록 (appKey + appSecret + accountNo)
│           ※ 로그인 성공 + KIS 키 없음 → Step 2 자동 진입
│           ※ 로그인 성공 + KIS 키 있음 → DashboardPage 이동
│
└── [인증된 경로] — 공통 레이아웃 (TopHeader + LeftSidebar + StatusBar)
    ├── DashboardPage     (기본 홈)
    ├── TradingRoomPage   (라이브 트레이딩 룸)
    ├── HistoryPage       (체결 히스토리)
    └── SettingsPage      (리스크 파라미터 설정)
```

### 1.2 네비게이션 상태 전이

```
AuthPage
  ─[로그인 성공 + KIS 키 없음]──→  AuthPage Step 2 (KIS 설정)
  ─[로그인 성공 + KIS 키 있음]──→  DashboardPage

DashboardPage
  ─[TradingRoom 진입 클릭]────→   TradingRoomPage
  ─[History 메뉴 클릭]────────→   HistoryPage
  ─[Settings 메뉴 클릭]────────→  SettingsPage

전역 레이어 (어느 페이지에서든 렌더링)
  ─[pendingConfirm 신호 수신 + SEMI_AUTO 모드]──→  TradeConfirmDialog (모달 오버레이)
  ─[WS 강제 MANUAL 전환]────────────────────────→  ForcedManualBanner (상단 고착)
```

### 1.3 라우팅 구조

```
/                 → DashboardPage (redirect)
/dashboard        → DashboardPage
/trading-room     → TradingRoomPage
/history          → HistoryPage
/settings         → SettingsPage

/auth             → AuthPage (미인증 시만 접근 가능)
```

Router guard 규칙: `isAuthenticated && hasCredentials` 둘 다 충족해야 인증된 경로 접근 허용. `isAuthenticated` 가 false면 `/auth` 리다이렉트. `isAuthenticated` 가 true지만 `hasCredentials` 가 false면 `/auth?step=vault` 리다이렉트.

---

## 2. 레이아웃 시스템

### 2.1 기본 창 크기 및 그리드

Electron 창: 1200×800px (기본), 최소 1024×680px.

인증된 경로의 공통 레이아웃:

```
┌─────────────────────────────────────────────────┐  ← TopHeader (48px 고정)
│  [로고]  [현재 페이지명]           [ConnectionBadge] [UserMenu]  │
├──────────┬──────────────────────────────────────┤
│          │                                      │
│  Left    │          Main Content Area           │
│  Sidebar │          (flex-1, overflow-y: auto)  │
│  (200px) │                                      │
│          │                                      │
│          │                                      │
├──────────┴──────────────────────────────────────┤  ← StatusBar (32px 고정)
│  [WS 상태] [KIS 토큰 상태] [현재 모드] [강제전환 경고]       │
└─────────────────────────────────────────────────┘
```

CSS Grid 정의:

```css
.app-layout {
  display: grid;
  grid-template-rows: 48px 1fr 32px;
  grid-template-columns: 200px 1fr;
  grid-template-areas:
    "header  header"
    "sidebar content"
    "statusbar statusbar";
  height: 100vh;
  overflow: hidden;
}
```

### 2.2 AuthPage 레이아웃

```
┌─────────────────────────────────────────────────┐
│                                                 │
│           [앱 로고 + 앱 이름]                   │
│                                                 │
│    ┌──────────────────────────────────┐         │
│    │      로그인 카드 (400px 폭)       │         │
│    │  [이메일 입력]                    │         │
│    │  [비밀번호 입력]                  │         │
│    │  [로그인 버튼]                    │         │
│    └──────────────────────────────────┘         │
│                                                 │
└─────────────────────────────────────────────────┘
```

배경: 전체 `--color-bg-base` 단색. 카드: `--color-surface-1` + `--shadow-lg`. 창 중앙 수직/수평 정렬.

KIS 설정 Step 2:

```
┌─────────────────────────────────────────────────┐
│                                                 │
│  [← 로그인으로] (Step 2/2 표시기)                │
│                                                 │
│    ┌──────────────────────────────────┐         │
│    │      KIS API 키 등록 카드         │         │
│    │  [경고: 이 키는 로컬에만 저장됨]  │         │
│    │  [App Key 입력]                   │         │
│    │  [App Secret 입력 (마스킹)]       │         │
│    │  [계좌번호 입력]                  │         │
│    │  [저장 버튼]                      │         │
│    └──────────────────────────────────┘         │
│                                                 │
└─────────────────────────────────────────────────┘
```

### 2.3 DashboardPage 레이아웃

Main Content Area 내부:

```
┌──────────────────────────────────────────┐
│  상단: ModeSelector 전체 폭              │  ← 240px 고정 높이
│  [MANUAL] [SEMI_AUTO] [AUTO_PILOT]       │
├──────────────┬───────────────────────────┤
│              │                           │
│ Portfolio    │   최근 신호 피드          │
│ Summary      │   (최근 5건, 읽기전용)    │
│ (40% 폭)     │   (60% 폭)                │
│              │                           │
│ - 총 자산    │                           │
│ - 현금       │                           │
│ - 수익률     │                           │
│ - 보유 종목  │                           │
│              │                           │
└──────────────┴───────────────────────────┘
```

### 2.4 TradingRoomPage 레이아웃

```
┌──────────────────────────────────────────┐
│  상단 바: 현재 모드 + ModeToggle (우측)   │  ← 48px
├─────────────────────┬────────────────────┤
│                     │  SignalFeed         │
│  EmaChart           │  (실시간 신호 목록) │
│  (lightweight-charts│                    │
│   TradingView)      │  각 항목:           │
│                     │  ticker / BUY·SELL  │
│  60% 폭             │  ema_score / 상태   │
│                     │                    │
│                     │  40% 폭            │
├─────────────────────┴────────────────────┤
│  하단 바: RawScoreGauge (전체 폭)         │  ← 80px
└──────────────────────────────────────────┘
```

### 2.5 HistoryPage 레이아웃

```
┌──────────────────────────────────────────┐
│  헤더: "체결 내역"  [새로고침 버튼]       │
├──────────────────────────────────────────┤
│  필터 바: [기간 선택] [ticker 검색]       │
├──────────────────────────────────────────┤
│  테이블 (전체 폭)                         │
│  날짜 | ticker | BUY/SELL | 수량 | 체결가 │
│  | 손익 | 상태(EXECUTED/FAILED)           │
│  ...                                     │
└──────────────────────────────────────────┘
```

### 2.6 SettingsPage 레이아웃

```
┌──────────────────────────────────────────┐
│  헤더: "리스크 설정"                      │
├────────────────────────┬─────────────────┤
│  설정 섹션 (두 컬럼)    │                 │
│                        │                 │
│  [리스크 파라미터]      │  [KIS 연동 상태] │
│  - 1회 매수 비율        │  - API 키: 등록됨│
│  - 최대 보유 비중       │  - 토큰 상태     │
│  - 쿨다운 (분)         │  - [키 재등록]   │
│  - EMA 최소 임계치     │  - [키 삭제]     │
│                        │                 │
│  [저장 버튼]           │                 │
└────────────────────────┴─────────────────┘
```

---

## 3. 컴포넌트 인벤토리

### 3.1 레이아웃 컴포넌트

```typescript
// components/layout/TopHeader.tsx
interface TopHeaderProps {
  currentPage: string;
}
// 내부에서 useConnectionStore, useUserStore 직접 구독

// components/layout/LeftSidebar.tsx
interface LeftSidebarProps {
  activePath: string;
  onNavigate: (path: string) => void;
}
// 네비게이션 항목: Dashboard, TradingRoom, History, Settings

// components/layout/StatusBar.tsx
// props 없음 — 전역 store에서 직접 구독
// 표시 항목: wsStatus, kisTokenStatus, tradingMode, forcedManual 여부
```

### 3.2 연결 상태 컴포넌트

```typescript
// components/common/ConnectionBadge.tsx
interface ConnectionBadgeProps {
  wsStatus: 'DISCONNECTED' | 'CONNECTING' | 'CONNECTED' | 'RECONNECTING';
  kisTokenStatus: 'VALID' | 'EXPIRED' | 'UNKNOWN';
  compact?: boolean; // TopHeader용 축약 표시 여부
}

// components/common/ForcedManualBanner.tsx
interface ForcedManualBannerProps {
  reason: string;
  onDismiss: () => void;
}
// wsStatus === DISCONNECTED 시 자동 표시. 연결 복구 시 자동 해제
```

### 3.3 모드 전환 컴포넌트

```typescript
// components/common/ModeSelector.tsx
interface ModeSelectorProps {
  currentMode: TradingMode;
  userPlan: 'FREE' | 'PRO';
  onChange: (mode: TradingMode) => void;
  size?: 'full' | 'compact'; // Dashboard용 full / TradingRoom 상단바용 compact
  disabled?: boolean; // WS DISCONNECTED 상태에서 자동 비활성화
}

type TradingMode = 'MANUAL' | 'SEMI_AUTO' | 'AUTO_PILOT';

// AUTO_PILOT는 PRO 전용. FREE 플랜이면 잠금 아이콘 + 툴팁 표시
// 모드 전환 시 confirm 없이 즉각 반영 (StatusBar에서 변경 확인 가능)
```

### 3.4 SEMI_AUTO 확인 다이얼로그

```typescript
// components/trading/TradeConfirmDialog.tsx
interface TradeConfirmDialogProps {
  signal: TradeSignalDto;
  timeoutSeconds: number;         // 30초 고정 (PRD F08)
  onApprove: () => void;
  onReject: () => void;
  onTimeout: () => void;          // 타임아웃 시 자동 onReject와 동일 처리
}

interface TradeSignalDto {
  trade_id: string;
  action: 'BUY' | 'SELL';
  target_qty: number;
  ticker: string;
  ema_score: number;
}
```

이 컴포넌트는 `App.tsx`의 최상위 모달 레이어에 렌더링. `useTradingStore`의 `pendingConfirm`이 non-null일 때 표시.

### 3.5 신호 피드

```typescript
// components/trading/SignalFeed.tsx
interface SignalFeedProps {
  signals: SignalFeedItem[];
  maxItems?: number;  // 기본 50
}

interface SignalFeedItem {
  trade_id: string;
  ticker: string;
  action: 'BUY' | 'SELL';
  ema_score: number;
  receivedAt: number;          // Unix timestamp (seconds)
  status: SignalStatus;
}

type SignalStatus = 'PENDING' | 'EXECUTED' | 'FAILED' | 'IGNORED' | 'REJECTED';

// components/trading/SignalFeedRow.tsx
interface SignalFeedRowProps {
  item: SignalFeedItem;
  isLatest?: boolean;   // 가장 최근 항목은 강조 표시
}
```

### 3.6 차트 및 게이지

```typescript
// components/trading/EmaChart.tsx
interface EmaChartProps {
  ticker: string | null;
  height?: number;   // 기본 320px
}
// lightweight-charts 래퍼. 신호 수신 시 ticker 변경 → 차트 리셋

// components/trading/RawScoreGauge.tsx
interface RawScoreGaugeProps {
  score: number | null;   // 0.0 ~ 1.0, null이면 "신호 대기중" 표시
  label?: string;
}
// 반원형 게이지. 0.0~0.49: 중립(회색), 0.5~0.69: 관심(노랑), 0.7~1.0: 강신호(녹색/빨강)
```

### 3.7 포트폴리오 요약

```typescript
// components/portfolio/PortfolioSummary.tsx
// props 없음 — usePortfolioStore에서 직접 구독

// 표시: 총 자산(원화), 현금, 수익률(%), 마지막 동기화 시간
// [포트폴리오 동기화] 버튼 — invoke('terminal:kis:get-balance')

// components/portfolio/HoldingsList.tsx
interface HoldingsListProps {
  holdings: HoldingDto[];
  compact?: boolean;  // Dashboard용 축약 / 향후 별도 페이지용 전체
}

interface HoldingDto {
  ticker: string;
  qty: number;
  avgPrice: number;
  currentPrice: number;
  unrealizedPnl: number;
  unrealizedPnlRate: number;
}
```

### 3.8 폼 컴포넌트 (Auth)

```typescript
// components/auth/LoginForm.tsx
interface LoginFormProps {
  onSuccess: () => void;
  isLoading: boolean;
  error: string | null;
}

// components/auth/KisVaultForm.tsx
interface KisVaultFormProps {
  onSuccess: () => void;
  existingCredentialsExist: boolean;  // true면 "수정" 모드 텍스트
  isLoading: boolean;
  error: string | null;
}
```

### 3.9 공통 기본 컴포넌트

```typescript
// components/common/Badge.tsx
interface BadgeProps {
  variant: 'success' | 'danger' | 'warning' | 'neutral' | 'info';
  size?: 'sm' | 'md';
  children: React.ReactNode;
}

// components/common/CountdownRing.tsx
interface CountdownRingProps {
  totalSeconds: number;
  remainingSeconds: number;
  size?: number;     // SVG 직경 px, 기본 48
  strokeWidth?: number;
}

// components/common/SkeletonRow.tsx
// 로딩 중 테이블 행 자리 표시용

// components/common/Tooltip.tsx
interface TooltipProps {
  content: string;
  children: React.ReactNode;
  position?: 'top' | 'bottom' | 'left' | 'right';
}
```

---

## 4. 디자인 토큰

### 4.1 CSS 커스텀 속성 (다크 테마 단일 테마)

Trading Terminal은 다크 테마 단일 운용. 시스템 테마 연동 불필요 (트레이딩 앱 관례).

```css
/* renderer/styles/tokens.css */
:root {
  /* ── 배경 계층 (깊이 순서) ── */
  --color-bg-base:       #0a0c0f;   /* 앱 최하위 배경 */
  --color-surface-0:     #0f1215;   /* 사이드바, 헤더 배경 */
  --color-surface-1:     #161b22;   /* 카드, 패널 배경 */
  --color-surface-2:     #1c2330;   /* 입력 필드, 행 hover */
  --color-surface-3:     #232d3f;   /* 선택된 행, 활성 항목 */

  /* ── 테두리 ── */
  --color-border:        #2a3344;
  --color-border-subtle: #1e2738;
  --color-border-focus:  #3b82f6;

  /* ── 텍스트 ── */
  --color-text-primary:  #e2e8f0;   /* 주요 텍스트 */
  --color-text-secondary:#94a3b8;   /* 보조 텍스트 */
  --color-text-disabled: #4a5568;   /* 비활성 텍스트 */
  --color-text-inverse:  #0a0c0f;   /* 밝은 배경 위 텍스트 */

  /* ── 브랜드 ── */
  --color-brand:         #3b82f6;   /* 파란색 기본 액션 */
  --color-brand-hover:   #2563eb;
  --color-brand-subtle:  rgba(59,130,246,0.15);

  /* ── 매매 시그널 색상 (트레이딩 관례) ── */
  --color-buy:           #22c55e;   /* BUY / 상승 — 녹색 */
  --color-buy-hover:     #16a34a;
  --color-buy-subtle:    rgba(34,197,94,0.12);
  --color-sell:          #ef4444;   /* SELL / 하락 — 빨간색 */
  --color-sell-hover:    #dc2626;
  --color-sell-subtle:   rgba(239,68,68,0.12);

  /* ── 상태 색상 ── */
  --color-success:       #22c55e;
  --color-warning:       #f59e0b;
  --color-danger:        #ef4444;
  --color-neutral:       #64748b;
  --color-info:          #3b82f6;

  /* ── 연결 상태 색상 ── */
  --color-connected:     #22c55e;
  --color-connecting:    #f59e0b;
  --color-disconnected:  #ef4444;
  --color-reconnecting:  #f97316;

  /* ── EMA 스코어 색상 ── */
  --color-score-low:     #64748b;   /* 0.0 ~ 0.49 */
  --color-score-mid:     #f59e0b;   /* 0.5 ~ 0.69 */
  --color-score-high:    #22c55e;   /* 0.7 ~ 1.0 (BUY 신호) */
  --color-score-high-sell: #ef4444; /* 0.7 ~ 1.0 (SELL 신호) */

  /* ── 타이포그래피 ── */
  --font-family-base:   'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
  --font-family-mono:   'JetBrains Mono', 'Fira Code', 'Consolas', monospace;
  /* 모노스페이스: 가격, ticker, 수량 등 숫자 데이터에 사용 */

  --font-size-xs:    0.625rem;   /* 10px */
  --font-size-sm:    0.75rem;    /* 12px */
  --font-size-base:  0.875rem;   /* 14px — 앱 기본 (데스크톱 밀도) */
  --font-size-md:    1rem;       /* 16px */
  --font-size-lg:    1.125rem;   /* 18px */
  --font-size-xl:    1.375rem;   /* 22px */
  --font-size-2xl:   1.75rem;    /* 28px */
  --font-size-3xl:   2.25rem;    /* 36px — 포트폴리오 총 자산 */

  --font-weight-normal:   400;
  --font-weight-medium:   500;
  --font-weight-semibold: 600;
  --font-weight-bold:     700;

  --line-height-tight:  1.25;
  --line-height-normal: 1.5;

  /* ── 간격 (4px 베이스 그리드) ── */
  --space-0-5: 0.125rem;  /*  2px */
  --space-1:   0.25rem;   /*  4px */
  --space-1-5: 0.375rem;  /*  6px */
  --space-2:   0.5rem;    /*  8px */
  --space-3:   0.75rem;   /* 12px */
  --space-4:   1rem;      /* 16px */
  --space-5:   1.25rem;   /* 20px */
  --space-6:   1.5rem;    /* 24px */
  --space-8:   2rem;      /* 32px */
  --space-10:  2.5rem;    /* 40px */
  --space-12:  3rem;      /* 48px */
  --space-16:  4rem;      /* 64px */

  /* ── 레이아웃 고정 치수 ── */
  --layout-header-height:    48px;
  --layout-statusbar-height: 32px;
  --layout-sidebar-width:    200px;
  --layout-content-padding:  var(--space-6);

  /* ── 테두리 반경 ── */
  --radius-sm:   4px;
  --radius-md:   6px;
  --radius-lg:   8px;
  --radius-xl:   12px;
  --radius-full: 9999px;

  /* ── 그림자 ── */
  --shadow-sm:  0 1px 2px rgba(0,0,0,0.4);
  --shadow-md:  0 4px 6px rgba(0,0,0,0.5);
  --shadow-lg:  0 8px 24px rgba(0,0,0,0.6);
  --shadow-xl:  0 16px 48px rgba(0,0,0,0.75);

  /* ── 다이얼로그 오버레이 ── */
  --shadow-dialog: 0 20px 60px rgba(0,0,0,0.8), 0 0 0 1px rgba(239,68,68,0.3);
  /* TradeConfirmDialog는 빨간 테두리 glow로 위급성 표현 */

  /* ── 트랜지션 ── */
  --transition-fast:   100ms ease;
  --transition-normal: 200ms ease;
  --transition-slow:   300ms ease;

  /* ── z-index 스택 ── */
  --z-base:       0;
  --z-dropdown:   100;
  --z-sticky:     200;
  --z-overlay:    300;
  --z-modal:      400;
  --z-toast:      500;
  --z-tooltip:    600;
}
```

### 4.2 트레이딩 전용 색상 사용 원칙

- BUY 관련 모든 텍스트, 배경, 버튼: `--color-buy` 계열
- SELL 관련 모든 텍스트, 배경, 버튼: `--color-sell` 계열
- 이 규칙은 SignalFeed, TradeConfirmDialog, HistoryPage 테이블 행 전체에 일관 적용
- 수익(+) 표시: `--color-buy`, 손실(−) 표시: `--color-sell`
- 숫자 데이터(가격, 수량, EMA 스코어): 항상 `--font-family-mono` 사용

---

## 5. 인터랙션 패턴

### 5.1 모드 전환 UX 플로우

```
[사용자 행동] ModeSelector에서 새 모드 클릭
      │
      ▼
[즉각 반응] 선택된 탭 활성화 (낙관적 업데이트)
      │
      ▼
[IPC] invoke('terminal:settings:update', { tradingMode: newMode })
      │
      ├─ 성공 → useTradingStore.setMode(newMode)
      │          StatusBar 모드 표시 갱신
      │          toast("SEMI_AUTO 모드로 전환됨") — 1.5초 후 자동 사라짐
      │
      └─ 실패 → 이전 모드로 되돌림 (rollback)
                 ErrorToast 표시

[특수 케이스 — AUTO_PILOT, FREE 플랜]
  클릭 차단 + Tooltip("Pro 플랜에서 사용 가능합니다")

[특수 케이스 — WS DISCONNECTED 상태]
  SEMI_AUTO / AUTO_PILOT 전환 차단
  ModeSelector 전체 disabled 처리
  Tooltip("백엔드 연결이 끊겼습니다. 연결 복구 후 모드를 전환하세요.")
```

### 5.2 신호 수신 UX 플로우

```
[Main → Renderer IPC: terminal:signal:received]
      │
      ▼
useTradingStore.receiveSignal(signal)
      │
      ├─ MANUAL 모드
      │    → signalHistory 맨 앞에 추가 (최대 50건, 초과 시 가장 오래된 항목 제거)
      │    → SignalFeed 실시간 갱신 (새 항목 슬라이드-인 애니메이션)
      │    → OS 알림: "{ticker} {BUY/SELL} 신호 수신 (EMA: {score})"
      │    → 상태: IGNORED (사용자가 수동으로 처리)
      │
      ├─ SEMI_AUTO 모드
      │    → signalHistory에 PENDING 상태로 추가
      │    → pendingConfirm = signal
      │    → TradeConfirmDialog 즉시 표시 (30초 카운트다운 시작)
      │    → OS 알림: "매매 신호 — 확인 필요 ({ticker})"
      │
      └─ AUTO_PILOT 모드
           → signalHistory에 PENDING 상태로 추가
           → invoke('terminal:kis:place-order') (Main이 처리)
           → terminal:trade:executed / terminal:trade:failed 이벤트 대기
```

### 5.3 TradeConfirmDialog UX 플로우

```
[다이얼로그 표시 — pendingConfirm non-null]
      │
      ▼
[30초 카운트다운 시작]
  - CountdownRing SVG 애니메이션 (원형 진행 표시)
  - 남은 시간 숫자 표시 (30 → 0)
  - 10초 이하: 링 색상 --color-danger로 전환
  - 5초 이하: 다이얼로그 전체 경계선 pulse 애니메이션
      │
      ├─ [승인 버튼 클릭]
      │    → invoke('terminal:kis:place-order', signal)
      │    → 버튼을 로딩 스피너로 교체 (중복 클릭 방지)
      │    → 다이얼로그 유지 (결과 대기)
      │    → terminal:trade:executed 수신: 성공 상태 표시 후 1초 뒤 닫기
      │    → terminal:trade:failed 수신: 오류 상태 표시 후 2초 뒤 닫기
      │
      ├─ [거절 버튼 클릭]
      │    → pendingConfirm = null
      │    → 해당 신호 상태 REJECTED로 갱신
      │    → 다이얼로그 닫기 (애니메이션)
      │
      └─ [30초 타임아웃]
           → onTimeout() 호출 → onReject()와 동일 처리
           → 상태: IGNORED
           → toast("30초 타임아웃 — 신호가 자동 취소되었습니다.")
```

다이얼로그 시각 계층:
- 오버레이: `rgba(0,0,0,0.7)` backdrop
- 다이얼로그 카드: `--color-surface-1`, `--shadow-dialog` (빨간 테두리 glow)
- action 정보(ticker, BUY/SELL, qty, EMA)는 상단에 가장 크게 표시
- BUY: 초록 배경 강조 / SELL: 빨간 배경 강조
- 승인 버튼: action 색상 (BUY면 초록, SELL이면 빨간) — 크게, 두드러지게
- 거절 버튼: `--color-surface-3` 중립

### 5.4 강제 MANUAL 전환 UX 플로우

```
[terminal:mode:forced-manual IPC 수신]
      │
      ▼
useTradingStore.forceManual()
  - mode = 'MANUAL'
  - isForcedManual = true
  - forcedManualReason = reason
      │
      ▼
[ForcedManualBanner 표시]
  - TopHeader 하단에 고착 (sticky, --z-sticky)
  - 배경: --color-danger 반투명
  - 텍스트: "백엔드 연결 끊김 — 수동 모드로 자동 전환되었습니다"
  - [X] 닫기 버튼 (Banner 숨김, isForcedManual 유지)
  - ModeSelector: SEMI_AUTO, AUTO_PILOT 비활성화

[연결 복구: terminal:ws:status-changed(CONNECTED) 수신]
  - isForcedManual = false
  - ForcedManualBanner 제거
  - ModeSelector 재활성화
  - toast("백엔드에 다시 연결되었습니다.")
```

### 5.5 StatusBar 표시 상태 매핑

| wsStatus | 표시 | 색상 |
|---|---|---|
| CONNECTED | WS 연결됨 | `--color-connected` |
| CONNECTING | 연결 중... (점 깜빡임) | `--color-connecting` |
| RECONNECTING | 재연결 중... (회전 아이콘) | `--color-reconnecting` |
| DISCONNECTED | 연결 끊김 | `--color-disconnected` |

| kisTokenStatus | 표시 | 색상 |
|---|---|---|
| VALID | KIS 토큰 유효 | `--color-connected` |
| EXPIRED | KIS 토큰 만료 | `--color-danger` |
| UNKNOWN | KIS 토큰 확인 중 | `--color-neutral` |

### 5.6 키보드 인터랙션

| 컨텍스트 | 키 | 동작 |
|---|---|---|
| TradeConfirmDialog 열림 | Enter | 승인 |
| TradeConfirmDialog 열림 | Escape | 거절 |
| 전역 | Ctrl+1 | DashboardPage 이동 |
| 전역 | Ctrl+2 | TradingRoomPage 이동 |
| 전역 | Ctrl+3 | HistoryPage 이동 |
| 전역 | Ctrl+4 | SettingsPage 이동 |

TradeConfirmDialog가 열려 있는 동안 Ctrl+1~4 네비게이션은 차단. 트레이드 확인이 최우선.

### 5.7 로딩 및 빈 상태

| 상황 | UI 처리 |
|---|---|
| 포트폴리오 최초 로딩 | SkeletonRow 3행 표시 |
| 신호 피드 수신 대기 | "신호 대기 중..." 중앙 텍스트 + 점 애니메이션 |
| 히스토리 로딩 | SkeletonRow 5행 표시 |
| KIS 주문 처리 중 | TradeConfirmDialog 승인 버튼 → 스피너 |
| 포트폴리오 동기화 중 | 동기화 버튼 → 스피너, 비활성화 |

---

## 6. Tailwind 설정

### 6.1 `tailwind.config.js` 커스텀 컬러 확장

```javascript
// tailwind.config.js
module.exports = {
  content: ['./src/renderer/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        bg: {
          base:    '#0a0c0f',
        },
        surface: {
          0: '#0f1215',
          1: '#161b22',
          2: '#1c2330',
          3: '#232d3f',
        },
        border: {
          DEFAULT: '#2a3344',
          subtle:  '#1e2738',
          focus:   '#3b82f6',
        },
        text: {
          primary:   '#e2e8f0',
          secondary: '#94a3b8',
          disabled:  '#4a5568',
        },
        brand: {
          DEFAULT: '#3b82f6',
          hover:   '#2563eb',
        },
        buy: {
          DEFAULT: '#22c55e',
          hover:   '#16a34a',
          subtle:  'rgba(34,197,94,0.12)',
        },
        sell: {
          DEFAULT: '#ef4444',
          hover:   '#dc2626',
          subtle:  'rgba(239,68,68,0.12)',
        },
        connected:    '#22c55e',
        connecting:   '#f59e0b',
        reconnecting: '#f97316',
        disconnected: '#ef4444',
      },
      fontFamily: {
        sans: ['Inter', '-apple-system', 'BlinkMacSystemFont', 'sans-serif'],
        mono: ['JetBrains Mono', 'Fira Code', 'Consolas', 'monospace'],
      },
      fontSize: {
        xs:   ['0.625rem', { lineHeight: '1rem' }],     /* 10px */
        sm:   ['0.75rem',  { lineHeight: '1.125rem' }], /* 12px */
        base: ['0.875rem', { lineHeight: '1.375rem' }], /* 14px */
        md:   ['1rem',     { lineHeight: '1.5rem' }],   /* 16px */
        lg:   ['1.125rem', { lineHeight: '1.75rem' }],  /* 18px */
        xl:   ['1.375rem', { lineHeight: '2rem' }],     /* 22px */
        '2xl':['1.75rem',  { lineHeight: '2.25rem' }],  /* 28px */
        '3xl':['2.25rem',  { lineHeight: '2.75rem' }],  /* 36px */
      },
      spacing: {
        '0.5': '0.125rem',
        '1':   '0.25rem',
        '1.5': '0.375rem',
        '2':   '0.5rem',
        '3':   '0.75rem',
        '4':   '1rem',
        '5':   '1.25rem',
        '6':   '1.5rem',
        '8':   '2rem',
        '10':  '2.5rem',
        '12':  '3rem',
        '16':  '4rem',
      },
      borderRadius: {
        sm:   '4px',
        DEFAULT: '6px',
        md:   '6px',
        lg:   '8px',
        xl:   '12px',
      },
      boxShadow: {
        sm:     '0 1px 2px rgba(0,0,0,0.4)',
        md:     '0 4px 6px rgba(0,0,0,0.5)',
        lg:     '0 8px 24px rgba(0,0,0,0.6)',
        xl:     '0 16px 48px rgba(0,0,0,0.75)',
        dialog: '0 20px 60px rgba(0,0,0,0.8), 0 0 0 1px rgba(239,68,68,0.3)',
      },
      animation: {
        'pulse-slow':    'pulse 2s cubic-bezier(0.4,0,0.6,1) infinite',
        'ping-slow':     'ping 1.5s cubic-bezier(0,0,0.2,1) infinite',
        'slide-in-top':  'slideInTop 200ms ease',
        'fade-in':       'fadeIn 150ms ease',
        'border-pulse':  'borderPulse 500ms ease infinite',
      },
      keyframes: {
        slideInTop: {
          '0%':   { transform: 'translateY(-8px)', opacity: '0' },
          '100%': { transform: 'translateY(0)',    opacity: '1' },
        },
        fadeIn: {
          '0%':   { opacity: '0' },
          '100%': { opacity: '1' },
        },
        borderPulse: {
          '0%, 100%': { borderColor: 'rgba(239,68,68,0.4)' },
          '50%':      { borderColor: 'rgba(239,68,68,1)' },
        },
      },
    },
  },
  plugins: [],
};
```

### 6.2 컴포넌트 클래스 패턴 (재사용 유틸리티 조합)

```css
/* renderer/styles/components.css — @layer components 에 배치 */
@layer components {

  /* 버튼 기본 */
  .btn-base {
    @apply inline-flex items-center justify-center gap-2 px-4 py-2
           rounded-md font-medium text-base transition-colors duration-100
           focus:outline-none focus-visible:ring-2 focus-visible:ring-offset-1
           focus-visible:ring-offset-surface-1 disabled:opacity-40
           disabled:cursor-not-allowed;
  }
  .btn-primary {
    @apply btn-base bg-brand hover:bg-brand-hover text-white;
  }
  .btn-buy {
    @apply btn-base bg-buy hover:bg-buy-hover text-white;
  }
  .btn-sell {
    @apply btn-base bg-sell hover:bg-sell-hover text-white;
  }
  .btn-ghost {
    @apply btn-base bg-transparent hover:bg-surface-3 text-text-secondary
           hover:text-text-primary;
  }
  .btn-danger-ghost {
    @apply btn-base bg-transparent hover:bg-sell-subtle text-sell;
  }
  /* TradeConfirmDialog 거절 버튼 */
  .btn-reject {
    @apply btn-base bg-surface-3 hover:bg-surface-2 text-text-secondary;
  }

  /* 입력 필드 */
  .input-base {
    @apply w-full px-3 py-2 rounded-md bg-surface-2 border border-border
           text-text-primary text-base placeholder:text-text-disabled
           focus:outline-none focus:border-border-focus focus:ring-1
           focus:ring-border-focus transition-colors duration-100;
  }
  .input-error {
    @apply input-base border-sell focus:border-sell focus:ring-sell;
  }

  /* 카드 */
  .card {
    @apply rounded-lg bg-surface-1 border border-border p-6;
  }
  .card-sm {
    @apply rounded-md bg-surface-1 border border-border p-4;
  }

  /* 섹션 헤더 */
  .section-header {
    @apply text-md font-semibold text-text-primary mb-4;
  }

  /* 뱃지 */
  .badge-base {
    @apply inline-flex items-center gap-1 px-2 py-0.5 rounded-full
           text-xs font-medium;
  }
  .badge-success  { @apply badge-base bg-buy/20 text-buy; }
  .badge-danger   { @apply badge-base bg-sell/20 text-sell; }
  .badge-warning  { @apply badge-base bg-connecting/20 text-connecting; }
  .badge-neutral  { @apply badge-base bg-surface-3 text-text-secondary; }
  .badge-info     { @apply badge-base bg-brand/20 text-brand; }

  /* BUY/SELL 전용 뱃지 (크게, 신호 피드용) */
  .badge-buy  { @apply badge-base bg-buy-subtle text-buy text-sm px-3 py-1; }
  .badge-sell { @apply badge-base bg-sell-subtle text-sell text-sm px-3 py-1; }

  /* 모드 버튼 (ModeSelector) */
  .mode-tab {
    @apply flex-1 py-2.5 text-sm font-medium rounded-md transition-colors
           duration-100 text-center cursor-pointer;
  }
  .mode-tab-active {
    @apply mode-tab bg-brand text-white;
  }
  .mode-tab-inactive {
    @apply mode-tab bg-surface-2 text-text-secondary hover:bg-surface-3
           hover:text-text-primary;
  }
  .mode-tab-locked {
    @apply mode-tab bg-surface-2 text-text-disabled cursor-not-allowed;
  }

  /* StatusBar 항목 */
  .status-item {
    @apply flex items-center gap-1.5 text-xs;
  }
  .status-dot {
    @apply w-1.5 h-1.5 rounded-full;
  }

  /* 사이드바 네비게이션 링크 */
  .nav-item {
    @apply flex items-center gap-3 px-3 py-2.5 rounded-md text-sm
           text-text-secondary hover:bg-surface-2 hover:text-text-primary
           transition-colors duration-100 cursor-pointer;
  }
  .nav-item-active {
    @apply nav-item bg-surface-2 text-text-primary;
  }

  /* 숫자 데이터 공통 (가격, 수량, 스코어) */
  .num {
    @apply font-mono;
  }
  .num-positive { @apply font-mono text-buy; }
  .num-negative { @apply font-mono text-sell; }
  .num-neutral  { @apply font-mono text-text-secondary; }

  /* 신호 피드 행 */
  .signal-row {
    @apply flex items-center gap-3 px-4 py-3 border-b border-border-subtle
           hover:bg-surface-2 transition-colors duration-100;
  }
  .signal-row-latest {
    @apply signal-row bg-surface-2 animate-slide-in-top;
  }

  /* TradeConfirmDialog */
  .confirm-dialog-overlay {
    @apply fixed inset-0 bg-black/70 flex items-center justify-center
           animate-fade-in;
  }
  .confirm-dialog-card {
    @apply w-96 rounded-xl bg-surface-1 shadow-dialog border border-sell/30
           p-6 animate-slide-in-top;
  }
  /* 5초 이하 경고 상태 */
  .confirm-dialog-card-urgent {
    @apply confirm-dialog-card animate-border-pulse;
  }

  /* ForcedManualBanner */
  .forced-manual-banner {
    @apply w-full px-6 py-2.5 bg-sell/20 border-b border-sell/40
           flex items-center gap-3 text-sm text-sell;
  }

  /* 테이블 */
  .data-table-header {
    @apply text-xs font-medium text-text-disabled uppercase tracking-wide
           px-4 py-2.5 text-left border-b border-border;
  }
  .data-table-row {
    @apply px-4 py-3 text-sm border-b border-border-subtle
           hover:bg-surface-2 transition-colors duration-100;
  }

}
```

---

## 7. 개발 구현 순서 제안

1단계 (P0 기반): AuthPage (로그인 + KIS 설정) → 공통 레이아웃 셸 (TopHeader + LeftSidebar + StatusBar) → ConnectionBadge + StatusBar 상태 표시

2단계 (P0 핵심): ModeSelector → TradeConfirmDialog (SEMI_AUTO 흐름 완성) → ForcedManualBanner → IPC 이벤트 → Zustand store 연결

3단계 (P1): DashboardPage 완성 (PortfolioSummary + 요약 SignalFeed) → TradingRoomPage (SignalFeed 전체 + EmaChart + RawScoreGauge)

4단계 (P1): HistoryPage (테이블 + 필터) → SettingsPage (리스크 파라미터 폼)

---

## 8. 컴포넌트 파일 경로 전체 목록

```
src/renderer/
├── styles/
│   ├── tokens.css          ← CSS 커스텀 속성 (섹션 4.1)
│   ├── components.css      ← @layer components (섹션 6.2)
│   └── global.css          ← base reset + body 기본 스타일
│
├── pages/
│   ├── AuthPage.tsx
│   ├── DashboardPage.tsx
│   ├── TradingRoomPage.tsx
│   ├── HistoryPage.tsx
│   └── SettingsPage.tsx
│
├── components/
│   ├── layout/
│   │   ├── AppLayout.tsx           ← 공통 레이아웃 래퍼 (grid 적용)
│   │   ├── TopHeader.tsx
│   │   ├── LeftSidebar.tsx
│   │   └── StatusBar.tsx
│   │
│   ├── trading/
│   │   ├── TradeConfirmDialog.tsx  ← pendingConfirm 비null 시 렌더링
│   │   ├── SignalFeed.tsx
│   │   ├── SignalFeedRow.tsx
│   │   ├── EmaChart.tsx
│   │   └── RawScoreGauge.tsx
│   │
│   ├── portfolio/
│   │   ├── PortfolioSummary.tsx
│   │   └── HoldingsList.tsx
│   │
│   ├── auth/
│   │   ├── LoginForm.tsx
│   │   └── KisVaultForm.tsx
│   │
│   └── common/
│       ├── ConnectionBadge.tsx
│       ├── ForcedManualBanner.tsx
│       ├── ModeSelector.tsx
│       ├── Badge.tsx
│       ├── CountdownRing.tsx
│       ├── SkeletonRow.tsx
│       └── Tooltip.tsx
```

---

이 스펙 문서를 `docs/trading-terminal-ux-spec.md`에 저장하면 됩니다. 구현 시 추가로 필요한 부분이 있으면 알려주세요.
