import LiveIndicator from '../common/LiveIndicator'
import { useDrawerStore } from '../../store/useDrawerStore'

interface TradingRoomHeaderProps {
  ticker: string | null
  companyName: string | null
  /** "Q3 FY25 Earnings Call" 같은 세션 라벨. */
  sessionLabel?: string | null
  /** 경과 시간 라벨 ("25:14"). 호출처에서 포맷. */
  elapsedLabel?: string | null
  wpm?: number
  isLive: boolean
  /** Market Screen 복귀 콜백. */
  onExit?: () => void
  /**
   * 어닝콜 시연 재생 시작 콜백 (Contract 7.8).
   * 지정하지 않으면 버튼이 렌더되지 않는다.
   */
  onStartDemo?: () => void
  /** 시연 시작 요청이 진행 중인지. true 면 버튼을 잠근다. */
  demoStarting?: boolean
  /**
   * 발화자 프로필 열기 콜백. 명부를 못 가져왔으면 호출처가 넘기지 않고,
   * 그때는 버튼이 렌더되지 않는다 — 눌러도 빈 모달이 뜨는 것보다 낫다.
   */
  onSpeakerProfile?: () => void
  /** 명부 인원 수. 버튼에 같이 표시해 무엇이 들어 있는지 미리 알린다. */
  speakerCount?: number
}

/**
 * TradingRoomHeader — 페이지 내부 상단 행.
 *
 * 디자인 캔버스의 main `.header` 좌측 (`hd-left`) 와 동일한 정보 묶음.
 * 책임 분리:
 *  - TopHeader (AppLayout): 워크스페이스 브레드크럼 + 페이지 타이틀 + WS/KIS/유저.
 *    모든 페이지에서 동일. ticker 정보는 표시하지 않는다.
 *  - TradingRoomHeader (본 컴포넌트): LIVE 상태 + ticker 큼 + 회사명 + 종목정보
 *    버튼 + 세션 메타. TradingRoom 페이지 내부 상단 행으로만 표시.
 *
 * 두 헤더에서 동일 ticker 가 중복 노출되는 것을 방지하기 위해 TradingRoom 의 모든
 * 종목 컨텍스트는 본 컴포넌트가 단독 책임진다.
 *
 * 종목정보 버튼:
 *  - useDrawerStore.open(ticker) → CompanyDrawer 표시 (DashboardPage 와 동일 패턴).
 *  - CompanyDrawer 는 App.tsx 전역에 단일 mount → 페이지 무관하게 표시 가능.
 *  - ticker 정규식 검증은 store 내부에서 처리 — silently no-op on invalid.
 */
export default function TradingRoomHeader({
  ticker,
  companyName,
  sessionLabel,
  elapsedLabel,
  wpm,
  isLive,
  onExit,
  onStartDemo,
  demoStarting = false,
  onSpeakerProfile,
  speakerCount = 0,
}: TradingRoomHeaderProps) {
  const openDrawer = useDrawerStore((s) => s.open)

  return (
    <div className="h-12 shrink-0 flex items-center gap-3 min-w-0">
      {onExit && (
        <button
          type="button"
          onClick={onExit}
          className="inline-flex items-center gap-1 h-6 px-2 rounded text-text-tertiary hover:text-text-primary hover:bg-surface-2 transition-colors duration-100 text-[11px]"
          title="종목 목록으로"
        >
          <svg width="11" height="11" viewBox="0 0 12 12" fill="none" stroke="currentColor" strokeWidth="1.5">
            <path d="M7.5 2L3 6l4.5 4" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
          목록
        </button>
      )}
      <LiveIndicator active={isLive} />

      {ticker ? (
        <>
          <span className="num text-xl font-bold text-text-primary tracking-[0.01em]">
            {ticker}
          </span>
          {companyName && (
            <span className="text-[13px] text-text-secondary truncate max-w-[200px]">
              {companyName}
            </span>
          )}
          <button
            type="button"
            onClick={() => openDrawer(ticker)}
            className="inline-flex items-center gap-1.5 h-6 px-2.5 rounded
                       bg-surface-2 border border-border-subtle text-text-secondary text-[11px] font-medium
                       hover:bg-surface-3 hover:text-text-primary hover:border-border-strong
                       transition-colors duration-100"
            title="종목 상세 정보 보기"
            aria-label={`${ticker} 종목 정보`}
          >
            <svg width="11" height="11" viewBox="0 0 12 12" fill="none" stroke="currentColor" strokeWidth="1.4">
              <circle cx="6" cy="6" r="4.5" />
              <path d="M6 5.2v2.4M6 3.6v.4" strokeLinecap="round" />
            </svg>
            종목 정보
          </button>

          {onStartDemo && (
            <button
              type="button"
              onClick={onStartDemo}
              disabled={demoStarting}
              className="inline-flex items-center gap-1.5 h-6 px-2.5 rounded
                         bg-surface-2 border border-border-subtle text-text-secondary text-[11px] font-medium
                         hover:bg-surface-3 hover:text-text-primary hover:border-border-strong
                         disabled:opacity-50 disabled:cursor-not-allowed
                         transition-colors duration-100"
              title="준비된 어닝콜 스크립트를 재생합니다"
            >
              <svg width="11" height="11" viewBox="0 0 12 12" fill="none" stroke="currentColor" strokeWidth="1.4">
                <path d="M3 2.2l6.5 3.8L3 9.8z" strokeLinejoin="round" />
              </svg>
              {demoStarting ? '시작하는 중…' : '시연 시작'}
            </button>
          )}

          {onSpeakerProfile && (
            <button
              type="button"
              onClick={onSpeakerProfile}
              className="inline-flex items-center gap-1.5 h-6 px-2.5 rounded
                         bg-surface-2 border border-border-subtle text-text-secondary text-[11px] font-medium
                         hover:bg-surface-3 hover:text-text-primary hover:border-border-strong
                         focus-visible:outline focus-visible:outline-1 focus-visible:outline-accent-500
                         transition-colors duration-100"
              title="콜 참가자 명부와 발언 집계"
            >
              <svg width="11" height="11" viewBox="0 0 12 12" fill="none" stroke="currentColor" strokeWidth="1.4">
                <circle cx="6" cy="4.2" r="2.2" />
                <path d="M2 10.2c0-2 1.8-3.2 4-3.2s4 1.2 4 3.2" strokeLinecap="round" />
              </svg>
              발화자
              {speakerCount > 0 && <span className="num text-text-tertiary">{speakerCount}</span>}
            </button>
          )}

          {(sessionLabel || elapsedLabel || wpm != null) && (
            <>
              <span className="w-[3px] h-[3px] rounded-full bg-border-strong mx-0.5" />
              <span className="text-[12px] text-text-tertiary">
                {sessionLabel}
                {elapsedLabel && (
                  <>
                    {' · '}
                    <span className="num text-text-secondary">{elapsedLabel}</span>
                    {' 경과'}
                  </>
                )}
                {wpm != null && (
                  <>
                    {' · WPM '}
                    <span className="num text-text-secondary">{wpm}</span>
                  </>
                )}
              </span>
            </>
          )}
        </>
      ) : (
        <span className="text-sm text-text-tertiary">활성 종목 없음</span>
      )}
    </div>
  )
}
