# Trading Terminal UI 디자인 개선 스펙

Bloomberg / TradingView 스타일의 프로페셔널 다크 테마. 정보 밀도 최우선, 모든 수치는 모노스페이스, 인터랙션 반응 속도 100ms 이하.

---

## 공통 원칙

- 기존 색상 토큰은 변경하지 않음 (bg-base, surface-0~3, brand, buy, sell, connecting 등)
- 추가 CSS utility는 `global.css` `@layer components` 블록 내에 append
- SVG 아이콘은 24x24 viewBox, strokeWidth 1.5, currentColor 기준
- 모든 transition은 `duration-100` (100ms) — 빠른 반응이 트레이딩 도구의 기본
- focus-visible ring은 `ring-brand ring-offset-[#0f1215]` 통일

---

## 1. LeftSidebar

### 개선 방향

사이드바 상단에 로고+브랜딩 섹션 추가. 유니코드 문자 아이콘을 SVG로 교체. 액티브 탭에 좌측 accent bar + brand 배경 강조.

### 레이아웃 구조

```
[사이드바 200px]
┌──────────────────┐
│  logo section    │  48px (헤더 높이와 정렬)
│  ─────────────── │
│  nav items       │  flex-col gap-0.5
│  (아이콘+라벨)   │
│                  │
│  (flex-1 공백)   │
│  ─────────────── │
│  version badge   │  하단 고정
└──────────────────┘
```

### 로고 섹션

```tsx
// 높이 48px — TopHeader와 정렬
<div className="h-12 flex items-center px-4 border-b border-[#1e2738]">
  <div className="flex items-center gap-2.5">
    {/* EW 로고 마크 — 16x16 SVG */}
    <svg width="20" height="20" viewBox="0 0 20 20" fill="none">
      <rect width="20" height="20" rx="4" fill="#3b82f6" fillOpacity="0.15" />
      <rect x="0.75" y="0.75" width="18.5" height="18.5" rx="3.25"
            stroke="#3b82f6" strokeWidth="1.5" />
      <path d="M5 10 L9 6 L13 10 L9 14 Z"
            fill="#3b82f6" />
    </svg>
    <div className="flex flex-col leading-none">
      <span className="text-text-primary text-xs font-bold tracking-widest uppercase">EW</span>
      <span className="text-text-disabled text-[10px] tracking-wide">Terminal</span>
    </div>
  </div>
</div>
```

### NAV_ITEMS SVG 아이콘 정의

```tsx
// 아이콘 컴포넌트 — strokeWidth 1.5, currentColor
const NAV_ICONS = {
  '/dashboard': (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none"
         stroke="currentColor" strokeWidth="1.5" strokeLinecap="round">
      <rect x="3" y="3" width="7" height="7" rx="1" />
      <rect x="14" y="3" width="7" height="7" rx="1" />
      <rect x="3" y="14" width="7" height="7" rx="1" />
      <rect x="14" y="14" width="7" height="7" rx="1" />
    </svg>
  ),
  '/trading-room': (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none"
         stroke="currentColor" strokeWidth="1.5" strokeLinecap="round">
      <polyline points="2 12 6 6 10 14 14 8 18 16 22 12" />
      <circle cx="22" cy="12" r="1.5" fill="currentColor" stroke="none" className="animate-pulse" />
    </svg>
  ),
  '/history': (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none"
         stroke="currentColor" strokeWidth="1.5" strokeLinecap="round">
      <path d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2" />
      <rect x="9" y="3" width="6" height="4" rx="1" />
      <line x1="9" y1="12" x2="15" y2="12" />
      <line x1="9" y1="16" x2="13" y2="16" />
    </svg>
  ),
  '/settings': (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none"
         stroke="currentColor" strokeWidth="1.5" strokeLinecap="round">
      <circle cx="12" cy="12" r="3" />
      <path d="M19.4 15a1.65 1.65 0 00.33 1.82l.06.06a2 2 0 010 2.83
               2 2 0 01-2.83 0l-.06-.06a1.65 1.65 0 00-1.82-.33
               1.65 1.65 0 00-1 1.51V21a2 2 0 01-4 0v-.09A1.65 1.65 0 009 19.4
               a1.65 1.65 0 00-1.82.33l-.06.06a2 2 0 01-2.83-2.83l.06-.06
               A1.65 1.65 0 004.68 15a1.65 1.65 0 00-1.51-1H3a2 2 0 010-4h.09
               A1.65 1.65 0 004.6 9a1.65 1.65 0 00-.33-1.82l-.06-.06
               a2 2 0 012.83-2.83l.06.06A1.65 1.65 0 009 4.68a1.65 1.65 0 001-1.51V3
               a2 2 0 014 0v.09a1.65 1.65 0 001 1.51 1.65 1.65 0 001.82-.33
               l.06-.06a2 2 0 012.83 2.83l-.06.06A1.65 1.65 0 0019.4 9
               a1.65 1.65 0 001.51 1H21a2 2 0 010 4h-.09
               a1.65 1.65 0 00-1.51 1z" />
    </svg>
  ),
}
```

### nav-item CSS — global.css 교체

```css
/* 기존 nav-item, nav-item-active 대체 */
.nav-item {
  @apply relative flex items-center gap-3 px-3 py-2.5 rounded-md text-sm
         text-text-secondary hover:bg-[#1c2330] hover:text-text-primary
         transition-colors duration-100 cursor-pointer w-full;
}
.nav-item::before {
  content: '';
  @apply absolute left-0 top-1/2 -translate-y-1/2 w-0.5 h-4 rounded-r-full
         bg-brand opacity-0 transition-opacity duration-100;
}
.nav-item-active {
  @apply nav-item bg-[#1c2330] text-text-primary;
}
.nav-item-active::before {
  @apply opacity-100;
}
```

### 전체 LeftSidebar 컴포넌트

```tsx
export default function LeftSidebar({ activePath, onNavigate }: Props) {
  return (
    <nav className="flex flex-col h-full">
      {/* 로고 섹션 */}
      <div className="h-12 flex items-center px-4 border-b border-[#1e2738] shrink-0">
        <div className="flex items-center gap-2.5">
          <svg width="20" height="20" viewBox="0 0 20 20" fill="none">
            <rect width="20" height="20" rx="4" fill="#3b82f6" fillOpacity="0.15" />
            <rect x="0.75" y="0.75" width="18.5" height="18.5" rx="3.25"
                  stroke="#3b82f6" strokeWidth="1.5" />
            <path d="M5 10 L9 6 L13 10 L9 14 Z" fill="#3b82f6" />
          </svg>
          <div className="flex flex-col leading-none">
            <span className="text-text-primary text-xs font-bold tracking-widest uppercase">EW</span>
            <span className="text-text-disabled text-[10px] tracking-wide">Terminal</span>
          </div>
        </div>
      </div>

      {/* 네비게이션 */}
      <div className="flex-1 p-2 flex flex-col gap-0.5 mt-1">
        {NAV_ITEMS.map((item) => (
          <button
            key={item.path}
            className={activePath === item.path ? 'nav-item-active' : 'nav-item'}
            onClick={() => onNavigate(item.path)}
          >
            <span className="w-4 h-4 shrink-0 flex items-center justify-center">
              {NAV_ICONS[item.path]}
            </span>
            <span>{item.label}</span>
          </button>
        ))}
      </div>

      {/* 하단 버전 */}
      <div className="px-4 py-3 border-t border-[#1e2738] shrink-0">
        <span className="num text-[10px] text-text-disabled">v1.0.0</span>
      </div>
    </nav>
  )
}
```

---

## 2. TopHeader

### 개선 방향

좌측: 페이지 타이틀 앞에 breadcrumb-style 앱 이름 구분자 추가. 중앙 영역: 현재 활성 ticker (activeSignal이 있을 때만 표시). 우측: ConnectionBadge 시각 강화 + 닉네임 + 로그아웃.

### 레이아웃

```
[헤더 48px]
┌─────────────────────────────────────────────────────────┐
│  [EW] / [페이지타이틀]   [TICKER 활성표시]   [WS] [KIS] [닉네임] [로그아웃] │
└─────────────────────────────────────────────────────────┘
```

### 컴포넌트 코드

```tsx
// TopHeader.tsx
import { useConnectionStore } from '../../store/useConnectionStore'
import { useUserStore } from '../../store/useUserStore'
import { useTradingStore } from '../../store/useTradingStore'
import { ipc, IPC_CHANNELS } from '../../lib/ipc'

const PAGE_TITLES: Record<string, string> = {
  '/dashboard': '대시보드',
  '/trading-room': '트레이딩 룸',
  '/history': '체결 내역',
  '/settings': '설정',
}

export default function TopHeader({ currentPath }: { currentPath: string }) {
  const { wsStatus, kisTokenStatus } = useConnectionStore()
  const { nickname } = useUserStore()
  const { setAuthenticated } = useConnectionStore()
  const { clear } = useUserStore()
  const { activeSignal } = useTradingStore()

  async function handleLogout() {
    await ipc.invoke(IPC_CHANNELS.AUTH_LOGOUT)
    setAuthenticated(false)
    clear()
  }

  return (
    <header className="h-12 bg-[#0f1215] border-b border-[#2a3344] flex items-center justify-between px-4">
      {/* 좌측: 브레드크럼 타이틀 */}
      <div className="flex items-center gap-2 min-w-0">
        <span className="text-text-disabled text-xs font-medium uppercase tracking-widest shrink-0">EW</span>
        {/* 구분자 */}
        <svg width="12" height="12" viewBox="0 0 12 12" fill="none"
             className="text-[#2a3344] shrink-0">
          <path d="M4 2 L8 6 L4 10" stroke="currentColor" strokeWidth="1.5"
                strokeLinecap="round" strokeLinejoin="round" />
        </svg>
        <span className="text-text-primary text-sm font-semibold truncate">
          {PAGE_TITLES[currentPath] ?? ''}
        </span>
      </div>

      {/* 중앙: 활성 시그널 ticker (트레이딩 룸에서만) */}
      {currentPath === '/trading-room' && activeSignal && (
        <div className="flex items-center gap-2 bg-[#161b22] border border-[#2a3344] rounded-md px-3 py-1">
          <span className="w-1.5 h-1.5 rounded-full bg-buy animate-pulse shrink-0" />
          <span className="num text-sm font-medium text-text-primary">{activeSignal.ticker}</span>
          <span className={`text-xs font-medium num ${activeSignal.action === 'BUY' ? 'text-buy' : 'text-sell'}`}>
            {activeSignal.action}
          </span>
          <span className="num text-xs text-text-disabled">
            {(activeSignal.ema_score * 100).toFixed(0)}
          </span>
        </div>
      )}

      {/* 우측: 상태 + 유저 */}
      <div className="flex items-center gap-3">
        {/* WS 상태 인디케이터 */}
        <HeaderStatusDot
          color={WS_COLOR[wsStatus]}
          label={wsStatus === 'CONNECTED' ? 'WS' : wsStatus === 'RECONNECTING' ? 'WS↻' : 'WS✕'}
          active={wsStatus === 'CONNECTED'}
        />
        {/* KIS 상태 인디케이터 */}
        <HeaderStatusDot
          color={kisTokenStatus === 'VALID' ? '#22c55e' : '#ef4444'}
          label="KIS"
          active={kisTokenStatus === 'VALID'}
        />
        {/* 구분선 */}
        <div className="w-px h-4 bg-[#2a3344]" />
        <span className="text-text-secondary text-xs num">{nickname}</span>
        <button
          className="text-text-disabled hover:text-sell text-xs transition-colors duration-100 px-2 py-1 rounded hover:bg-sell/10"
          onClick={handleLogout}
        >
          로그아웃
        </button>
      </div>
    </header>
  )
}

// 헤더용 소형 상태 도트 + 라벨
function HeaderStatusDot({ color, label, active }: {
  color: string; label: string; active: boolean
}) {
  return (
    <div className="flex items-center gap-1.5">
      <span
        className={`w-1.5 h-1.5 rounded-full ${active ? 'animate-pulse' : ''}`}
        style={{ backgroundColor: color }}
      />
      <span className="text-[10px] font-medium text-text-disabled num">{label}</span>
    </div>
  )
}

const WS_COLOR: Record<string, string> = {
  CONNECTED:    '#22c55e',
  CONNECTING:   '#f59e0b',
  RECONNECTING: '#f97316',
  DISCONNECTED: '#ef4444',
}
```

---

## 3. DashboardPage

### 개선 방향

ModeSelector를 전체 너비 대신 우측 상단 compact 배치. 포트폴리오 카드에 총자산/현금 비율 Progress Bar, 보유종목 행에 현재가+평가손익 표시. 전체 레이아웃 재구성.

### 레이아웃 구조

```
[상단 헤더 행]  제목 + ModeSelector(compact, 우측정렬)
[메인 grid]
  col-span-2: 포트폴리오 카드
  col-span-3: 신호 피드 카드

포트폴리오 카드 내부:
  ┌─ 총자산 (큰 숫자) ────────────────┐
  │  $12,345.67                       │
  │  ────────────────────────────────  │
  │  현금  $8,000.00    [====----] 65% │
  │  평가  $4,345.67    [==------] 35% │
  │  ────────────────────────────────  │
  │  보유종목                          │
  │  NVDA  15주  $125.50  +$250  +1.3% │
  └──────────────────────────────────┘
```

### 핵심 개선 코드

```tsx
// DashboardPage.tsx — 레이아웃 부분

return (
  <div className="flex flex-col gap-4 h-full">
    {/* 헤더 행 */}
    <div className="flex items-center justify-between shrink-0">
      <div>
        <h2 className="text-sm font-semibold text-text-primary">대시보드</h2>
        {lastSyncedAt && (
          <p className="num text-[10px] text-text-disabled mt-0.5">
            마지막 동기화 {new Date(lastSyncedAt * 1000).toLocaleTimeString('ko-KR')}
          </p>
        )}
      </div>
      <div className="flex items-center gap-3">
        <button
          className="flex items-center gap-1.5 text-xs text-text-disabled hover:text-text-primary
                     transition-colors duration-100 px-2 py-1 rounded hover:bg-[#1c2330]"
          onClick={syncBalance}
          disabled={isSyncing}
        >
          {/* 새로고침 아이콘 */}
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none"
               stroke="currentColor" strokeWidth="2" strokeLinecap="round"
               className={isSyncing ? 'animate-spin' : ''}>
            <path d="M21 2v6h-6" /><path d="M3 12a9 9 0 0115-6.7L21 8" />
            <path d="M3 22v-6h6" /><path d="M21 12a9 9 0 01-15 6.7L3 16" />
          </svg>
          {isSyncing ? '동기화 중' : '동기화'}
        </button>
        {/* compact ModeSelector */}
        <ModeSelector currentMode={mode} userPlan={plan} onChange={handleModeChange} size="compact" />
      </div>
    </div>

    {/* 메인 그리드 */}
    <div className="grid grid-cols-5 gap-4 flex-1 min-h-0">
      {/* 포트폴리오 (40%) */}
      <div className="col-span-2 card flex flex-col gap-0 p-0 overflow-hidden">
        <PortfolioCard cash={cash} holdings={holdings} totalAsset={totalAsset} />
      </div>

      {/* 신호 피드 (60%) */}
      <div className="col-span-3 card flex flex-col p-0 overflow-hidden">
        <div className="px-4 py-3 border-b border-[#1e2738] shrink-0 flex items-center justify-between">
          <span className="text-xs font-semibold text-text-primary uppercase tracking-wide">최근 신호</span>
          <span className="num text-[10px] text-text-disabled">최근 {signalHistory.slice(0,5).length}건</span>
        </div>
        <div className="flex-1 overflow-y-auto">
          <SignalFeed items={signalHistory.slice(0, 5)} />
        </div>
      </div>
    </div>
  </div>
)
```

### PortfolioCard 서브컴포넌트

```tsx
// PortfolioCard.tsx (신규 파일: src/renderer/components/portfolio/PortfolioCard.tsx)

interface Holding {
  ticker: string
  qty: number
  currentPrice: number
  avgPrice: number
}

interface Props {
  cash: number
  holdings: Holding[]
  totalAsset: number
}

function AssetBar({ ratio, color }: { ratio: number; color: string }) {
  return (
    <div className="w-full h-1 bg-[#1e2738] rounded-full overflow-hidden">
      <div
        className="h-full rounded-full transition-all duration-500"
        style={{ width: `${Math.min(ratio * 100, 100)}%`, backgroundColor: color }}
      />
    </div>
  )
}

export default function PortfolioCard({ cash, holdings, totalAsset }: Props) {
  const stockValue = holdings.reduce((s, h) => s + h.qty * h.currentPrice, 0)
  const cashRatio = totalAsset > 0 ? cash / totalAsset : 1
  const stockRatio = totalAsset > 0 ? stockValue / totalAsset : 0

  return (
    <div className="flex flex-col h-full">
      {/* 총자산 섹션 */}
      <div className="px-5 pt-5 pb-4 border-b border-[#1e2738]">
        <p className="text-[10px] text-text-disabled uppercase tracking-widest mb-1">총 자산 (USD)</p>
        <p className="num text-2xl font-bold text-text-primary">
          ${totalAsset.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
        </p>
      </div>

      {/* 현금/평가 섹션 */}
      <div className="px-5 py-4 border-b border-[#1e2738] flex flex-col gap-3">
        {/* 현금 */}
        <div>
          <div className="flex items-center justify-between mb-1.5">
            <span className="text-[10px] text-text-disabled uppercase tracking-wide">현금</span>
            <div className="flex items-center gap-2">
              <span className="num text-sm text-text-primary">
                ${cash.toLocaleString('en-US', { minimumFractionDigits: 2 })}
              </span>
              <span className="num text-[10px] text-text-disabled">
                {(cashRatio * 100).toFixed(0)}%
              </span>
            </div>
          </div>
          <AssetBar ratio={cashRatio} color="#3b82f6" />
        </div>
        {/* 주식 평가금액 */}
        <div>
          <div className="flex items-center justify-between mb-1.5">
            <span className="text-[10px] text-text-disabled uppercase tracking-wide">평가</span>
            <div className="flex items-center gap-2">
              <span className="num text-sm text-text-primary">
                ${stockValue.toLocaleString('en-US', { minimumFractionDigits: 2 })}
              </span>
              <span className="num text-[10px] text-text-disabled">
                {(stockRatio * 100).toFixed(0)}%
              </span>
            </div>
          </div>
          <AssetBar ratio={stockRatio} color="#22c55e" />
        </div>
      </div>

      {/* 보유 종목 */}
      {holdings.length > 0 ? (
        <div className="flex-1 overflow-y-auto">
          <div className="px-5 pt-3 pb-1">
            <span className="text-[10px] text-text-disabled uppercase tracking-widest">보유 종목</span>
          </div>
          {holdings.map((h) => {
            const evalValue = h.qty * h.currentPrice
            const pnl = (h.currentPrice - h.avgPrice) * h.qty
            const pnlPct = h.avgPrice > 0 ? ((h.currentPrice - h.avgPrice) / h.avgPrice) * 100 : 0
            const isPositive = pnl >= 0
            return (
              <div key={h.ticker}
                   className="flex items-center justify-between px-5 py-2.5
                              border-b border-[#1e2738] last:border-b-0
                              hover:bg-[#1c2330] transition-colors duration-100">
                <div>
                  <p className="num text-sm font-semibold text-text-primary">{h.ticker}</p>
                  <p className="num text-[10px] text-text-disabled">{h.qty}주 @ ${h.avgPrice.toFixed(2)}</p>
                </div>
                <div className="text-right">
                  <p className="num text-sm text-text-primary">
                    ${evalValue.toLocaleString('en-US', { minimumFractionDigits: 2 })}
                  </p>
                  <p className={`num text-[10px] ${isPositive ? 'text-buy' : 'text-sell'}`}>
                    {isPositive ? '+' : ''}{pnl.toFixed(2)} ({isPositive ? '+' : ''}{pnlPct.toFixed(2)}%)
                  </p>
                </div>
              </div>
            )
          })}
        </div>
      ) : (
        <div className="flex-1 flex items-center justify-center">
          <span className="text-text-disabled text-xs">보유 종목 없음</span>
        </div>
      )}
    </div>
  )
}
```

---

## 4. TradingRoomPage

### 개선 방향

- 상단 바: 좌측에 LiveIndicator (점 깜빡임 + "LIVE"), 우측에 compact ModeSelector
- EMA 차트 카드 헤더에 현재 EMA Score 수치 인라인 표시 → 차트와 게이지 시각 연계
- RawScoreGauge를 우측 신호 피드 카드 하단에 병합 (별도 카드 제거) — 세로 공간 확보
- 게이지 옆에 현재 시그널의 BUY/SELL 방향 텍스트 강조

### 레이아웃 구조

```
[상단 행 44px]  LIVE 인디케이터 + ticker | ModeSelector
[grid flex-1]
  col-span-3 (차트 카드):
    헤더: "EMA 추세" | score badge | ticker
    차트 flex-1
  col-span-2 (신호+게이지 카드):
    헤더: "신호 피드"
    신호 피드 flex-1 overflow-y-auto
    ─────────────────
    RawScoreGauge h-28 (하단 고정 섹션)
```

### 컴포넌트 코드

```tsx
// TradingRoomPage.tsx

return (
  <div className="flex flex-col gap-3 h-full">
    {/* 상단 바 */}
    <div className="flex items-center justify-between shrink-0 h-9">
      <div className="flex items-center gap-3">
        {/* LIVE 인디케이터 */}
        <div className="flex items-center gap-2 bg-buy/10 border border-buy/20
                        rounded-md px-3 py-1.5">
          <span className="w-2 h-2 rounded-full bg-buy animate-pulse" />
          <span className="text-buy text-xs font-bold tracking-widest">LIVE</span>
        </div>
        {/* 활성 ticker */}
        {activeSignal && (
          <span className="num text-sm font-semibold text-text-primary">{activeSignal.ticker}</span>
        )}
      </div>
      <div className="w-72">
        <ModeSelector currentMode={mode} userPlan={plan} onChange={handleModeChange} size="compact" />
      </div>
    </div>

    {/* 메인 그리드 */}
    <div className="grid grid-cols-5 gap-3 flex-1 min-h-0">
      {/* 차트 (60%) */}
      <div className="col-span-3 card p-0 flex flex-col overflow-hidden">
        {/* 차트 헤더 */}
        <div className="px-4 py-3 border-b border-[#1e2738] flex items-center justify-between shrink-0">
          <div className="flex items-center gap-2">
            <span className="text-xs font-semibold text-text-primary uppercase tracking-wide">EMA 추세</span>
            {activeSignal && (
              <span className={`num text-xs font-medium px-1.5 py-0.5 rounded
                              ${activeSignal.action === 'BUY'
                                ? 'bg-buy/15 text-buy'
                                : 'bg-sell/15 text-sell'}`}>
                {(activeSignal.ema_score * 100).toFixed(1)}
              </span>
            )}
          </div>
          {activeSignal && (
            <span className="num text-[10px] text-text-disabled">{activeSignal.ticker}</span>
          )}
        </div>
        <div className="flex-1 min-h-0 p-3">
          <EmaChart signalHistory={signalHistory} />
        </div>
      </div>

      {/* 신호 피드 + 게이지 (40%) */}
      <div className="col-span-2 card p-0 flex flex-col overflow-hidden">
        {/* 신호 피드 헤더 */}
        <div className="px-4 py-3 border-b border-[#1e2738] shrink-0 flex items-center justify-between">
          <span className="text-xs font-semibold text-text-primary uppercase tracking-wide">신호 피드</span>
          <span className="num text-[10px] text-text-disabled">{signalHistory.length}건</span>
        </div>

        {/* 신호 목록 */}
        <div className="flex-1 overflow-y-auto min-h-0">
          <SignalFeed items={signalHistory} />
        </div>

        {/* 게이지 섹션 — 하단 고정 */}
        <div className="shrink-0 border-t border-[#1e2738] px-4 py-3">
          <div className="flex items-center gap-4">
            {/* 게이지 */}
            <div className="w-24 h-24 shrink-0">
              <RawScoreGauge score={activeSignal?.ema_score ?? null} />
            </div>
            {/* 수치 + 방향 텍스트 */}
            <div className="flex flex-col gap-1.5">
              <div>
                <p className="text-[10px] text-text-disabled uppercase tracking-wide">EMA Score</p>
                <p className={`num text-2xl font-bold ${getScoreColor(activeSignal?.ema_score ?? null)}`}>
                  {activeSignal ? (activeSignal.ema_score * 100).toFixed(0) : '--'}
                </p>
              </div>
              {activeSignal && (
                <div className={`inline-flex items-center gap-1.5 text-xs font-semibold px-2 py-1 rounded
                                ${activeSignal.action === 'BUY'
                                  ? 'bg-buy/15 text-buy'
                                  : 'bg-sell/15 text-sell'}`}>
                  <span>{activeSignal.action === 'BUY' ? '▲' : '▼'}</span>
                  <span>{activeSignal.action}</span>
                  <span className="num font-normal text-text-disabled">x{activeSignal.target_qty}</span>
                </div>
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
)

// 점수 색상 헬퍼
function getScoreColor(score: number | null): string {
  if (score === null) return 'text-text-disabled'
  if (score <= 0.4) return 'text-sell'
  if (score <= 0.6) return 'text-connecting'
  return 'text-buy'
}
```

---

## 5. HistoryPage

### 개선 방향

- 테이블 헤더 sticky, 행 hover 시 왼쪽 accent 라인
- BUY/SELL 방향에 색상 아이콘(▲/▼) 추가
- 상태 badge에 아이콘 추가 (체결: 체크, 실패: X)
- 하단 페이지네이션 컴포넌트
- 상단에 간단한 집계 요약 행 (오늘 총 체결, BUY/SELL 건수)

### 레이아웃

```
[요약 행]  오늘 체결 n건 | BUY n건 | SELL n건 | [새로고침]
[테이블 카드]
  sticky thead
  tbody — 행 hover left-accent
[페이지네이션]  < 1 2 3 ... > / 20건 표시
```

### 페이지네이션 컴포넌트

```tsx
// Pagination.tsx (신규: src/renderer/components/common/Pagination.tsx)

interface PaginationProps {
  page: number          // 0-indexed
  totalPages: number
  onPageChange: (page: number) => void
}

export default function Pagination({ page, totalPages, onPageChange }: PaginationProps) {
  if (totalPages <= 1) return null

  const pages = Array.from({ length: Math.min(totalPages, 7) }, (_, i) => i)

  return (
    <div className="flex items-center justify-center gap-1 py-3">
      <button
        className="pagination-btn"
        disabled={page === 0}
        onClick={() => onPageChange(page - 1)}
      >
        {/* chevron-left */}
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none"
             stroke="currentColor" strokeWidth="2" strokeLinecap="round">
          <path d="M15 18l-6-6 6-6" />
        </svg>
      </button>

      {pages.map((p) => (
        <button
          key={p}
          className={p === page ? 'pagination-btn-active' : 'pagination-btn'}
          onClick={() => onPageChange(p)}
        >
          {p + 1}
        </button>
      ))}

      <button
        className="pagination-btn"
        disabled={page >= totalPages - 1}
        onClick={() => onPageChange(page + 1)}
      >
        {/* chevron-right */}
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none"
             stroke="currentColor" strokeWidth="2" strokeLinecap="round">
          <path d="M9 18l6-6-6-6" />
        </svg>
      </button>
    </div>
  )
}
```

### HistoryPage 전체

```tsx
// HistoryPage.tsx — state 추가 및 레이아웃 개선

const [page, setPage] = useState(0)
const [totalPages, setTotalPages] = useState(0)
const PAGE_SIZE = 20

// loadTrades에 page 파라미터 연동
async function loadTrades(p = page) {
  setLoading(true)
  try {
    const data = await ipc.invoke<{ content: Trade[]; totalPages: number }>(
      IPC_CHANNELS.TRADES_GET, { page: p, size: PAGE_SIZE }
    )
    setTrades(data.content ?? [])
    setTotalPages(data.totalPages ?? 0)
  } catch (e) {
    console.error('거래 내역 조회 실패:', e)
  } finally {
    setLoading(false)
  }
}

// 집계
const todayTrades = trades.filter((t) => {
  const d = new Date(t.createdAt)
  const now = new Date()
  return d.getFullYear() === now.getFullYear()
    && d.getMonth() === now.getMonth()
    && d.getDate() === now.getDate()
})
const buyCount = todayTrades.filter((t) => t.side === 'BUY').length
const sellCount = todayTrades.filter((t) => t.side === 'SELL').length

return (
  <div className="flex flex-col gap-3 h-full">
    {/* 요약 + 헤더 */}
    <div className="flex items-center justify-between shrink-0">
      <div className="flex items-center gap-4">
        <span className="text-sm font-semibold text-text-primary">체결 내역</span>
        <div className="flex items-center gap-3">
          <SummaryChip label="오늘 체결" value={todayTrades.length} color="text-text-secondary" />
          <SummaryChip label="BUY" value={buyCount} color="text-buy" />
          <SummaryChip label="SELL" value={sellCount} color="text-sell" />
        </div>
      </div>
      <button
        className="flex items-center gap-1.5 text-xs text-text-disabled hover:text-text-primary
                   transition-colors duration-100 px-2 py-1 rounded hover:bg-[#1c2330]"
        onClick={() => loadTrades(page)}
      >
        <svg width="12" height="12" viewBox="0 0 24 24" fill="none"
             stroke="currentColor" strokeWidth="2" strokeLinecap="round">
          <path d="M21 2v6h-6" /><path d="M3 12a9 9 0 0115-6.7L21 8" />
          <path d="M3 22v-6h6" /><path d="M21 12a9 9 0 01-15 6.7L3 16" />
        </svg>
        새로고침
      </button>
    </div>

    {/* 테이블 */}
    <div className="card p-0 overflow-hidden flex flex-col flex-1 min-h-0">
      <div className="overflow-y-auto flex-1">
        <table className="w-full">
          <thead className="sticky top-0 z-10 bg-[#161b22]">
            <tr className="border-b border-[#2a3344]">
              {[
                { label: '일시',     cls: 'w-36' },
                { label: '종목',     cls: 'w-20' },
                { label: '방향',     cls: 'w-20' },
                { label: '수량',     cls: 'w-16 text-right' },
                { label: '체결가',   cls: 'w-24 text-right' },
                { label: '상태',     cls: 'w-20' },
              ].map(({ label, cls }) => (
                <th key={label}
                    className={`px-4 py-2.5 text-left text-[10px] font-semibold
                               text-text-disabled uppercase tracking-widest ${cls}`}>
                  {label}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {loading ? (
              Array.from({ length: 8 }).map((_, i) => (
                <tr key={i} className="border-b border-[#1e2738]">
                  {Array.from({ length: 6 }).map((_, j) => (
                    <td key={j} className="px-4 py-3">
                      <div className={`h-3.5 bg-[#1c2330] rounded animate-pulse ${j === 0 ? 'w-28' : j === 1 ? 'w-12' : 'w-16'}`} />
                    </td>
                  ))}
                </tr>
              ))
            ) : trades.length === 0 ? (
              <tr>
                <td colSpan={6} className="px-4 py-12 text-center text-text-disabled text-xs">
                  체결 내역이 없습니다
                </td>
              </tr>
            ) : (
              trades.map((t) => (
                <tr key={t.id}
                    className="table-row-accent border-b border-[#1e2738]
                               hover:bg-[#1c2330] transition-colors duration-100">
                  <td className="px-4 py-3 num text-xs text-text-secondary">
                    {new Date(t.createdAt).toLocaleString('ko-KR')}
                  </td>
                  <td className="px-4 py-3 num text-sm font-semibold text-text-primary">
                    {t.ticker}
                  </td>
                  <td className="px-4 py-3">
                    <span className={`inline-flex items-center gap-1 text-xs font-semibold
                                    ${t.side === 'BUY' ? 'text-buy' : 'text-sell'}`}>
                      <span>{t.side === 'BUY' ? '▲' : '▼'}</span>
                      {t.side}
                    </span>
                  </td>
                  <td className="px-4 py-3 num text-sm text-text-primary text-right">
                    {t.executedQty}
                  </td>
                  <td className="px-4 py-3 num text-sm text-text-primary text-right">
                    {t.executedPrice != null ? `$${t.executedPrice.toFixed(2)}` : '-'}
                  </td>
                  <td className="px-4 py-3">
                    <StatusBadge status={t.status} />
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>

      {/* 페이지네이션 */}
      <div className="shrink-0 border-t border-[#1e2738]">
        <Pagination page={page} totalPages={totalPages}
                    onPageChange={(p) => { setPage(p); loadTrades(p) }} />
      </div>
    </div>
  </div>
)

// 요약 chip
function SummaryChip({ label, value, color }: { label: string; value: number; color: string }) {
  return (
    <div className="flex items-center gap-1.5 bg-[#161b22] border border-[#2a3344]
                    rounded px-2.5 py-1">
      <span className="text-[10px] text-text-disabled">{label}</span>
      <span className={`num text-xs font-semibold ${color}`}>{value}</span>
    </div>
  )
}

// 상태 badge with icon
function StatusBadge({ status }: { status: string }) {
  if (status === 'EXECUTED') {
    return (
      <span className="inline-flex items-center gap-1 text-xs font-medium text-buy">
        <svg width="12" height="12" viewBox="0 0 24 24" fill="none"
             stroke="currentColor" strokeWidth="2.5" strokeLinecap="round">
          <polyline points="20 6 9 17 4 12" />
        </svg>
        체결
      </span>
    )
  }
  return (
    <span className="inline-flex items-center gap-1 text-xs font-medium text-sell">
      <svg width="12" height="12" viewBox="0 0 24 24" fill="none"
           stroke="currentColor" strokeWidth="2.5" strokeLinecap="round">
        <line x1="18" y1="6" x2="6" y2="18" />
        <line x1="6" y1="6" x2="18" y2="18" />
      </svg>
      실패
    </span>
  )
}
```

---

## 6. SettingsPage

### 개선 방향

- 섹션 헤더에 아이콘 + 설명 텍스트 추가
- 슬라이더 방식 대신 input + 시각적 비율 바 병행 (기존 input 유지, 하단에 bar 추가)
- KIS 연동 카드에 상태 타임라인 표시 (API키 등록 → 토큰 발급 → 유효)
- 저장 완료 피드백을 토스트 스타일로 (현재 버튼 텍스트 변경 방식 유지하되 시각 강화)
- 전체 너비를 max-w-2xl로 좁히고 세로 레이아웃으로 재구성 (grid-cols-2 유지 가능)

### 컴포넌트 코드

```tsx
// SettingsPage.tsx

return (
  <div className="flex flex-col gap-4 max-w-2xl">
    {/* 섹션: 리스크 파라미터 */}
    <section className="card p-0 overflow-hidden">
      {/* 섹션 헤더 */}
      <div className="px-5 py-4 border-b border-[#1e2738] flex items-center gap-3">
        <div className="w-7 h-7 rounded-md bg-brand/10 border border-brand/20
                        flex items-center justify-center shrink-0">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none"
               stroke="#3b82f6" strokeWidth="1.5" strokeLinecap="round">
            <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" />
          </svg>
        </div>
        <div>
          <p className="text-sm font-semibold text-text-primary">리스크 파라미터</p>
          <p className="text-[10px] text-text-disabled mt-0.5">자동 매매 시 적용되는 위험 관리 규칙</p>
        </div>
      </div>

      <form onSubmit={handleSave} className="px-5 py-5 flex flex-col gap-5">
        {/* 1회 매수 비율 */}
        <RatioField
          label="1회 매수 비율"
          description="신호 1건당 현금의 최대 사용 비율"
          value={form.maxBuyRatio}
          onChange={(v) => setForm({ ...form, maxBuyRatio: v })}
          min={0} max={1} step={0.01}
          color="#3b82f6"
        />

        {/* 최대 보유 비중 */}
        <RatioField
          label="최대 보유 비중"
          description="단일 종목의 포트폴리오 최대 비중"
          value={form.maxHoldingRatio}
          onChange={(v) => setForm({ ...form, maxHoldingRatio: v })}
          min={0} max={1} step={0.01}
          color="#22c55e"
        />

        {/* 쿨다운 */}
        <div className="flex flex-col gap-1.5">
          <div className="flex items-center justify-between">
            <div>
              <p className="text-sm text-text-primary">쿨다운</p>
              <p className="text-[10px] text-text-disabled mt-0.5">동일 종목 연속 매매 대기 시간</p>
            </div>
            <div className="flex items-center gap-2">
              <input
                className="input-base w-20 text-right"
                type="number" min={0} max={60}
                value={form.cooldownMinutes}
                onChange={(e) => setForm({ ...form, cooldownMinutes: Number(e.target.value) })}
              />
              <span className="text-text-disabled text-xs">분</span>
            </div>
          </div>
        </div>

        <div className="pt-1">
          <button
            type="submit"
            className={`btn-primary w-full transition-all duration-200
                        ${saved ? 'bg-buy hover:bg-buy' : ''}`}
            disabled={saving}
          >
            {saved ? (
              <span className="flex items-center gap-2">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none"
                     stroke="currentColor" strokeWidth="2.5" strokeLinecap="round">
                  <polyline points="20 6 9 17 4 12" />
                </svg>
                저장됨
              </span>
            ) : saving ? '저장 중...' : '저장'}
          </button>
        </div>
      </form>
    </section>

    {/* 섹션: KIS 연동 */}
    <section className="card p-0 overflow-hidden">
      <div className="px-5 py-4 border-b border-[#1e2738] flex items-center gap-3">
        <div className="w-7 h-7 rounded-md bg-[#1c2330] border border-[#2a3344]
                        flex items-center justify-center shrink-0">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none"
               stroke="#94a3b8" strokeWidth="1.5" strokeLinecap="round">
            <rect x="2" y="5" width="20" height="14" rx="2" />
            <line x1="2" y1="10" x2="22" y2="10" />
          </svg>
        </div>
        <div>
          <p className="text-sm font-semibold text-text-primary">KIS 연동</p>
          <p className="text-[10px] text-text-disabled mt-0.5">한국투자증권 Open API 연결 상태</p>
        </div>
      </div>

      <div className="px-5 py-5 flex flex-col gap-4">
        {/* 상태 타임라인 */}
        <div className="flex items-center gap-0">
          <KisStep
            done={hasCredentials}
            label="API 키"
            sublabel={hasCredentials ? '등록됨' : '미등록'}
          />
          <div className={`flex-1 h-px mx-2 ${hasCredentials ? 'bg-brand' : 'bg-[#2a3344]'}`} />
          <KisStep
            done={kisTokenStatus === 'VALID'}
            label="토큰"
            sublabel={kisTokenStatus === 'VALID' ? '유효' : kisTokenStatus === 'EXPIRED' ? '만료' : '미발급'}
          />
          <div className={`flex-1 h-px mx-2 ${kisTokenStatus === 'VALID' ? 'bg-buy' : 'bg-[#2a3344]'}`} />
          <KisStep
            done={hasCredentials && kisTokenStatus === 'VALID'}
            label="연결"
            sublabel={hasCredentials && kisTokenStatus === 'VALID' ? '정상' : '대기'}
            isLast
          />
        </div>

        {/* 액션 버튼 */}
        <div className="grid grid-cols-2 gap-3 mt-1">
          <button className="btn-ghost text-sm" onClick={handleIssueToken}>
            토큰 재발급
          </button>
          <button
            className="btn-danger-ghost text-sm"
            onClick={handleDeleteCredentials}
            disabled={!hasCredentials}
          >
            API 키 삭제
          </button>
        </div>
      </div>
    </section>
  </div>
)

// 비율 입력 필드 — input + 시각 바
function RatioField({ label, description, value, onChange, min, max, step, color }: {
  label: string; description: string; value: number
  onChange: (v: number) => void; min: number; max: number; step: number; color: string
}) {
  return (
    <div className="flex flex-col gap-2">
      <div className="flex items-center justify-between">
        <div>
          <p className="text-sm text-text-primary">{label}</p>
          <p className="text-[10px] text-text-disabled mt-0.5">{description}</p>
        </div>
        <div className="flex items-center gap-2">
          <input
            className="input-base w-20 text-right"
            type="number" min={min} max={max} step={step}
            value={value}
            onChange={(e) => onChange(Number(e.target.value))}
          />
          <span className="num text-xs text-text-disabled w-8 text-right">
            {(value * 100).toFixed(0)}%
          </span>
        </div>
      </div>
      {/* 비율 바 */}
      <div className="w-full h-1 bg-[#1e2738] rounded-full overflow-hidden">
        <div
          className="h-full rounded-full transition-all duration-300"
          style={{ width: `${Math.min(value * 100, 100)}%`, backgroundColor: color }}
        />
      </div>
    </div>
  )
}

// KIS 상태 타임라인 스텝
function KisStep({ done, label, sublabel, isLast = false }: {
  done: boolean; label: string; sublabel: string; isLast?: boolean
}) {
  return (
    <div className="flex flex-col items-center gap-1.5">
      <div className={`w-7 h-7 rounded-full flex items-center justify-center text-xs border
                      transition-colors duration-200
                      ${done
                        ? 'bg-buy/15 border-buy/40 text-buy'
                        : 'bg-[#1c2330] border-[#2a3344] text-text-disabled'}`}>
        {done ? (
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none"
               stroke="currentColor" strokeWidth="2.5" strokeLinecap="round">
            <polyline points="20 6 9 17 4 12" />
          </svg>
        ) : (
          <span className="w-1.5 h-1.5 rounded-full bg-current" />
        )}
      </div>
      <div className="text-center">
        <p className="text-[10px] font-medium text-text-secondary">{label}</p>
        <p className={`text-[10px] num ${done ? 'text-buy' : 'text-text-disabled'}`}>{sublabel}</p>
      </div>
    </div>
  )
}
```

---

## 7. StatusBar

### 개선 방향

기존 3개 항목에 추가 정보 삽입. 좌측부터 순서: WS상태 | KIS상태 | 구분선 | 현재 모드 | 구분선 | 마지막 신호 시간 | (우측 정렬) 현재 시간

### 레이아웃

```
[32px 하단 바]
┌──────────────────────────────────────────────────────────────────┐
│ ● WS 연결됨  ● KIS 유효  │  자동 (Auto-Pilot)  │  마지막: 14:32:05  ⟶  14:33:21 │
└──────────────────────────────────────────────────────────────────┘
```

### 컴포넌트 코드

```tsx
// StatusBar.tsx

import { useEffect, useState } from 'react'
import { useConnectionStore } from '../../store/useConnectionStore'
import { useTradingStore } from '../../store/useTradingStore'

const WS_CONFIG: Record<string, { label: string; color: string }> = {
  CONNECTED:    { label: 'WS',     color: '#22c55e' },
  CONNECTING:   { label: 'WS...',  color: '#f59e0b' },
  RECONNECTING: { label: 'WS↻',   color: '#f97316' },
  DISCONNECTED: { label: 'WS✕',   color: '#ef4444' },
}

const KIS_CONFIG: Record<string, { label: string; color: string }> = {
  VALID:   { label: 'KIS',  color: '#22c55e' },
  EXPIRED: { label: 'KIS✕', color: '#ef4444' },
  UNKNOWN: { label: 'KIS?', color: '#64748b' },
}

const MODE_CONFIG: Record<string, { label: string; color: string }> = {
  MANUAL:     { label: 'MANUAL',     color: '#94a3b8' },
  SEMI_AUTO:  { label: '1-CLICK',    color: '#f59e0b' },
  AUTO_PILOT: { label: 'AUTO-PILOT', color: '#22c55e' },
}

export default function StatusBar() {
  const { wsStatus, kisTokenStatus } = useConnectionStore()
  const { mode, signalHistory } = useTradingStore()
  const [now, setNow] = useState(new Date())

  useEffect(() => {
    const id = setInterval(() => setNow(new Date()), 1000)
    return () => clearInterval(id)
  }, [])

  const ws = WS_CONFIG[wsStatus] ?? WS_CONFIG.DISCONNECTED
  const kis = KIS_CONFIG[kisTokenStatus] ?? KIS_CONFIG.UNKNOWN
  const modeConf = MODE_CONFIG[mode] ?? MODE_CONFIG.MANUAL
  const lastSignal = signalHistory[0]

  return (
    <footer className="h-8 bg-[#0f1215] border-t border-[#2a3344]
                       flex items-center px-4 gap-0">
      {/* WS 상태 */}
      <StatusItem color={ws.color} label={ws.label} pulse={wsStatus === 'CONNECTED'} />
      <StatusDivider />

      {/* KIS 상태 */}
      <StatusItem color={kis.color} label={kis.label} pulse={kisTokenStatus === 'VALID'} />
      <StatusDivider />

      {/* 현재 모드 */}
      <div className="flex items-center gap-1.5 px-2">
        <span className="text-text-disabled text-[10px] uppercase tracking-wide">MODE</span>
        <span
          className="num text-[10px] font-bold tracking-widest"
          style={{ color: modeConf.color }}
        >
          {modeConf.label}
        </span>
      </div>

      {/* 마지막 신호 */}
      {lastSignal && (
        <>
          <StatusDivider />
          <div className="flex items-center gap-1.5 px-2">
            <span className="text-text-disabled text-[10px]">신호</span>
            <span className={`num text-[10px] font-semibold ${lastSignal.action === 'BUY' ? 'text-buy' : 'text-sell'}`}>
              {lastSignal.ticker} {lastSignal.action}
            </span>
            <span className="num text-[10px] text-text-disabled">
              {new Date(lastSignal.receivedAt * 1000).toLocaleTimeString('ko-KR')}
            </span>
          </div>
        </>
      )}

      {/* 오른쪽 정렬 — 현재 시간 */}
      <div className="ml-auto flex items-center">
        <span className="num text-[10px] text-text-disabled">
          {now.toLocaleTimeString('ko-KR')}
        </span>
      </div>
    </footer>
  )
}

function StatusItem({ color, label, pulse }: { color: string; label: string; pulse?: boolean }) {
  return (
    <div className="flex items-center gap-1.5 px-2">
      <span
        className={`w-1.5 h-1.5 rounded-full ${pulse ? 'animate-pulse' : ''}`}
        style={{ backgroundColor: color }}
      />
      <span className="num text-[10px] font-medium" style={{ color }}>
        {label}
      </span>
    </div>
  )
}

function StatusDivider() {
  return <span className="w-px h-3 bg-[#2a3344] mx-1" />
}
```

---

## 8. ModeSelector

### 개선 방향

3개 모드 각각에 위험도/특성을 시각화하는 색상 체계와 아이콘 적용:

- **MANUAL**: 중립 (현재 border/text 스타일 그대로) — 방패 아이콘
- **SEMI_AUTO**: 주의 (amber/connecting) — 번개 아이콘
- **AUTO_PILOT**: 위험(활성), 잠김 — 로켓 아이콘 + Pro 뱃지

각 탭: 상단에 아이콘, 아래에 라벨, 활성 상태에 해당 색상 border-top accent.

### CSS — global.css 교체

```css
/* 기존 mode-tab-* 클래스 교체 */
.mode-tab {
  @apply relative flex-1 flex flex-col items-center justify-center gap-1
         py-2 px-2 rounded-md text-xs font-medium
         transition-all duration-100 cursor-pointer
         border border-transparent;
}
.mode-tab-manual-active {
  @apply mode-tab bg-[#1c2330] text-text-primary border-[#2a3344];
}
.mode-tab-manual-inactive {
  @apply mode-tab bg-transparent text-text-secondary
         hover:bg-[#1c2330] hover:text-text-primary;
}
.mode-tab-semi-active {
  @apply mode-tab bg-connecting/10 text-connecting border-connecting/30;
}
.mode-tab-semi-inactive {
  @apply mode-tab bg-transparent text-text-secondary
         hover:bg-connecting/10 hover:text-connecting;
}
.mode-tab-auto-active {
  @apply mode-tab bg-buy/10 text-buy border-buy/30;
}
.mode-tab-auto-inactive {
  @apply mode-tab bg-transparent text-text-secondary
         hover:bg-buy/10 hover:text-buy;
}
.mode-tab-locked {
  @apply mode-tab bg-transparent text-text-disabled cursor-not-allowed;
}
```

### ModeSelector 컴포넌트 코드

```tsx
// ModeSelector.tsx

const MODE_CONFIG = {
  MANUAL: {
    label: '수동',
    sublabel: 'Manual',
    proOnly: false,
    icon: (
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none"
           stroke="currentColor" strokeWidth="1.5" strokeLinecap="round">
        <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" />
      </svg>
    ),
    activeClass: 'mode-tab-manual-active',
    inactiveClass: 'mode-tab-manual-inactive',
  },
  SEMI_AUTO: {
    label: '1-Click',
    sublabel: 'Semi-Auto',
    proOnly: false,
    icon: (
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none"
           stroke="currentColor" strokeWidth="1.5" strokeLinecap="round">
        <polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2" />
      </svg>
    ),
    activeClass: 'mode-tab-semi-active',
    inactiveClass: 'mode-tab-semi-inactive',
  },
  AUTO_PILOT: {
    label: '자동',
    sublabel: 'Auto-Pilot',
    proOnly: true,
    icon: (
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none"
           stroke="currentColor" strokeWidth="1.5" strokeLinecap="round">
        <path d="M12 2L8.5 8.5H3L7.5 13l-2 7 6.5-4 6.5 4-2-7L20.5 8.5H15L12 2z" />
      </svg>
    ),
    activeClass: 'mode-tab-auto-active',
    inactiveClass: 'mode-tab-auto-inactive',
  },
}

export default function ModeSelector({ currentMode, userPlan, onChange, size = 'full' }: Props) {
  const wsStatus = useConnectionStore((s) => s.wsStatus)
  const isDisconnected = wsStatus === 'DISCONNECTED'

  return (
    <div className={`flex gap-1.5 ${
      size === 'full'
        ? 'p-3 bg-[#161b22] rounded-lg border border-[#2a3344]'
        : ''
    }`}>
      {(Object.entries(MODE_CONFIG) as [TradingMode, typeof MODE_CONFIG[keyof typeof MODE_CONFIG]][])
        .map(([value, conf]) => {
          const isLocked = conf.proOnly && userPlan !== 'PRO'
          const isActive = currentMode === value
          const isDisabled = isDisconnected && value !== 'MANUAL'

          let cls = conf.inactiveClass
          if (isActive) cls = conf.activeClass
          if (isLocked || isDisabled) cls = 'mode-tab-locked'

          return (
            <button
              key={value}
              className={cls}
              disabled={isLocked || isDisabled}
              title={
                isLocked
                  ? 'Pro 플랜에서 사용 가능합니다'
                  : isDisabled
                    ? '백엔드 연결 복구 후 전환 가능합니다'
                    : undefined
              }
              onClick={() => !isLocked && !isDisabled && onChange(value)}
            >
              <span className="opacity-80">{conf.icon}</span>
              <span className="text-[10px] leading-none">{conf.label}</span>
              {size === 'full' && (
                <span className="text-[9px] opacity-50 leading-none">{conf.sublabel}</span>
              )}
              {isLocked && (
                <span className="absolute top-1 right-1">
                  <svg width="8" height="8" viewBox="0 0 24 24" fill="none"
                       stroke="currentColor" strokeWidth="2.5" strokeLinecap="round">
                    <rect x="3" y="11" width="18" height="11" rx="2" />
                    <path d="M7 11V7a5 5 0 0110 0v4" />
                  </svg>
                </span>
              )}
            </button>
          )
        })}
    </div>
  )
}
```

---

## global.css 추가 항목

기존 `global.css`에 `@layer components` 블록 내 append:

```css
/* HistoryPage 테이블 행 left accent */
.table-row-accent {
  position: relative;
}
.table-row-accent::before {
  content: '';
  @apply absolute left-0 top-0 bottom-0 w-0 bg-brand opacity-0
         transition-all duration-100;
}
.table-row-accent:hover::before {
  @apply w-0.5 opacity-100;
}

/* Pagination */
.pagination-btn {
  @apply w-7 h-7 flex items-center justify-center rounded text-xs
         text-text-secondary hover:bg-[#1c2330] hover:text-text-primary
         transition-colors duration-100 disabled:opacity-30 disabled:cursor-not-allowed num;
}
.pagination-btn-active {
  @apply pagination-btn bg-brand text-white hover:bg-brand-hover;
}

/* 모드 탭 (기존 3개 클래스 교체 — 섹션 8 참고) */
.mode-tab {
  @apply relative flex-1 flex flex-col items-center justify-center gap-1
         py-2 px-2 rounded-md text-xs font-medium
         transition-all duration-100 cursor-pointer
         border border-transparent;
}
.mode-tab-manual-active  { @apply mode-tab bg-[#1c2330] text-text-primary border-[#2a3344]; }
.mode-tab-manual-inactive { @apply mode-tab bg-transparent text-text-secondary hover:bg-[#1c2330] hover:text-text-primary; }
.mode-tab-semi-active    { @apply mode-tab bg-connecting/10 text-connecting border-connecting/30; }
.mode-tab-semi-inactive  { @apply mode-tab bg-transparent text-text-secondary hover:bg-connecting/10 hover:text-connecting; }
.mode-tab-auto-active    { @apply mode-tab bg-buy/10 text-buy border-buy/30; }
.mode-tab-auto-inactive  { @apply mode-tab bg-transparent text-text-secondary hover:bg-buy/10 hover:text-buy; }
.mode-tab-locked         { @apply mode-tab bg-transparent text-text-disabled cursor-not-allowed; }

/* 사이드바 nav left accent (기존 nav-item, nav-item-active 교체) */
.nav-item {
  @apply relative flex items-center gap-3 px-3 py-2.5 rounded-md text-sm
         text-text-secondary hover:bg-[#1c2330] hover:text-text-primary
         transition-colors duration-100 cursor-pointer w-full;
}
.nav-item::before {
  content: '';
  @apply absolute left-0 top-1/2 -translate-y-1/2 w-0.5 h-4 rounded-r-full
         bg-brand opacity-0 transition-opacity duration-100;
}
.nav-item-active { @apply nav-item bg-[#1c2330] text-text-primary; }
.nav-item-active::before { @apply opacity-100; }
```

---

## 신규 파일 목록

구현 시 생성이 필요한 파일:

| 파일 경로 | 역할 |
|-----------|------|
| `src/renderer/components/portfolio/PortfolioCard.tsx` | 포트폴리오 카드 (섹션 3) |
| `src/renderer/components/common/Pagination.tsx` | 페이지네이션 (섹션 5) |

기존 파일 수정 목록:

| 파일 경로 | 변경 사항 |
|-----------|-----------|
| `src/renderer/styles/global.css` | nav-item, mode-tab, table-row-accent, pagination-btn 추가/교체 |
| `src/renderer/components/layout/LeftSidebar.tsx` | 로고 섹션 + SVG 아이콘 + 하단 버전 |
| `src/renderer/components/layout/TopHeader.tsx` | 브레드크럼 + 활성 ticker 표시 + StatusDot |
| `src/renderer/components/layout/StatusBar.tsx` | 모드 색상 + 마지막 신호 + 현재 시간 |
| `src/renderer/components/common/ModeSelector.tsx` | 모드별 아이콘 + 색상 체계 |
| `src/renderer/pages/DashboardPage.tsx` | 레이아웃 재구성 + PortfolioCard 사용 |
| `src/renderer/pages/TradingRoomPage.tsx` | 게이지 통합 + LIVE 인디케이터 |
| `src/renderer/pages/HistoryPage.tsx` | 요약 + 테이블 개선 + Pagination |
| `src/renderer/pages/SettingsPage.tsx` | RatioField + KisStep 타임라인 |
