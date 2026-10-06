import { useCallback, useEffect, useRef, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { ipc, IPC_CHANNELS } from '../lib/ipc'
import { type MaskedCredentialsResponse } from '../../lib/ipcChannels'
import { useUserStore } from '../store/useUserStore'
import { useConnectionStore } from '../store/useConnectionStore'
import KisStatusTimeline, { type KisTimelineStep } from '../components/settings/KisStatusTimeline'
import KisKeyForm, {
  KIS_MODE_LABEL,
  type KisMode,
  type MaskedKisKey,
  type VaultSavePayload,
} from '../components/settings/KisKeyForm'
import SegmentedControl from '../components/common/SegmentedControl'
import Modal from '../components/common/Modal'
import { ComingSoon } from '../components/common/StateView'
import { showIpcErrorToast } from '../components/common/Toast'
import { notifyComingSoon } from '../components/auth/notifyComingSoon'

/**
 * 키 삭제 시 분기 결정 helper (테스트 친화적 순수 함수).
 *
 * 입력:
 *   - mode: 삭제 대상 모드
 *   - isPaperTrading: 현재 활성 모드가 paper 인지
 *   - hasCredentials: 양쪽 등록 여부 스냅샷
 *
 * 반환:
 *   - kind 'active-switch'    : 활성 모드 키 삭제 + 다른 모드 등록됨 → 다른 모드로 자동 전환
 *   - kind 'active-none-left' : 활성 모드 키 삭제 + 남는 키가 없음 → 설정에 머물며 "키 없음" 으로 표시
 *   - kind 'inactive-keep'    : 비활성 모드 키 삭제 — 활성 모드 운영 영향 없음
 */
export type CardDeleteDecision =
  | { kind: 'active-switch'; switchTo: KisMode }
  | { kind: 'active-none-left' }
  | { kind: 'inactive-keep' }

export function decideCardDelete(
  mode: KisMode,
  isPaperTrading: boolean,
  hasCredentials: { paper: boolean; real: boolean },
): CardDeleteDecision {
  const isActive = (mode === 'paper') === isPaperTrading
  if (!isActive) return { kind: 'inactive-keep' }
  const otherMode: KisMode = mode === 'paper' ? 'real' : 'paper'
  if (hasCredentials[otherMode]) return { kind: 'active-switch', switchTo: otherMode }
  return { kind: 'active-none-left' }
}

/** `?kis=paper|real` — 키 없이 주문을 열었을 때 그 계좌의 등록 폼을 펼친 채로 연다. */
export function parseKisParam(value: string | null): KisMode | null {
  return value === 'paper' || value === 'real' ? value : null
}

const MODE_ITEMS: { id: KisMode; label: string }[] = [
  { id: 'paper', label: KIS_MODE_LABEL.paper },
  { id: 'real', label: KIS_MODE_LABEL.real },
]

export default function SettingsPage() {
  const { accountType } = useUserStore()
  const isSelfPaper = accountType === 'SELF_PAPER'

  return (
    <div className="max-w-[720px] mx-auto px-6 py-8 flex flex-col gap-6">
      <h1 className="text-ink-1 text-[22px] font-bold">설정</h1>
      {isSelfPaper ? <PaperAccountPanel /> : <KisPanel />}
      <AppSettingsPanel />
    </div>
  )
}

/* -------------------------------------------------------------------------- */
/* PaperAccountPanel — 페이퍼 계정은 KIS 키 없이 가상 체결하므로 상태만 보인다.  */
/* -------------------------------------------------------------------------- */
function PaperAccountPanel() {
  return (
    <section className="glass rim rounded-[var(--radius-panel)] p-6 flex flex-col gap-3">
      <div className="flex items-center gap-3">
        <h2 className="on-glass text-ink-1 text-[16px] font-semibold">페이퍼 계정</h2>
        <StatusChip ok label="준비됨" />
      </div>
      <p className="text-ink-3 text-[13px] leading-relaxed">
        증권사를 거치지 않고 현재가로 가상 체결합니다. 잔고와 체결 내역은 서버에 기록됩니다.
      </p>
    </section>
  )
}

/* -------------------------------------------------------------------------- */
/* KisPanel — 사용할 계좌(모드) · 연결 단계 · 키 두 벌.                          */
/* -------------------------------------------------------------------------- */
type PendingAction =
  | { kind: 'switch'; to: KisMode }
  | { kind: 'delete'; mode: KisMode; decision: CardDeleteDecision }

function KisPanel() {
  const [searchParams] = useSearchParams()
  const kisTokenStatus = useConnectionStore((s) => s.kisTokenStatus)
  const hasCredentials = useConnectionStore((s) => s.hasCredentials)
  const setHasCredentials = useConnectionStore((s) => s.setHasCredentials)
  const setKisTokenStatus = useConnectionStore((s) => s.setKisTokenStatus)

  // 모의/실전 활성 모드 — main 프로세스가 단일 source of truth.
  // 읽기 전(null)에는 모의로 표시하되 전환 · 삭제를 막는다 — 실제 모드를 모른 채 판단하지 않게.
  const [isPaperTrading, setIsPaperTrading] = useState<boolean | null>(null)
  const [busy, setBusy] = useState(false)

  // 모드별 마스킹된 자격증명 — VAULT_GET_MASKED 응답.
  // appSecret 은 절대 포함되지 않으며 (KisService.getMaskedCredentials 가 차단),
  // 컴포넌트 언마운트 시 자동 폐기 (state 가 component-scoped 이므로).
  const [maskedCreds, setMaskedCreds] = useState<MaskedCredentialsResponse>({ paper: null, real: null })

  // 한 번에 하나의 키만 펼쳐서 등록 · 수정한다. 주문 시트에서 넘어오면 그 계좌를 펼친다.
  const [editing, setEditing] = useState<KisMode | null>(() => parseKisParam(searchParams.get('kis')))
  const [pending, setPending] = useState<PendingAction | null>(null)
  const keysRef = useRef<HTMLDivElement>(null)

  // 자격증명 / 마스킹 응답 재조회 — 등록/수정/삭제 후 + 마운트 시 호출.
  async function refreshCredsState(): Promise<void> {
    try {
      const [has, masked] = await Promise.all([
        ipc.invoke<{ paper: boolean; real: boolean }>(IPC_CHANNELS.VAULT_HAS),
        ipc.invoke<MaskedCredentialsResponse>(IPC_CHANNELS.VAULT_GET_MASKED),
      ])
      setHasCredentials(has)
      setMaskedCreds(masked)
    } catch (err) {
      // 조회 실패 시 silent — 다음 액션에서 재시도. UI 는 직전 상태 유지.
      console.debug('[SettingsPage] refreshCredsState failed:', err)
    }
  }

  useEffect(() => {
    let cancelled = false
    ipc
      .invoke<boolean>(IPC_CHANNELS.SETTINGS_GET_PAPER_TRADING)
      .then((v) => {
        if (!cancelled && typeof v === 'boolean') setIsPaperTrading(v)
      })
      .catch((err: unknown) => {
        // null 유지 — 전환 · 삭제가 막힌 채 남는다. 실전 모드인데 조회 실패 시 화면이 "모의" 로
        // 거짓 표시되어 사용자가 안전한 모의로 착각하는 silent fail 을 알림으로 드러낸다 (review F3).
        if (!cancelled) showIpcErrorToast(err)
      })
    void refreshCredsState()
    return () => {
      cancelled = true
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // 주문 시트에서 넘어왔으면 키 목록을 화면 안으로 끌어온다.
  useEffect(() => {
    if (parseKisParam(searchParams.get('kis'))) {
      keysRef.current?.scrollIntoView({ block: 'center' })
    }
  }, [searchParams])

  const modeKnown = isPaperTrading !== null
  const activeMode: KisMode = isPaperTrading === false ? 'real' : 'paper'
  const otherMode: KisMode = activeMode === 'paper' ? 'real' : 'paper'
  const noneRegistered = !hasCredentials.paper && !hasCredentials.real
  // 키가 있는 계좌로 바꾸는 것은 늘 안전하다. 지금 계좌의 키를 지운 뒤에도 다른 계좌로 빠져나올 수 있게
  // "두 계좌 모두 등록" 대신 "바꿀 계좌에 키 있음" 으로 판단한다.
  const canSwitch = modeKnown && !busy && hasCredentials[otherMode]
  const activeModeRegistered = hasCredentials[activeMode]
  const isKisHealthy = activeModeRegistered && kisTokenStatus === 'VALID'

  function requestSwitch(to: KisMode) {
    // 바꿀 계좌에 키가 있을 때만 전환한다 — 키 없는 모드로 바꾸면 인증이 실패한다.
    if (!canSwitch || to === activeMode || !hasCredentials[to]) return
    setPending({ kind: 'switch', to })
  }

  async function confirmSwitch(to: KisMode) {
    setBusy(true)
    try {
      await ipc.invoke(IPC_CHANNELS.SETTINGS_SET_PAPER_TRADING, { value: to === 'paper' })
      setIsPaperTrading(to === 'paper')
      // 토큰이 무효화됐으므로 connection store 표시도 갱신
      setKisTokenStatus('UNKNOWN')
    } catch (err: unknown) {
      showIpcErrorToast(err)
    } finally {
      setBusy(false)
    }
  }

  function requestDelete(mode: KisMode) {
    if (isPaperTrading === null) return
    setPending({ kind: 'delete', mode, decision: decideCardDelete(mode, isPaperTrading, hasCredentials) })
  }

  async function confirmDelete(mode: KisMode, decision: CardDeleteDecision) {
    setBusy(true)
    try {
      await ipc.invoke(IPC_CHANNELS.VAULT_DELETE, { isPaperTrading: mode === 'paper' })
      if (decision.kind === 'active-switch') {
        await ipc.invoke(IPC_CHANNELS.SETTINGS_SET_PAPER_TRADING, { value: decision.switchTo === 'paper' })
        setIsPaperTrading(decision.switchTo === 'paper')
        setKisTokenStatus('UNKNOWN')
      } else if (decision.kind === 'active-none-left') {
        // 남는 키가 없어도 설정에 머문다 — 분석 기능은 키 없이 쓰고, 등록은 이 자리에서 다시 한다.
        setKisTokenStatus('UNKNOWN')
      }
    } catch (err: unknown) {
      showIpcErrorToast(err)
    } finally {
      setBusy(false)
    }
    await refreshCredsState()
  }

  async function handlePendingConfirm() {
    const action = pending
    setPending(null)
    if (!action) return
    if (action.kind === 'switch') await confirmSwitch(action.to)
    else await confirmDelete(action.mode, action.decision)
  }

  async function handleSave(payload: VaultSavePayload) {
    // 비활성 모드 저장도 안전하다 — VAULT_SAVE 는 활성 모드와 같을 때만 토큰을 발급한다.
    await ipc.invoke(IPC_CHANNELS.VAULT_SAVE, payload)
    setEditing(null)
    await refreshCredsState()
  }

  async function handleIssueToken() {
    try {
      await ipc.invoke(IPC_CHANNELS.KIS_ISSUE_TOKEN)
      setKisTokenStatus('VALID')
    } catch (err: unknown) {
      showIpcErrorToast(err)
    }
  }

  // 표시 기준은 "활성 모드의 키 등록 여부" — 비활성 모드 키만 등록된 상태에서 활성 모드가
  // 마치 사용 가능한 것처럼 보이지 않도록 (Security H1).
  const steps: KisTimelineStep[] = [
    {
      id: 'apikey',
      title: activeModeRegistered ? 'API 키 등록됨' : 'API 키 미등록',
      sub: activeModeRegistered
        ? 'API 키가 안전하게 저장되어 있습니다'
        : hasCredentials[otherMode]
          ? `${KIS_MODE_LABEL[activeMode]} 키가 없습니다. ${KIS_MODE_LABEL[otherMode]} 키만 등록되어 있습니다`
          : '등록된 API 키가 없습니다',
      status: activeModeRegistered ? 'done' : 'pending',
    },
    {
      id: 'token',
      title:
        kisTokenStatus === 'VALID'
          ? '액세스 토큰 유효'
          : kisTokenStatus === 'EXPIRED'
            ? '액세스 토큰 만료'
            : '액세스 토큰 미발급',
      sub: kisTokenStatus === 'VALID' ? '토큰이 정상 발급되어 있습니다' : '토큰 재발급이 필요합니다',
      status: kisTokenStatus === 'VALID' ? 'done' : kisTokenStatus === 'EXPIRED' ? 'error' : 'pending',
    },
    {
      id: 'connection',
      title: isKisHealthy ? '서버 연결 정상' : '서버 연결 대기',
      sub: isKisHealthy ? '정상 연결됨' : 'API 키와 토큰 등록 후 연결됩니다',
      status: isKisHealthy ? 'done' : 'pending',
    },
  ]

  const closePending = useCallback(() => setPending(null), [])

  const modeHelp = !modeKnown
    ? '주문할 계좌를 확인하는 중입니다.'
    : hasCredentials[otherMode]
      ? null
      : noneRegistered
        ? '아래에서 키를 등록하면 주문할 수 있습니다.'
        : `${KIS_MODE_LABEL[otherMode]} 키도 등록하면 바꿀 수 있습니다.`

  return (
    <section className="glass rim rounded-[var(--radius-panel)] p-6 flex flex-col gap-6">
      <div className="flex items-center gap-3">
        <h2 className="on-glass text-ink-1 text-[16px] font-semibold">KIS 연동</h2>
        <StatusChip ok={isKisHealthy} label={isKisHealthy ? '연결 정상' : '연결 대기'} />
      </div>

      {/* 사용할 계좌 — 실전 모드는 늘 크게 표시한다 (ux.md 설계 원칙) */}
      <div className="flex flex-col gap-2.5">
        <span className="text-ink-2 text-[12.5px] font-medium">주문할 계좌</span>
        <div className="flex flex-wrap items-center gap-3">
          {/* fieldset disabled 로 안의 버튼이 클릭 · 키보드 모두 막힌다 */}
          <fieldset
            disabled={!canSwitch}
            aria-describedby={modeHelp ? 'kis-mode-help' : undefined}
            className={`contents ${!canSwitch ? '[&>div]:opacity-[0.55]' : ''}`}
          >
            <SegmentedControl items={MODE_ITEMS} activeId={activeMode} onChange={requestSwitch} />
          </fieldset>
          {modeKnown && activeMode === 'real' && (
            <span className="text-warning text-[13px] font-semibold">실제 돈으로 주문합니다</span>
          )}
        </div>
        <p id="kis-mode-help" className="text-ink-3 text-[12.5px] empty:hidden" aria-live="polite">
          {modeHelp}
        </p>
      </div>

      <KisStatusTimeline steps={steps} />

      {/* 키 두 벌 — 고른 계좌가 "사용 중" */}
      <div ref={keysRef} className="flex flex-col">
        <span className="text-ink-2 text-[12.5px] font-medium mb-1">API 키</span>
        <ul className="flex flex-col divide-y divide-border-subtle">
          {(['paper', 'real'] as const).map((mode) => (
            <KisKeyRow
              key={mode}
              mode={mode}
              inUse={modeKnown && mode === activeMode && hasCredentials[mode]}
              registered={hasCredentials[mode]}
              masked={maskedCreds[mode]}
              editing={editing === mode}
              disabled={busy || !modeKnown}
              onEdit={() => setEditing(mode)}
              onCancel={() => setEditing(null)}
              onDelete={() => requestDelete(mode)}
              onSave={handleSave}
            />
          ))}
        </ul>
      </div>

      <p className="flex gap-2 items-start text-ink-3 text-[12.5px] leading-relaxed">
        <svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" className="flex-none mt-0.5" aria-hidden>
          <rect x="3" y="7" width="10" height="7" rx="1.5" />
          <path d="M5 7V5a3 3 0 016 0v2" />
        </svg>
        <span>
          API 키와 액세스 토큰은 운영체제 자격 증명 저장소(keytar)에 암호화해 저장합니다. 키를 파일로 보관하지
          않습니다.
        </span>
      </p>

      <div className="flex items-center gap-3">
        <button type="button" onClick={handleIssueToken} disabled={busy || !activeModeRegistered} className="gbtn gbtn-sm">
          토큰 재발급
        </button>
        <button
          type="button"
          aria-disabled="true"
          title="준비 중입니다"
          onClick={() => notifyComingSoon('KIS 개발자 포털 열기')}
          className="ml-auto text-ink-4 text-[12.5px] bg-transparent border-0 p-0 cursor-default"
        >
          KIS 개발자 포털 열기
        </button>
      </div>

      <ConfirmModal action={pending} onCancel={closePending} onConfirm={handlePendingConfirm} />
    </section>
  )
}

/* -------------------------------------------------------------------------- */
/* KisKeyRow — 한 계좌의 키. 마스킹 값만 보이고 비밀값은 되돌려 받지 않는다.      */
/* -------------------------------------------------------------------------- */
function KisKeyRow({
  mode,
  inUse,
  registered,
  masked,
  editing,
  disabled,
  onEdit,
  onCancel,
  onDelete,
  onSave,
}: {
  mode: KisMode
  inUse: boolean
  registered: boolean
  masked: MaskedKisKey | null
  editing: boolean
  disabled: boolean
  onEdit: () => void
  onCancel: () => void
  onDelete: () => void
  onSave: (payload: VaultSavePayload) => Promise<void>
}) {
  // 등록된 키인데 가린 값을 아직 못 받았으면 폼을 열지 않는다 — 신규 등록으로 열리면 HTS ID 칸이 비어
  // 저장된 HTS ID 가 지워진다. 받으면(주문 시트에서 넘어온 경우 포함) 그때 펼친다.
  const canEdit = !registered || masked !== null
  return (
    <li className="flex flex-col gap-3 py-3.5">
      <div className="flex items-center gap-3 min-w-0">
        <div className="flex flex-col gap-1 min-w-0">
          <div className="flex items-center gap-2">
            <span className="text-ink-1 text-[14px] font-semibold">{KIS_MODE_LABEL[mode]}</span>
            {inUse && (
              <span className="glass rim rounded-full px-2 py-0.5 text-[11px] font-semibold text-ink-1 on-glass">사용 중</span>
            )}
          </div>
          {registered && masked ? (
            <dl className="flex flex-wrap gap-x-4 gap-y-0.5 text-[12px] text-ink-3">
              <div className="flex gap-1.5">
                <dt>계좌</dt>
                <dd className="num text-ink-2">{masked.accountNoMasked}</dd>
              </div>
              <div className="flex gap-1.5">
                <dt>App Key</dt>
                <dd className="num text-ink-2">{masked.appKeyMasked}</dd>
              </div>
              <div className="flex gap-1.5">
                <dt>HTS ID</dt>
                <dd className="text-ink-2">{masked.htsId ? '등록됨' : '없음'}</dd>
              </div>
            </dl>
          ) : (
            <span className="text-ink-3 text-[12px]">{registered ? '등록됨' : '등록된 키가 없습니다'}</span>
          )}
        </div>

        {!editing && (
          <div className="ml-auto flex items-center gap-2 flex-none">
            {registered ? (
              <>
                <button type="button" onClick={onEdit} disabled={disabled || !canEdit} className="gbtn gbtn-sm">
                  수정
                </button>
                <button type="button" onClick={onDelete} disabled={disabled} className="gbtn gbtn-sm">
                  삭제
                </button>
              </>
            ) : (
              <button type="button" onClick={onEdit} disabled={disabled} className="gbtn gbtn-sm">
                등록
              </button>
            )}
          </div>
        )}
      </div>

      {editing && canEdit && (
        <div className="frost rounded-[20px] p-4">
          <KisKeyForm
            mode={mode}
            existing={registered ? masked : null}
            submitLabel="저장"
            secondaryLabel="취소"
            onSecondary={onCancel}
            onSubmit={onSave}
            compact
            autoFocus
          />
        </div>
      )}
    </li>
  )
}

/* -------------------------------------------------------------------------- */
/* ConfirmModal — 계좌 전환 · 키 삭제 확인.                                      */
/* -------------------------------------------------------------------------- */
function ConfirmModal({
  action,
  onCancel,
  onConfirm,
}: {
  action: PendingAction | null
  onCancel: () => void
  onConfirm: () => void
}) {
  let title = ''
  let body = ''
  let confirmLabel = ''
  // 실제 돈과 관련된 방향(실전으로 전환, 키 삭제)은 위험 버튼으로 둔다
  let danger = false

  if (action?.kind === 'switch') {
    title = `${KIS_MODE_LABEL[action.to]}로 바꿀까요?`
    body =
      action.to === 'real'
        ? '이제부터 실제 돈으로 주문합니다. 토큰을 다시 발급합니다.'
        : '모의투자 서버로 주문합니다. 토큰을 다시 발급합니다.'
    confirmLabel = '바꾸기'
    danger = action.to === 'real'
  } else if (action?.kind === 'delete') {
    const label = KIS_MODE_LABEL[action.mode]
    title = `${label} 키를 삭제할까요?`
    const d = action.decision
    body =
      d.kind === 'active-switch'
        ? d.switchTo === 'real'
          ? `삭제하면 ${KIS_MODE_LABEL.real}로 바뀌고, 이제부터 실제 돈으로 주문합니다.`
          : `삭제하면 ${KIS_MODE_LABEL.paper}로 바뀝니다.`
        : d.kind === 'active-none-left'
          ? '삭제하면 등록된 키가 없어 주문할 수 없습니다. 분석 기능은 그대로 씁니다.'
          : '지금 쓰는 계좌의 키는 그대로 둡니다.'
    confirmLabel = '삭제'
    danger = true
  }

  return (
    <Modal open={action !== null} onClose={onCancel} ariaLabel={title}>
      <div className="w-[400px] max-w-[90vw] p-7 flex flex-col gap-3">
        <h3 className="text-ink-1 text-[17px] font-bold">{title}</h3>
        <p className="text-ink-2 text-[13.5px] leading-relaxed">{body}</p>
        {/* 대화상자는 보조 버튼 왼쪽, 색상 유리 버튼 오른쪽 */}
        <div className="flex items-center justify-between gap-2 mt-3">
          <button type="button" onClick={onCancel} className="gbtn">
            취소
          </button>
          <button type="button" onClick={onConfirm} className={`gbtn ${danger ? 'gbtn-porphyra' : 'gbtn-olive'}`}>
            {confirmLabel}
          </button>
        </div>
      </div>
    </Modal>
  )
}

/* -------------------------------------------------------------------------- */
/* AppSettingsPanel — 앱 설정 자리. 아직 동작하는 항목이 없다.                   */
/* -------------------------------------------------------------------------- */
const APP_SETTINGS: { title: string; note: string }[] = [
  { title: '알림', note: '콜 시작 · 체결 알림을 고르는 기능은 준비 중입니다' },
  { title: '테마', note: '지금은 어두운 테마만 있습니다' },
  { title: '언어', note: '지금은 한국어만 있습니다' },
  { title: '자동 로그인', note: '로그인 정보를 보관하는 방식을 정한 뒤 추가합니다' },
]

function AppSettingsPanel() {
  return (
    <section className="glass rim rounded-[var(--radius-panel)] p-6 flex flex-col gap-4">
      <h2 className="on-glass text-ink-1 text-[16px] font-semibold">앱 설정</h2>
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
        {APP_SETTINGS.map((it) => (
          <ComingSoon key={it.title} title={it.title} note={it.note} className="py-6 px-4" />
        ))}
      </div>
    </section>
  )
}

function StatusChip({ ok, label }: { ok: boolean; label: string }) {
  return (
    <span className="ml-auto inline-flex items-center gap-1.5 text-[12px] font-semibold" style={{ color: ok ? 'var(--ok)' : 'var(--caution)' }}>
      <span className="w-1.5 h-1.5 rounded-full" style={{ background: 'currentColor' }} aria-hidden />
      {label}
    </span>
  )
}
