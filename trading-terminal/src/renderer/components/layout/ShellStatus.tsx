import { ipc, IPC_CHANNELS } from '../../lib/ipc'
import { useConnectionStore } from '../../store/useConnectionStore'
import type { WsStatus, KisTokenStatus } from '../../store/useConnectionStore'
import { useUserStore } from '../../store/useUserStore'

type Tone = 'ok' | 'caution' | 'danger' | 'idle'

const TONE_DOT: Record<Tone, string> = {
  ok: 'bg-ok',
  caution: 'bg-warning',
  danger: 'bg-danger',
  idle: 'bg-ink-4',
}

const WS_VIEW: Record<WsStatus, { text: string; tone: Tone }> = {
  CONNECTED: { text: '연결됨', tone: 'ok' },
  CONNECTING: { text: '연결 중', tone: 'caution' },
  RECONNECTING: { text: '다시 연결 중', tone: 'caution' },
  DISCONNECTED: { text: '끊김', tone: 'danger' },
}

const KIS_VIEW: Record<KisTokenStatus, { text: string; tone: Tone }> = {
  VALID: { text: '토큰 유효', tone: 'ok' },
  EXPIRED: { text: '토큰 만료', tone: 'danger' },
  UNKNOWN: { text: '연결 안 됨', tone: 'idle' },
}

/**
 * 메뉴 아래쪽 상태 · 계정 영역.
 *
 * 서버 연결과 KIS 토큰 상태를 보여 주는 곳은 앱에서 여기 한 곳뿐이다 (docs/design/ux.md).
 * KIS 가 정상이 아니면 줄을 눌러 설정으로 가서 바로 고칠 수 있다.
 */
export default function ShellStatus({ onOpenSettings }: { onOpenSettings: () => void }) {
  const wsStatus = useConnectionStore((s) => s.wsStatus)
  const kisTokenStatus = useConnectionStore((s) => s.kisTokenStatus)
  const setAuthenticated = useConnectionStore((s) => s.setAuthenticated)
  const nickname = useUserStore((s) => s.nickname)
  const clear = useUserStore((s) => s.clear)

  const ws = WS_VIEW[wsStatus] ?? WS_VIEW.DISCONNECTED
  const kis = KIS_VIEW[kisTokenStatus] ?? KIS_VIEW.UNKNOWN
  const kisNeedsAction = kisTokenStatus !== 'VALID'

  async function handleLogout() {
    try {
      await ipc.invoke(IPC_CHANNELS.AUTH_LOGOUT)
    } finally {
      setAuthenticated(false)
      clear()
    }
  }

  return (
    <div className="shrink-0 mx-2.5 mb-2.5 mt-3 pt-3 border-t border-border-subtle flex flex-col gap-1">
      <div role="status" aria-label="연결 상태" className="flex flex-col gap-1">
      <StatusRow label="서버" value={ws.text} tone={ws.tone} />
      {kisNeedsAction ? (
        <button
          type="button"
          onClick={onOpenSettings}
          className="rounded-full hover:bg-white/[0.04] transition-colors text-left"
          title="설정에서 KIS 연결을 확인합니다"
          aria-label={`KIS ${kis.text} — 설정에서 확인`}
        >
          <StatusRow label="KIS" value={kis.text} tone={kis.tone} />
        </button>
      ) : (
        <StatusRow label="KIS" value={kis.text} tone={kis.tone} />
      )}
      </div>

      <div className="flex items-center gap-2 mt-2 pl-3 pr-1">
        <span className="flex-1 min-w-0 truncate text-[13px] text-ink-2">{nickname}</span>
        <button type="button" onClick={() => void handleLogout()} className="gbtn gbtn-sm shrink-0">
          로그아웃
        </button>
      </div>
    </div>
  )
}

function StatusRow({ label, value, tone }: { label: string; value: string; tone: Tone }) {
  return (
    <div className="flex items-center gap-2 px-3 py-1.5 text-[12px]">
      <span className={`w-1.5 h-1.5 rounded-full shrink-0 ${TONE_DOT[tone]}`} aria-hidden="true" />
      <span className="text-ink-3 w-9 shrink-0">{label}</span>
      <span className={tone === 'danger' ? 'text-danger' : 'text-ink-2'}>{value}</span>
    </div>
  )
}
