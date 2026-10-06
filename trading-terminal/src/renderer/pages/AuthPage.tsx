import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { ipc, IPC_CHANNELS, isMac } from '../lib/ipc'
import { useConnectionStore } from '../store/useConnectionStore'
import { useUserStore } from '../store/useUserStore'
import AuthBrandSection from '../components/auth/AuthBrandSection'
import AuthInputField from '../components/auth/AuthInputField'
import OAuthButton from '../components/auth/OAuthButton'
import { notifyComingSoon } from '../components/auth/notifyComingSoon'
import KisKeyForm, {
  KIS_MODE_LABEL,
  type KisMode,
  type VaultSavePayload,
} from '../components/settings/KisKeyForm'
import SegmentedControl from '../components/common/SegmentedControl'
import Modal from '../components/common/Modal'
import { showIpcErrorToast } from '../components/common/Toast'
import { isIpcError } from '../../lib/types/ipcError'

// vault = 첫 로그인 직후 KIS 키 등록 권유
type Step = 'login' | 'vault'

/**
 * VAULT_HAS 응답: A2 부터 모드별 객체로 변경.
 * A3 에서 paper/real 카드 분리 시까지는 "둘 중 하나라도 등록되어 있으면" 진입 가능 — 기존 흐름과 호환.
 */
type VaultHasResponse = { paper: boolean; real: boolean }

export default function AuthPage() {
  const [step, setStep] = useState<Step>('login')
  const navigate = useNavigate()
  const { setAuthenticated, setHasCredentials } = useConnectionStore()
  const { setUser, setAccountType } = useUserStore()

  async function handleLoginSuccess(user: any, accountType?: string) {
    setUser(user)
    if (accountType) setAccountType(accountType as any)

    // VAULT_HAS 를 먼저 조회한다. 인증 상태를 먼저 켜면 조회가 실패했을 때
    // 자격증명 등록 여부를 모른 채 대시보드/vault 중 어디로도 못 가고 멈춘다.
    let hasCredentials: VaultHasResponse | null = null
    try {
      hasCredentials = await ipc.invoke<VaultHasResponse>(IPC_CHANNELS.VAULT_HAS)
    } catch (err: unknown) {
      // 조회에 실패하면 등록 여부를 모른다. 권유 화면은 늘 신규 등록이라 이미 있는 키를 덮어쓸 수 있으므로
      // 홈으로 보내고, 등록은 설정에 맡긴다.
      showIpcErrorToast(err)
    }
    setHasCredentials(hasCredentials ?? { paper: false, real: false })
    setAuthenticated(true)
    if (hasCredentials === null || hasCredentials.paper || hasCredentials.real) {
      navigate('/home')
    } else {
      setStep('vault')
    }
  }

  async function handleVaultSaved() {
    // 저장 직후 양쪽 모드 등록 상태 재조회 — 이번 저장이 어느 모드였는지에 따라 paper/real 갱신.
    try {
      const has = await ipc.invoke<VaultHasResponse>(IPC_CHANNELS.VAULT_HAS)
      setHasCredentials(has)
    } catch {
      // 조회 실패 시 최소한 현재 저장한 흐름이 있다는 사실을 반영해 양쪽 true 처리는 하지 않음.
      // 다음 SettingsPage 마운트 시 재조회로 보정.
    }
    navigate('/home')
  }

  return (
    <div className="relative h-screen w-screen overflow-hidden bg-bg-base text-ink-2">
      {/*
        macOS 창 드래그 영역. 이 화면에는 메뉴가 없어 창을 잡을 곳이 없다.
        상단 40px 는 비어 있어 겹치는 컨트롤이 없다.
      */}
      {isMac && (
        <div className="absolute top-0 left-0 right-0 h-10 z-[5] [-webkit-app-region:drag]" aria-hidden />
      )}

      {/* 왼쪽 아래: 언어 선택 자리 — 지금은 한국어 고정 */}
      <div className="absolute bottom-4 left-4 z-10">
        <button
          type="button"
          aria-disabled="true"
          title="준비 중입니다"
          className="text-[12px] text-ink-4 hover:text-ink-3 bg-transparent border-0 p-0 cursor-default"
          onClick={() => notifyComingSoon('언어 선택')}
        >
          한국어
        </button>
      </div>

      {/* 가운데 열 */}
      <div className="relative z-[2] h-full overflow-y-auto box-border flex flex-col items-center justify-center px-4 py-10 gap-5">
        <AuthBrandSection />

        {step === 'login' ? (
          <LoginForm onSuccess={handleLoginSuccess} />
        ) : (
          <KisKeyOffer onSaved={handleVaultSaved} onSkip={() => navigate('/home')} />
        )}
      </div>
    </div>
  )
}

/* -------------------------------------------------------------------------- */
/* LoginForm — 디자인 캔버스 기준 마크업 + 기존 IPC 호출 보존                 */
/* -------------------------------------------------------------------------- */
function LoginForm({ onSuccess }: { onSuccess: (user: any, accountType?: string) => Promise<void> }) {
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const [oauthLoading, setOauthLoading] = useState<'google' | 'kakao' | null>(null)

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setError(null)
    setLoading(true)
    try {
      const result = await ipc.invoke<{ user: any; accountType?: string }>(
        IPC_CHANNELS.AUTH_LOGIN,
        { email, password },
      )
      await onSuccess(result.user, result.accountType)
    } catch (err: any) {
      // user enumeration 방지: 백엔드의 "이메일 없음"/"비밀번호 틀림" 구분
      // 메시지를 그대로 노출하지 않고 generic 메시지로 통일.
      // 네트워크 오류만 별도 분기 (TypeError 또는 'fetch' 키워드 포함 시).
      const isNetworkError =
        err instanceof TypeError ||
        (typeof err?.message === 'string' &&
          /fetch|network|econnrefused|enotfound/i.test(err.message))

      if (isNetworkError) {
        setError('서버에 연결할 수 없습니다. 잠시 후 다시 시도하세요.')
      } else {
        setError('이메일 또는 비밀번호가 올바르지 않습니다.')
      }
      // 원본 에러는 devtools 한정으로만 보존
      console.debug('[auth] login failed:', err)
      // 인증 실패(잘못된 비밀번호 등)는 인라인 메시지로 충분하다.
      // 서버·네트워크 장애일 때만 toast 를 추가로 띄운다.
      if (isIpcError(err) && (err.code === 'NETWORK' || err.code === 'BACKEND_5XX')) {
        showIpcErrorToast(err)
      }
    } finally {
      setLoading(false)
    }
  }

  async function handleOAuth(provider: 'google' | 'kakao') {
    setError(null)
    setOauthLoading(provider)
    try {
      // Main 프로세스가 RFC 8252 Loopback 흐름으로 PKCE+state+localhost:9000 서버를 띄우고
      // 사용자의 기본 브라우저로 provider 인증 페이지를 연다. 콜백 수신 → 백엔드 교환 → 결과 반환.
      const result = await ipc.invoke<{ user: any; accountType?: string }>(
        IPC_CHANNELS.AUTH_OAUTH_START,
        { provider },
      )
      await onSuccess(result.user, result.accountType)
    } catch (err: any) {
      // user enumeration 방지: 백엔드 메시지를 그대로 노출하지 않고 generic 메시지로 통일
      setError('소셜 로그인에 실패했습니다. 다시 시도해 주세요.')
      console.debug('[auth] oauth failed:', err)
      if (isIpcError(err) && (err.code === 'NETWORK' || err.code === 'BACKEND_5XX')) {
        showIpcErrorToast(err)
      }
    } finally {
      setOauthLoading(null)
    }
  }

  const busy = loading || oauthLoading !== null

  return (
    <>
      <div className="frost rim rim-float w-[400px] max-w-full rounded-[var(--radius-sheet)] px-8 pt-7 pb-7">
        <form onSubmit={handleSubmit} className="flex flex-col">
          <h1 className="text-ink-1 text-[19px] font-bold">로그인</h1>

          <div className="flex flex-col gap-3 mt-5">
            <AuthInputField
              label="이메일"
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              required
              autoComplete="username"
            />
            <AuthInputField
              label="비밀번호"
              isPassword
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
              autoComplete="current-password"
              labelTrailing={
                <button
                  type="button"
                  aria-disabled="true"
                  title="준비 중입니다"
                  className="text-ink-4 text-[12px] bg-transparent border-0 p-0 cursor-default whitespace-nowrap"
                  onClick={() => notifyComingSoon('비밀번호 찾기')}
                >
                  비밀번호 찾기
                </button>
              }
            />
          </div>

          {/*
            자동 로그인 자리. 로그인 정보를 디스크에 남기지 않으므로 아직 동작하지 않는다
            (ux.md "아직 정하지 않은 것"). 켜진 것처럼 보이지 않게 빈 상자로 둔다.
          */}
          <button
            type="button"
            aria-disabled="true"
            title="준비 중입니다"
            onClick={() => notifyComingSoon('자동 로그인')}
            className="inline-flex items-center gap-2 self-start mt-3.5 bg-transparent border-0 p-0 cursor-default opacity-60"
          >
            <span className="w-4 h-4 rounded-[5px] border border-border-strong" aria-hidden />
            <span className="text-ink-3 text-[13px]">자동 로그인</span>
          </button>

          <p className="min-h-[18px] mt-3 text-danger text-[13px] leading-snug" role="alert">
            {error}
          </p>

          <button type="submit" disabled={busy} className="gbtn gbtn-lapis w-full mt-1">
            {loading ? '로그인 중' : '로그인'}
          </button>

          <div className="flex items-center gap-3 mt-5">
            <span className="flex-1 h-px bg-border-subtle" />
            <span className="text-ink-4 text-[12px] whitespace-nowrap">또는</span>
            <span className="flex-1 h-px bg-border-subtle" />
          </div>

          {/* 소셜 로그인 — 진행 중에는 다른 provider 와 이메일 로그인 모두 비활성 */}
          <div className="flex flex-col gap-2.5 mt-4">
            <OAuthButton
              provider="google"
              onClick={() => handleOAuth('google')}
              disabled={busy}
              loading={oauthLoading === 'google'}
            />
            <OAuthButton
              provider="kakao"
              onClick={() => handleOAuth('kakao')}
              disabled={busy}
              loading={oauthLoading === 'kakao'}
            />
          </div>
        </form>
      </div>

      <div className="flex flex-col items-center gap-1.5">
        <p className="text-ink-3 text-[13px]">
          계정이 없으면{' '}
          <button
            type="button"
            aria-disabled="true"
            title="준비 중입니다"
            className="text-ink-3 underline underline-offset-2 decoration-ink-4 bg-transparent border-0 p-0 cursor-default"
            onClick={() => notifyComingSoon('웹사이트 가입')}
          >
            웹사이트에서 가입
          </button>
        </p>
        <span className="num text-ink-4 text-[11px]">v1.0.0</span>
      </div>
    </>
  )
}

/* -------------------------------------------------------------------------- */
/* KisKeyOffer — 첫 로그인 직후 키 등록 권유. 건너뛰고 홈으로 갈 수 있다.          */
/* 모의 · 실전 중 하나를 골라 키 한 벌만 받는다. 고른 모드가 활성 모드가 된다.      */
/* -------------------------------------------------------------------------- */
const MODE_ITEMS: { id: KisMode; label: string }[] = [
  { id: 'paper', label: KIS_MODE_LABEL.paper },
  { id: 'real', label: KIS_MODE_LABEL.real },
]

function KisKeyOffer({ onSaved, onSkip }: { onSaved: () => Promise<void>; onSkip: () => void }) {
  const [mode, setMode] = useState<KisMode>('paper')
  const [saving, setSaving] = useState(false)
  // 처음 그릴 때만 App Key 칸에 포커스를 준다 — 화살표로 계좌를 바꿀 때는 전환에 포커스를 둔다
  const [focusForm, setFocusForm] = useState(true)
  const [confirmReal, setConfirmReal] = useState<((ok: boolean) => void) | null>(null)

  function handleModeChange(next: KisMode) {
    setFocusForm(false)
    setMode(next)
  }

  // 실전 계좌는 저장 전에 한 번 더 묻는다 (설정의 실전 전환과 같은 마찰)
  function confirmSubmit(): Promise<boolean> {
    if (mode !== 'real') return Promise.resolve(true)
    return new Promise((resolve) => setConfirmReal(() => resolve))
  }

  function closeConfirm(ok: boolean) {
    confirmReal?.(ok)
    setConfirmReal(null)
  }

  async function handleSubmit(payload: VaultSavePayload) {
    // 활성 모드를 먼저 정해 두면 VAULT_SAVE 가 같은 모드일 때 저장 직후 토큰을 발급한다.
    // SETTINGS_SET_PAPER_TRADING 은 런타임을 무효화하므로 VAULT_SAVE 보다 먼저 부른다.
    const prev = await ipc.invoke<boolean>(IPC_CHANNELS.SETTINGS_GET_PAPER_TRADING)
    await ipc.invoke(IPC_CHANNELS.SETTINGS_SET_PAPER_TRADING, { value: payload.isPaperTrading })
    try {
      await ipc.invoke(IPC_CHANNELS.VAULT_SAVE, payload)
    } catch (err) {
      // 저장이 실패하면 모드를 되돌린다 — 키 없는 실전 모드로 남은 채 `나중에` 로 들어가지 않게
      if (typeof prev === 'boolean' && prev !== payload.isPaperTrading) {
        await ipc.invoke(IPC_CHANNELS.SETTINGS_SET_PAPER_TRADING, { value: prev }).catch(() => {})
      }
      throw err
    }
    await onSaved()
  }

  return (
    <div className="frost rim rim-float w-[440px] max-w-full rounded-[var(--radius-sheet)] px-8 pt-7 pb-7 flex flex-col gap-5">
      <div className="flex flex-col gap-1.5">
        <h1 className="text-ink-1 text-[19px] font-bold">주문용 KIS 키 등록</h1>
        <p className="text-ink-3 text-[13px] leading-relaxed">
          어닝콜 분석은 키 없이 모두 쓸 수 있습니다. 주문하려면 한국투자증권 Open API 키가 필요하고,
          나중에 설정에서 등록해도 됩니다.
        </p>
      </div>

      <div className="flex flex-col gap-2">
        {/* 저장 중에는 계좌를 바꾸지 못하게 막는다 */}
        <fieldset disabled={saving} className="contents">
          <SegmentedControl items={MODE_ITEMS} activeId={mode} onChange={handleModeChange} className="self-start" />
        </fieldset>
        <p className={`text-[12.5px] leading-snug ${mode === 'real' ? 'text-warning' : 'text-ink-3'}`} aria-live="polite">
          {mode === 'real'
            ? '실제 돈으로 주문하는 계좌입니다. 체결되면 되돌릴 수 없습니다.'
            : '모의투자 서버로 주문합니다. 실제 돈은 움직이지 않습니다.'}
        </p>
      </div>

      {/* 모드를 바꾸면 폼을 새로 그려 입력값을 비운다 — 다른 계좌의 키가 섞여 저장되지 않게 */}
      <KisKeyForm
        key={mode}
        mode={mode}
        submitLabel="저장하고 시작"
        secondaryLabel="나중에"
        onSecondary={onSkip}
        onSubmit={handleSubmit}
        confirmSubmit={confirmSubmit}
        onSavingChange={setSaving}
        autoFocus={focusForm}
      />

      <Modal open={confirmReal !== null} onClose={() => closeConfirm(false)} ariaLabel="실전투자 키 저장 확인">
        <div className="w-[400px] max-w-[90vw] p-7 flex flex-col gap-3">
          <h2 className="text-ink-1 text-[17px] font-bold">실전투자 계좌로 시작할까요?</h2>
          <p className="text-ink-2 text-[13.5px] leading-relaxed">
            저장하면 이 계좌로 실제 돈을 주문합니다. 모의투자로 먼저 써 보려면 취소하고 모의투자를 고릅니다.
          </p>
          <div className="flex items-center justify-between gap-2 mt-3">
            <button type="button" onClick={() => closeConfirm(false)} className="gbtn">
              취소
            </button>
            <button type="button" onClick={() => closeConfirm(true)} className="gbtn gbtn-porphyra">
              실전투자로 저장
            </button>
          </div>
        </div>
      </Modal>
    </div>
  )
}
