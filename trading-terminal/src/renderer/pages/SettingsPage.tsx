import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { ipc, IPC_CHANNELS } from '../lib/ipc'
import { type MaskedCredentialsResponse } from '../../lib/ipcChannels'
import AuthInputField from '../components/auth/AuthInputField'
import { useUserStore } from '../store/useUserStore'
import { useConnectionStore } from '../store/useConnectionStore'
import Slider from '../components/common/Slider'
import Stepper from '../components/common/Stepper'
import KisStatusTimeline, {
  type KisTimelineStep,
} from '../components/settings/KisStatusTimeline'
import { kisStatusDevMock } from '../fixtures/kisStatus.dev-mock'
import { showIpcErrorToast } from '../components/common/Toast'

// fixture 메타데이터(AppKey, 핑 지연 등)는 dev 빌드에서만 노출.
// prod 에서는 generic 메시지만 표시 — 사용자가 더미 값을 진짜로 오인하지 않도록.
const SHOW_DEV_KIS_META = import.meta.env.DEV

/**
 * 카드 삭제 시 분기 결정 helper (테스트 친화적 순수 함수).
 *
 * 입력:
 *   - mode: 삭제 대상 모드
 *   - isPaperTrading: 현재 활성 모드가 paper 인지
 *   - hasCredentials: 양쪽 등록 여부 스냅샷
 *
 * 반환:
 *   - kind 'active-switch'   : 활성 모드 키 삭제 + 다른 모드 등록됨 → 자동 전환
 *   - kind 'active-redirect' : 활성 모드 키 삭제 + 양쪽 모두 미등록 됨 → vault 화면 redirect
 *   - kind 'inactive-keep'   : 비활성 모드 키 삭제 — 활성 모드 운영 영향 없음
 */
export type CardDeleteDecision =
  | { kind: 'active-switch'; switchTo: 'paper' | 'real' }
  | { kind: 'active-redirect' }
  | { kind: 'inactive-keep' }

export function decideCardDelete(
  mode: 'paper' | 'real',
  isPaperTrading: boolean,
  hasCredentials: { paper: boolean; real: boolean },
): CardDeleteDecision {
  const isActive = (mode === 'paper') === isPaperTrading
  if (!isActive) return { kind: 'inactive-keep' }
  const otherMode: 'paper' | 'real' = mode === 'paper' ? 'real' : 'paper'
  if (hasCredentials[otherMode]) return { kind: 'active-switch', switchTo: otherMode }
  return { kind: 'active-redirect' }
}

const SETTINGS_DEFAULT = {
  maxBuyRatio: 0.1,
  maxHoldingRatio: 0.3,
  cooldownMinutes: 5,
  emaThreshold: 0.6,
}

export default function SettingsPage() {
  const navigate = useNavigate()
  const { settings, setSettings, setEmaThreshold } = useUserStore()
  const {
    kisTokenStatus,
    hasCredentials,
    setHasCredentials,
    setKisTokenStatus,
  } = useConnectionStore()

  const [form, setForm] = useState({ ...settings })
  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState(false)
  const [saveError, setSaveError] = useState<string | null>(null)

  // 모의/실전 환경 토글 — main 프로세스에서 단일 source of truth
  const [isPaperTrading, setIsPaperTrading] = useState<boolean>(true)
  const [paperToggleBusy, setPaperToggleBusy] = useState(false)

  // 모드별 마스킹된 자격증명 — VAULT_GET_MASKED 응답.
  // appSecret 은 절대 포함되지 않으며 (KisService.getMaskedCredentials 가 차단),
  // 컴포넌트 언마운트 시 자동 폐기 (state 가 component-scoped 이므로).
  const [maskedCreds, setMaskedCreds] = useState<MaskedCredentialsResponse>({
    paper: null,
    real: null,
  })

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
        // 디폴트 true 유지 (안전한 쪽). 실전 모드인데 조회 실패 시 화면이 "모의" 로
        // 거짓 표시되어 사용자가 안전한 모의로 착각하는 silent fail 차단 (review F3).
        if (!cancelled) showIpcErrorToast(err)
      })
    // 마운트 시 마스킹/등록 여부 초기 조회.
    void refreshCredsState()
    return () => {
      cancelled = true
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  async function handleTogglePaperTrading() {
    if (paperToggleBusy) return
    // A3: 양쪽 모두 등록되어 있을 때만 토글 가능 — 한쪽만 등록된 경우 다른 모드로 전환해도 인증 실패.
    // 양쪽 미등록은 vault 진입 화면에서 처리되므로 여기에서는 단순 disabled.
    if (!(hasCredentials.paper && hasCredentials.real)) return

    const next = !isPaperTrading
    const message = next
      ? '모의 투자 환경으로 전환하시겠습니까? 토큰이 재발급됩니다.'
      : '실전 투자 환경으로 전환하시겠습니까? 토큰이 재발급됩니다.'
    if (!confirm(message)) return

    setPaperToggleBusy(true)
    try {
      await ipc.invoke(IPC_CHANNELS.SETTINGS_SET_PAPER_TRADING, { value: next })
      setIsPaperTrading(next)
      // 토큰이 무효화됐으므로 connection store 표시도 갱신
      setKisTokenStatus('UNKNOWN')
    } catch (err: unknown) {
      showIpcErrorToast(err)
    } finally {
      setPaperToggleBusy(false)
    }
  }

  // "저장됨" 배지 자동 hide 타이머 — 연속 저장 race / 언마운트 후 setState 방지.
  const savedTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  useEffect(() => {
    return () => {
      if (savedTimerRef.current !== null) {
        clearTimeout(savedTimerRef.current)
        savedTimerRef.current = null
      }
    }
  }, [])

  async function handleSave(e: React.FormEvent) {
    e.preventDefault()
    setSaving(true)
    setSaveError(null)
    try {
      // 주의: emaThreshold 는 IPC 페이로드에 포함하지 않음 — store 에만 반영.
      // TODO: emaThreshold 백엔드 영속화 (SETTINGS_UPDATE 시그니처 확장 필요, 별도 PR)
      await ipc.invoke(IPC_CHANNELS.SETTINGS_UPDATE, {
        tradingMode: form.tradingMode,
        maxBuyRatio: form.maxBuyRatio,
        maxHoldingRatio: form.maxHoldingRatio,
        cooldownMinutes: form.cooldownMinutes,
      })
      setSettings(form)
      setEmaThreshold(form.emaThreshold)
      setSaved(true)
      if (savedTimerRef.current !== null) {
        clearTimeout(savedTimerRef.current)
      }
      savedTimerRef.current = setTimeout(() => {
        setSaved(false)
        savedTimerRef.current = null
      }, 2000)
    } catch (err: unknown) {
      // 기존 인라인 setSaveError 는 유지 + toast 추가.
      const fallback = err instanceof Error ? err.message : '저장에 실패했습니다.'
      setSaveError(fallback)
      showIpcErrorToast(err)
    } finally {
      setSaving(false)
    }
  }

  function handleReset() {
    setForm({
      ...form,
      maxBuyRatio: SETTINGS_DEFAULT.maxBuyRatio,
      maxHoldingRatio: SETTINGS_DEFAULT.maxHoldingRatio,
      cooldownMinutes: SETTINGS_DEFAULT.cooldownMinutes,
      emaThreshold: SETTINGS_DEFAULT.emaThreshold,
    })
  }

  /**
   * A3: 카드별 키 삭제 핸들러.
   * 활성 모드 키 삭제 시 다른 모드 등록 여부에 따라 자동 전환 / 등록 화면 안내 분기.
   */
  async function handleCardDelete(mode: 'paper' | 'real'): Promise<void> {
    const isActive = (mode === 'paper') === isPaperTrading
    const modeLabel = mode === 'paper' ? '모의' : '실전'
    const otherMode = mode === 'paper' ? 'real' : 'paper'
    const otherLabel = mode === 'paper' ? '실전' : '모의'
    const otherRegistered = hasCredentials[otherMode]

    if (isActive) {
      // 활성 모드 키 삭제: 다른 모드 등록 여부에 따라 분기.
      if (otherRegistered) {
        // 다른 모드로 자동 전환.
        if (
          !confirm(
            `${modeLabel} KIS API 키를 삭제하시겠습니까?\n삭제 후 ${otherLabel} 모드로 자동 전환됩니다.`,
          )
        )
          return
        try {
          await ipc.invoke(IPC_CHANNELS.VAULT_DELETE, { isPaperTrading: mode === 'paper' })
          // 다른 모드로 활성 전환.
          await ipc.invoke(IPC_CHANNELS.SETTINGS_SET_PAPER_TRADING, {
            value: otherMode === 'paper',
          })
          setIsPaperTrading(otherMode === 'paper')
          setKisTokenStatus('UNKNOWN')
        } catch (err: unknown) {
          showIpcErrorToast(err)
        }
      } else {
        // 양쪽 다 없게 됨 — 등록 화면으로 이동 안내.
        if (
          !confirm(
            `${modeLabel} KIS API 키를 삭제하시겠습니까?\n삭제 후 등록된 키가 없으므로 등록 화면으로 이동합니다.`,
          )
        )
          return
        try {
          await ipc.invoke(IPC_CHANNELS.VAULT_DELETE, { isPaperTrading: mode === 'paper' })
          setKisTokenStatus('UNKNOWN')
          // 양쪽 모두 미등록 상태 — AuthPage 의 vault step 경로와 일관되게 재진입.
          // 라우팅 변경은 사용자 동선이 큰 변경이므로 confirm 동의 후에만 이동.
          // useNavigate 사용 — window.location.hash 직접 조작은 React Router 상태와 어긋남.
          navigate('/auth')
        } catch (err: unknown) {
          showIpcErrorToast(err)
        }
      }
    } else {
      // 비활성 모드 키 삭제 — 활성 모드 운영에는 영향 없음. 토글만 disabled 로 변경됨.
      // 비활성 모드 키 삭제 분기에 들어왔다는 것은 활성 모드 키가 등록되어 있다는 전제.
      // (활성 모드 키가 없으면 양쪽 미등록이거나 한쪽만 등록인데, 등록된 한쪽이 곧 활성 모드.)
      // 따라서 otherClause 는 항상 활성 모드 라벨 명시.
      const activeLabel = isPaperTrading ? '모의' : '실전'
      const otherClause = `\n${activeLabel} 키는 유지됩니다.`
      if (!confirm(`${modeLabel} KIS API 키를 삭제하시겠습니까?${otherClause}`)) return
      try {
        await ipc.invoke(IPC_CHANNELS.VAULT_DELETE, { isPaperTrading: mode === 'paper' })
      } catch (err: unknown) {
        showIpcErrorToast(err)
      }
    }
    await refreshCredsState()
  }

  /**
   * A3: 카드별 등록/수정 후 후처리 — 등록 상태 + 마스킹 응답 재조회.
   * 저장 자체는 KisCredentialEditor 가 직접 VAULT_SAVE 호출.
   */
  async function handleCardSaved(): Promise<void> {
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

  // KIS 라이브 상태 기반 타임라인.
  // dev 빌드: fixture 메타(AppKey, 만료시간, 핑 등) 결합 표시
  // prod 빌드: generic 메시지만 표시 (fixture 누출 방지)
  // 표시 기준은 "활성 모드의 키 등록 여부" — 비활성 모드 키만 등록된 상태에서 활성 모드가
  // 마치 사용 가능한 것처럼 보이지 않도록 (Security H1).
  const activeModeRegistered = hasCredentials[isPaperTrading ? 'paper' : 'real']
  const otherModeRegistered = hasCredentials[isPaperTrading ? 'real' : 'paper']
  const liveSteps: KisTimelineStep[] = [
    {
      id: 'apikey',
      title: activeModeRegistered ? 'API 키 등록됨' : 'API 키 미등록',
      sub: activeModeRegistered
        ? SHOW_DEV_KIS_META
          ? (
              <>
                AppKey: <b className="text-text-secondary font-medium">{kisStatusDevMock.appKey}</b> · 등록일{' '}
                {kisStatusDevMock.registeredAt}
              </>
            )
          : otherModeRegistered
            ? `API 키가 안전하게 저장되어 있습니다 (${isPaperTrading ? '실전' : '모의'} 키도 등록됨)`
            : 'API 키가 안전하게 저장되어 있습니다'
        : otherModeRegistered
          ? `${isPaperTrading ? '모의' : '실전'} 모드 키가 등록되지 않았습니다 (${isPaperTrading ? '실전' : '모의'} 키만 등록됨)`
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
      sub:
        kisTokenStatus === 'VALID'
          ? SHOW_DEV_KIS_META
            ? (
                <>
                  만료까지 <b className="text-text-secondary font-medium">{kisStatusDevMock.tokenExpiresIn}</b> 남음 · 자동 갱신{' '}
                  {kisStatusDevMock.autoRefresh ? 'ON' : 'OFF'}
                </>
              )
            : '토큰이 정상 발급되어 있습니다'
          : '토큰 재발급이 필요합니다',
      status: kisTokenStatus === 'VALID' ? 'done' : kisTokenStatus === 'EXPIRED' ? 'error' : 'pending',
    },
    {
      id: 'connection',
      title:
        activeModeRegistered && kisTokenStatus === 'VALID'
          ? '서버 연결 정상'
          : '서버 연결 대기',
      sub:
        activeModeRegistered && kisTokenStatus === 'VALID'
          ? SHOW_DEV_KIS_META
            ? (
                <>
                  마지막 핑 <b className="text-text-secondary font-medium">{kisStatusDevMock.lastPingAgo}</b> · 지연{' '}
                  <b className="text-text-secondary font-medium">{kisStatusDevMock.pingMs}ms</b>
                </>
              )
            : '정상 연결됨'
          : 'API 키와 토큰 등록 후 연결됩니다',
      status:
        activeModeRegistered && kisTokenStatus === 'VALID' ? 'done' : 'pending',
    },
  ]

  const isKisHealthy = activeModeRegistered && kisTokenStatus === 'VALID'

  return (
    <div className="max-w-2xl mx-auto py-8 flex flex-col gap-6">
      {/* 페이지 헤더 */}
      <div className="flex flex-col gap-1">
        <h1 className="text-text-primary text-xl font-semibold tracking-tight">설정</h1>
        <p className="text-text-tertiary text-base">
          거래 위험 관리 파라미터와 KIS 연동 상태를 관리합니다.
        </p>
      </div>

      {/* 카드 1 — 리스크 파라미터 */}
      <section className="bg-surface-1 border border-border-subtle rounded-xl p-6 flex flex-col gap-4">
        <div className="flex items-center gap-2.5">
          <div
            className="w-7 h-7 rounded-md grid place-items-center text-accent-400 flex-none"
            style={{
              background: 'rgba(16,185,129,0.08)',
              border: '1px solid rgba(16,185,129,0.2)',
            }}
          >
            <svg
              width="14"
              height="14"
              viewBox="0 0 16 16"
              fill="none"
              stroke="currentColor"
              strokeWidth="1.5"
            >
              <path d="M8 1.5l5.5 2v4.25c0 3.25-2.3 5.75-5.5 6.5-3.2-.75-5.5-3.25-5.5-6.5V3.5L8 1.5z" />
            </svg>
          </div>
          <div className="text-text-primary text-base font-semibold tracking-tight whitespace-nowrap">
            리스크 파라미터
          </div>
          {saved && (
            <span
              className="ml-auto inline-flex items-center gap-1 px-2 py-0.5 rounded-sm text-xs font-semibold tracking-wider whitespace-nowrap"
              style={{
                background: 'rgba(16,185,129,0.10)',
                color: '#34d399',
                border: '1px solid rgba(16,185,129,0.25)',
              }}
            >
              <span className="w-[5px] h-[5px] rounded-full bg-accent-500" />
              저장됨
            </span>
          )}
        </div>

        <form onSubmit={handleSave} className="flex flex-col">
          <div className="flex flex-col">
            {/* Row 1 — 1회 매수 비율 */}
            <SettingsRow
              label="1회 매수 비율"
              description="1회 시그널당 총 자산 대비 매수 비중"
              control={
                <Slider
                  value={Math.round(form.maxBuyRatio * 100)}
                  min={5}
                  max={50}
                  step={1}
                  onChange={(v) => setForm({ ...form, maxBuyRatio: v / 100 })}
                  formatValue={(v) => `${v}%`}
                  ariaLabel="1회 매수 비율"
                />
              }
              valueDisplay={
                <>
                  {Math.round(form.maxBuyRatio * 100)}
                  <span className="text-sm text-text-tertiary font-medium ml-0.5">%</span>
                </>
              }
            />

            {/* Row 2 — 최대 보유 비중 */}
            <SettingsRow
              label="최대 보유 비중"
              description="단일 종목 최대 포지션 한도"
              control={
                <Slider
                  value={Math.round(form.maxHoldingRatio * 100)}
                  min={10}
                  max={100}
                  step={1}
                  onChange={(v) => setForm({ ...form, maxHoldingRatio: v / 100 })}
                  formatValue={(v) => `${v}%`}
                  ariaLabel="최대 보유 비중"
                />
              }
              valueDisplay={
                <>
                  {Math.round(form.maxHoldingRatio * 100)}
                  <span className="text-sm text-text-tertiary font-medium ml-0.5">%</span>
                </>
              }
            />

            {/* Row 3 — 쿨다운 */}
            <SettingsRow
              label="쿨다운"
              description="동일 종목 재진입 대기 시간"
              control={
                <div className="flex flex-col gap-0.5">
                  <Stepper
                    value={form.cooldownMinutes}
                    min={1}
                    max={120}
                    step={1}
                    onChange={(v) => setForm({ ...form, cooldownMinutes: v })}
                    ariaLabel="쿨다운"
                  />
                  <div className="flex justify-between font-mono text-xs text-text-disabled px-0.5 mt-0.5">
                    <span>최소 1분</span>
                    <span>최대 120분</span>
                  </div>
                </div>
              }
              valueDisplay={
                <>
                  {form.cooldownMinutes}
                  <span className="text-sm text-text-tertiary font-medium ml-0.5">분</span>
                </>
              }
            />

            {/* Row 4 — 매매 Threshold (EMA) */}
            <SettingsRow
              label="매매 Threshold"
              description="AI 점수가 이 값 이상일 때만 신호 발동 (0.0 ~ 1.0)"
              control={
                <Slider
                  value={form.emaThreshold}
                  min={0}
                  max={1}
                  step={0.05}
                  onChange={(v) => setForm({ ...form, emaThreshold: v })}
                  formatValue={(v) => v.toFixed(2)}
                  ariaLabel="매매 Threshold"
                />
              }
              valueDisplay={form.emaThreshold.toFixed(2)}
              isLast
            />
          </div>

          {saveError && (
            <p className="text-sell text-sm mt-2">{saveError}</p>
          )}

          <div className="flex gap-2 justify-end pt-1 mt-2">
            <button
              type="button"
              onClick={handleReset}
              className="h-[34px] px-3.5 rounded-md text-sm font-semibold inline-flex items-center justify-center gap-1.5 bg-transparent border border-border-strong text-text-tertiary hover:bg-surface-2 hover:text-text-primary transition-colors"
            >
              기본값으로 초기화
            </button>
            <button
              type="submit"
              disabled={saving}
              className="h-[34px] px-3.5 rounded-md text-sm font-bold tracking-wide inline-flex items-center justify-center gap-1.5 bg-accent-500 hover:bg-accent-600 text-accent-foreground disabled:opacity-60 disabled:cursor-not-allowed transition-colors"
            >
              {saving ? '저장 중...' : '저장'}
            </button>
          </div>
        </form>
      </section>

      {/* 카드 2 — KIS Open API 연동 */}
      <section className="bg-surface-1 border border-border-subtle rounded-xl p-6 flex flex-col gap-4">
        <div className="flex items-center gap-2.5">
          <div
            className="w-7 h-7 rounded-md grid place-items-center text-accent-400 flex-none"
            style={{
              background: 'rgba(16,185,129,0.08)',
              border: '1px solid rgba(16,185,129,0.2)',
            }}
          >
            <svg
              width="14"
              height="14"
              viewBox="0 0 16 16"
              fill="none"
              stroke="currentColor"
              strokeWidth="1.5"
            >
              <path d="M6.5 9.5l-2 2a2 2 0 01-2.83-2.83l3-3a2 2 0 012.83 0M9.5 6.5l2-2a2 2 0 012.83 2.83l-3 3a2 2 0 01-2.83 0" />
            </svg>
          </div>
          <div className="text-text-primary text-base font-semibold tracking-tight whitespace-nowrap">
            KIS Open API 연동
          </div>
          <span
            className="ml-auto inline-flex items-center gap-1 px-2 py-0.5 rounded-sm text-xs font-semibold tracking-wider whitespace-nowrap"
            style={{
              background: isKisHealthy
                ? 'rgba(16,185,129,0.10)'
                : 'rgba(245,158,11,0.10)',
              color: isKisHealthy ? '#34d399' : '#f59e0b',
              border: isKisHealthy
                ? '1px solid rgba(16,185,129,0.25)'
                : '1px solid rgba(245,158,11,0.25)',
            }}
          >
            <span
              className="w-[5px] h-[5px] rounded-full"
              style={{ background: isKisHealthy ? '#10b981' : '#f59e0b' }}
            />
            {isKisHealthy ? '연결 정상' : '연결 대기'}
          </span>
        </div>

        {/* 환경 토글 — 모의/실전.
            A3: 양쪽 모두 등록된 경우에만 토글 활성. 한쪽만 / 양쪽 미등록 시 disabled + 안내 카피.
        */}
        {(() => {
          const bothRegistered = hasCredentials.paper && hasCredentials.real
          const noneRegistered = !hasCredentials.paper && !hasCredentials.real
          const toggleDisabled = paperToggleBusy || !bothRegistered
          const toggleHelp = bothRegistered
            ? isPaperTrading
              ? '모의 환경 (openapivts) — 가상 자금으로 주문 시뮬레이션'
              : '실전 환경 (openapi) — 실계좌로 주문 체결'
            : noneRegistered
              ? '아래 카드에서 KIS API 키를 등록하면 모드 전환을 사용할 수 있습니다.'
              : isPaperTrading
                ? '실전 키도 등록하면 전환할 수 있습니다.'
                : '모의 키도 등록하면 전환할 수 있습니다.'
          return (
            <div
              className="flex items-center justify-between gap-3 bg-surface-2 border border-border-subtle rounded-lg px-3 py-2.5"
              aria-live="polite"
            >
              <div className="flex flex-col gap-0.5 min-w-0">
                <span className="text-text-primary text-sm font-medium">모의 투자 모드</span>
                <span className="text-text-disabled text-xs leading-snug">{toggleHelp}</span>
              </div>
              <button
                type="button"
                role="switch"
                aria-checked={isPaperTrading}
                aria-label="모의 투자 모드"
                onClick={handleTogglePaperTrading}
                disabled={toggleDisabled}
                title={
                  !bothRegistered
                    ? '양쪽 모드 키가 모두 등록되어야 전환 가능합니다.'
                    : undefined
                }
                className={
                  'relative inline-flex h-6 w-11 flex-none items-center rounded-full transition-colors disabled:opacity-50 disabled:cursor-not-allowed ' +
                  (isPaperTrading ? 'bg-accent-500' : 'bg-surface-3 border border-border-strong')
                }
              >
                <span
                  className={
                    'inline-block h-4 w-4 transform rounded-full bg-white transition-transform ' +
                    (isPaperTrading ? 'translate-x-6' : 'translate-x-1')
                  }
                />
              </button>
            </div>
          )
        })()}

        {/* 보안 안내 */}
        <div className="text-sm text-text-secondary leading-[1.55] bg-surface-2 border border-border-subtle rounded-lg px-3 py-2.5 flex gap-2.5 items-start">
          <span className="text-accent-400 flex-none mt-0.5" aria-hidden>
            <svg
              width="14"
              height="14"
              viewBox="0 0 16 16"
              fill="none"
              stroke="currentColor"
              strokeWidth="1.5"
            >
              <rect x="3" y="7" width="10" height="7" rx="1.5" />
              <path d="M5 7V5a3 3 0 016 0v2" />
            </svg>
          </span>
          <span>
            API 키와 액세스 토큰은{' '}
            <b className="text-text-primary font-semibold">OS Credential Manager (keytar)</b>에 암호화 저장됩니다.
            본 앱은 평문 키를 파일로 보관하지 않습니다.
          </span>
        </div>

        {/* 3-step 타임라인 */}
        <KisStatusTimeline steps={liveSteps} />

        {/* A3: 모드별 자격증명 카드 두 개. 활성 배지 + 마스킹 표시 + 등록/수정/삭제 액션 */}
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
          <KisCredentialCard
            mode="paper"
            isActive={isPaperTrading}
            registered={hasCredentials.paper}
            masked={maskedCreds.paper}
            onSaved={handleCardSaved}
            onDelete={() => handleCardDelete('paper')}
          />
          <KisCredentialCard
            mode="real"
            isActive={!isPaperTrading}
            registered={hasCredentials.real}
            masked={maskedCreds.real}
            onSaved={handleCardSaved}
            onDelete={() => handleCardDelete('real')}
          />
        </div>

        {/* 액션 버튼 — API 키 삭제는 카드 [삭제] 버튼으로 이전됨. */}
        <div className="flex items-center gap-2 pt-1.5">
          <button
            type="button"
            onClick={handleIssueToken}
            className="h-[34px] px-3.5 rounded-md text-sm font-semibold inline-flex items-center justify-center gap-1.5 bg-transparent text-accent-400 hover:bg-accent-500/10 transition-colors"
            style={{ border: '1px solid rgba(16,185,129,0.35)' }}
          >
            토큰 재발급
          </button>
          <button
            type="button"
            onClick={() => {
              // TODO(impl): shell.openExternal('https://apiportal.koreainvestment.com') (별도 PR)
              // 보안: URL 화이트리스트 검증 (koreainvestment.com 도메인) + state 파라미터 + main 프로세스 IPC 경유
              console.log('[SettingsPage] open KIS portal (noop)')
            }}
            className="ml-auto text-text-tertiary text-sm hover:text-text-primary inline-flex items-center gap-1 bg-transparent border-0 p-0 cursor-pointer"
          >
            KIS 개발자 포털 열기 ↗
          </button>
        </div>
      </section>
    </div>
  )
}

/* -------------------------------------------------------------------------- */
/* SettingsRow — 라벨(설명) / 컨트롤 / 값 세 컬럼 그리드 행                    */
/* -------------------------------------------------------------------------- */
function SettingsRow({
  label,
  description,
  control,
  valueDisplay,
  isLast = false,
}: {
  label: string
  description: string
  control: React.ReactNode
  valueDisplay: React.ReactNode
  isLast?: boolean
}) {
  return (
    <div
      className={`grid gap-4 items-center py-3.5 ${isLast ? '' : 'border-b border-border-subtle'}`}
      style={{ gridTemplateColumns: '1fr 280px 80px' }}
    >
      <div className="flex flex-col gap-1 min-w-0">
        <span className="text-text-primary text-base font-medium">{label}</span>
        <span className="text-text-disabled text-xs leading-snug">{description}</span>
      </div>
      <div className="min-w-0">{control}</div>
      <div className="font-mono text-lg font-semibold text-text-primary text-right tabular-nums tracking-tight">
        {valueDisplay}
      </div>
    </div>
  )
}

/* -------------------------------------------------------------------------- */
/* KisCredentialCard — A3: 모드별 자격증명 카드.                                */
/*                                                                              */
/* 표시:                                                                        */
/*   - 활성 배지 (현재 활성 모드인 경우)                                          */
/*   - 등록됨 → 마스킹된 appKey/accountNo + [수정] [삭제]                          */
/*   - 미등록 → "미등록" 안내 + [등록]                                             */
/*                                                                              */
/* [수정]/[등록] 클릭 시 인라인 폼 토글 — 모달 인프라 도입 회피.                    */
/* -------------------------------------------------------------------------- */
function KisCredentialCard({
  mode,
  isActive,
  registered,
  masked,
  onSaved,
  onDelete,
}: {
  mode: 'paper' | 'real'
  isActive: boolean
  registered: boolean
  masked: { appKeyMasked: string; accountNoMasked: string } | null
  onSaved: () => Promise<void> | void
  onDelete: () => void | Promise<void>
}) {
  const [editing, setEditing] = useState(false)

  const title = mode === 'paper' ? 'KIS 모의투자' : 'KIS 실전투자'
  const tone =
    mode === 'paper'
      ? { color: '#f59e0b', border: 'rgba(245,158,11,0.3)', bg: 'rgba(245,158,11,0.06)' }
      : { color: '#ef4444', border: 'rgba(239,68,68,0.3)', bg: 'rgba(239,68,68,0.06)' }

  return (
    <div
      className="rounded-lg border bg-surface-2 px-3.5 py-3 flex flex-col gap-2.5"
      style={{ borderColor: tone.border, background: tone.bg }}
    >
      <div className="flex items-center gap-2">
        <span
          className="text-sm font-semibold tracking-tight"
          style={{ color: tone.color }}
        >
          {title}
        </span>
        {isActive && registered && (
          <span
            className="ml-auto inline-flex items-center gap-1 px-2 py-0.5 rounded-sm text-[10px] font-semibold tracking-wider whitespace-nowrap"
            style={{
              background: 'rgba(16,185,129,0.10)',
              color: '#34d399',
              border: '1px solid rgba(16,185,129,0.25)',
            }}
          >
            <span className="w-[5px] h-[5px] rounded-full bg-accent-500" />
            활성
          </span>
        )}
      </div>

      {!editing && registered && masked && (
        <div className="flex flex-col gap-1.5 font-mono text-xs">
          <div className="flex items-center gap-2">
            <span className="text-text-disabled w-16 flex-none">계좌</span>
            <span className="text-text-primary tabular-nums tracking-wide">
              {masked.accountNoMasked}
            </span>
          </div>
          <div className="flex items-center gap-2">
            <span className="text-text-disabled w-16 flex-none">AppKey</span>
            <span className="text-text-primary tabular-nums tracking-wide">
              {masked.appKeyMasked}
            </span>
          </div>
        </div>
      )}

      {!editing && !registered && (
        <div className="flex items-center gap-2 text-text-disabled text-xs">
          <svg
            width="13"
            height="13"
            viewBox="0 0 14 14"
            fill="none"
            stroke="currentColor"
            strokeWidth="1.5"
            aria-hidden
          >
            <circle cx="7" cy="7" r="5.5" />
            <path d="M7 4v3.5M7 9.5v.5" />
          </svg>
          <span>미등록</span>
        </div>
      )}

      {editing && (
        <KisCredentialEditor
          mode={mode}
          onCancel={() => setEditing(false)}
          onSaved={async () => {
            setEditing(false)
            await onSaved()
          }}
        />
      )}

      {!editing && (
        <div className="flex items-center gap-2 pt-0.5">
          {registered ? (
            <>
              <button
                type="button"
                onClick={() => setEditing(true)}
                className="h-[28px] px-2.5 rounded-md text-xs font-semibold bg-transparent text-text-secondary hover:bg-surface-3 hover:text-text-primary transition-colors"
                style={{ border: '1px solid rgba(255,255,255,0.12)' }}
              >
                수정
              </button>
              <button
                type="button"
                onClick={() => {
                  void onDelete()
                }}
                className="h-[28px] px-2.5 rounded-md text-xs font-semibold bg-transparent text-sell hover:bg-sell/10 transition-colors"
                style={{ border: '1px solid #3f1d1d' }}
              >
                삭제
              </button>
            </>
          ) : (
            <button
              type="button"
              onClick={() => setEditing(true)}
              className="h-[28px] px-2.5 rounded-md text-xs font-semibold bg-accent-500 hover:bg-accent-600 text-accent-foreground transition-colors"
            >
              등록
            </button>
          )}
        </div>
      )}
    </div>
  )
}

/* -------------------------------------------------------------------------- */
/* KisCredentialEditor — 카드 내 인라인 등록/수정 폼.                            */
/*                                                                              */
/* AppKey/AppSecret/계좌번호 세 필드 입력 후 VAULT_SAVE(mode) 호출.              */
/* 비활성 모드 수정도 안전 — KisService.saveCredentials 가 활성 모드 일치 시에만 */
/* 토큰 발급 시도 (vaultHandlers 가 활성 모드 가드).                             */
/* -------------------------------------------------------------------------- */
function KisCredentialEditor({
  mode,
  onCancel,
  onSaved,
}: {
  mode: 'paper' | 'real'
  onCancel: () => void
  onSaved: () => Promise<void> | void
}) {
  const [appKey, setAppKey] = useState('')
  const [appSecret, setAppSecret] = useState('')
  const [accountNo, setAccountNo] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)

  // 언마운트 시 입력값 명시 clear — react state 가 GC 대기에 걸려 secret 이 메모리 잔존하는
  // 위험 차단 (review hotfix #3). submit 시는 별도로 비우지만 cancel/parent unmount 경로 보강.
  useEffect(
    () => () => {
      setAppKey('')
      setAppSecret('')
      setAccountNo('')
    },
    [],
  )

  function handleCancel() {
    // 취소 시 입력값 즉시 폐기 — onCancel 이 부모의 editing=false 를 트리거해 unmount 되지만,
    // 명시 clear 로 기록상 의도를 분명히 함.
    setAppKey('')
    setAppSecret('')
    setAccountNo('')
    onCancel()
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setError(null)
    if (appKey.trim() === '' || appSecret.trim() === '' || accountNo.trim() === '') {
      setError('모든 필드를 입력해주세요.')
      return
    }
    setSaving(true)
    try {
      await ipc.invoke(IPC_CHANNELS.VAULT_SAVE, {
        appKey: appKey.trim(),
        appSecret: appSecret.trim(),
        accountNo: accountNo.trim(),
        isPaperTrading: mode === 'paper',
      })
      // 폼 메모리에서 입력값 폐기 — secret 잔류 회피.
      setAppKey('')
      setAppSecret('')
      setAccountNo('')
      await onSaved()
    } catch (err: unknown) {
      const fallback = err instanceof Error ? err.message : '저장에 실패했습니다.'
      setError(fallback)
      showIpcErrorToast(err)
    } finally {
      setSaving(false)
    }
  }

  return (
    <form onSubmit={handleSubmit} className="flex flex-col gap-2 mt-1">
      <AuthInputField
        label="App Key"
        value={appKey}
        onChange={(e) => setAppKey(e.target.value)}
      />
      <AuthInputField
        label="App Secret"
        isPassword
        value={appSecret}
        onChange={(e) => setAppSecret(e.target.value)}
      />
      <AuthInputField
        label="계좌번호"
        value={accountNo}
        onChange={(e) => setAccountNo(e.target.value)}
      />
      {error && <p className="text-sell text-xs">{error}</p>}
      <div className="flex items-center gap-2 pt-0.5">
        <button
          type="submit"
          disabled={saving}
          className="h-[28px] px-2.5 rounded-md text-xs font-semibold bg-accent-500 hover:bg-accent-600 text-accent-foreground disabled:opacity-60 disabled:cursor-not-allowed transition-colors"
        >
          {saving ? '저장 중...' : '저장'}
        </button>
        <button
          type="button"
          onClick={handleCancel}
          disabled={saving}
          className="h-[28px] px-2.5 rounded-md text-xs font-semibold bg-transparent text-text-tertiary hover:bg-surface-3 hover:text-text-primary disabled:opacity-60 disabled:cursor-not-allowed transition-colors"
          style={{ border: '1px solid rgba(255,255,255,0.12)' }}
        >
          취소
        </button>
      </div>
    </form>
  )
}
