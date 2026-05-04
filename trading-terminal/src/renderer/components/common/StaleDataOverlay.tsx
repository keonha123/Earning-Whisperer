import type { IpcError, IpcErrorCode } from '../../../lib/types/ipcError'

interface StaleDataOverlayProps {
  /**
   * 마지막 조회 에러. null 이면 overlay 미렌더 (정상 상태).
   * IpcError 의 code 로 사용자 메시지 차등 표시.
   */
  error: IpcError | null
  /** 사용자가 "다시 조회" 버튼 클릭 시 호출. 없으면 버튼 숨김. */
  onRetry?: () => void
  /**
   * 재시도 진행 중 여부 — 버튼 비활성 + 라벨 변경.
   * 부모는 보통 store 의 isSyncing 을 그대로 전달.
   */
  isRetrying?: boolean
  /**
   * 마지막 성공 동기화 시각 (epoch sec). 있으면 overlay 하단에 표시 →
   * "이 데이터는 N분 전" 형태로 staleness 명확화.
   */
  lastSyncedAt?: number | null
  /**
   * absolute 가 차지하는 영역 — 부모가 relative 여야 함.
   * 기본값 inset-0 = 부모 전체 덮기.
   */
  className?: string
}

/**
 * F-2: stale 데이터 시각화 overlay.
 *
 * 사용 시나리오: KIS_GET_BALANCE 가 실패한 직후 PortfolioCard / HoldingsTable 등
 * 잔고 기반 카드 위에 절대 위치 overlay 를 띄워서 사용자가 표시된 숫자를 실제
 * 데이터로 오인하는 silent fail 을 차단한다.
 *
 * 디자인 원칙:
 *  - 숫자가 흐릿하게 보이되 읽히지 않도록 backdrop-blur + 어두운 반투명 배경.
 *  - 경고 톤 (warning border) 으로 "정상 상태가 아님" 신호.
 *  - 재시도 액션을 overlay 안에 둬서 사용자가 Dashboard 헤더의 "동기화" 버튼을
 *    찾아 헤매지 않도록 가까이 배치.
 *  - 부모 컴포넌트 (PortfolioCard / HoldingsTable) 자체는 변경 최소화 —
 *    overlay 만 조건부 mount.
 */
export default function StaleDataOverlay({
  error,
  onRetry,
  isRetrying = false,
  lastSyncedAt,
  className = '',
}: StaleDataOverlayProps) {
  if (error === null) return null

  const userMessage = messageForCode(error.code)
  const lastSyncLabel = lastSyncedAt
    ? formatRelative(lastSyncedAt)
    : null

  return (
    <div
      // role=alert 으로 screen reader 즉시 안내. aria-live=assertive.
      role="alert"
      aria-live="assertive"
      className={`absolute inset-0 z-10 flex items-center justify-center
                  bg-surface-0/80 backdrop-blur-[2px]
                  border border-warning/40 rounded-lg
                  ${className}`}
    >
      <div className="flex flex-col items-center gap-2 px-4 py-3 max-w-[280px] text-center">
        <div className="flex items-center gap-1.5 text-warning text-[11px] font-semibold uppercase tracking-[0.12em]">
          <svg
            width="12"
            height="12"
            viewBox="0 0 12 12"
            fill="none"
            stroke="currentColor"
            strokeWidth="1.5"
            aria-hidden="true"
          >
            <path d="M6 1.5L11 10.5H1L6 1.5Z" />
            <path d="M6 5v2.5" strokeLinecap="round" />
            <circle cx="6" cy="9" r="0.5" fill="currentColor" />
          </svg>
          조회 실패
        </div>
        <p className="text-text-primary text-[12px] leading-snug">
          {userMessage}
        </p>
        <p className="text-text-tertiary text-[10px]">
          데이터 신뢰 불가 — 매매 판단 보류
          {lastSyncLabel !== null && (
            <>
              <br />
              마지막 정상 조회 {lastSyncLabel}
            </>
          )}
        </p>
        {onRetry !== undefined && (
          <button
            type="button"
            onClick={onRetry}
            disabled={isRetrying}
            className="mt-1 h-7 px-3 inline-flex items-center gap-1.5 rounded-md
                       bg-surface-2 border border-border-strong text-text-primary
                       hover:bg-surface-3 text-[11px] font-medium
                       disabled:opacity-40 disabled:cursor-not-allowed"
          >
            <svg
              width="11"
              height="11"
              viewBox="0 0 12 12"
              fill="none"
              stroke="currentColor"
              strokeWidth="1.5"
              className={isRetrying ? 'animate-spin' : ''}
              aria-hidden="true"
            >
              <path d="M2 6a4 4 0 017-2.5M10 6a4 4 0 01-7 2.5M9 2v2h-2M3 10V8h2" />
            </svg>
            {isRetrying ? '조회 중' : '다시 조회'}
          </button>
        )}
      </div>
    </div>
  )
}

/**
 * IpcError code → 사용자 가시 메시지.
 * 영역별 안내 톤은 toast 메시지와 일관 (PR-2b 디자인 참고).
 */
function messageForCode(code: IpcErrorCode): string {
  switch (code) {
    case 'AUTH_REQUIRED':
      return 'KIS 계정 권한이 필요합니다.'
    case 'AUTH_EXPIRED':
      return 'KIS 토큰이 만료되었습니다. 재로그인이 필요합니다.'
    case 'NETWORK':
      return '네트워크 연결을 확인해 주세요.'
    case 'BACKEND_5XX':
      return 'KIS 서버가 응답하지 않습니다.'
    case 'KIS_ERROR':
      return 'KIS 잔고 조회에 실패했습니다.'
    case 'VALIDATION':
      return '잔고 요청이 거부되었습니다.'
    case 'BUSINESS_RULE':
      return '잔고 조회 정책에 의해 차단되었습니다.'
    case 'UNKNOWN':
    default:
      return '잔고 조회에 실패했습니다.'
  }
}

/**
 * epoch sec → "5분 전" 형태 한국어 상대 시각.
 * 가벼운 자체 구현 — date-fns 등 dep 추가 회피.
 */
function formatRelative(epochSec: number): string {
  const diffSec = Math.max(0, Math.floor(Date.now() / 1000) - epochSec)
  if (diffSec < 60) return '방금'
  const diffMin = Math.floor(diffSec / 60)
  if (diffMin < 60) return `${diffMin}분 전`
  const diffHour = Math.floor(diffMin / 60)
  if (diffHour < 24) return `${diffHour}시간 전`
  const diffDay = Math.floor(diffHour / 24)
  return `${diffDay}일 전`
}
