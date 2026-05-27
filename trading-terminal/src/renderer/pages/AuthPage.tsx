import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { ipc, IPC_CHANNELS } from '../lib/ipc'
import { useConnectionStore } from '../store/useConnectionStore'
import { useUserStore } from '../store/useUserStore'
import AuthBrandSection from '../components/auth/AuthBrandSection'
import AuthInputField from '../components/auth/AuthInputField'
import OAuthButton from '../components/auth/OAuthButton'
import { showIpcErrorToast } from '../components/common/Toast'

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
  const { setUser, setSettings, setAccountType } = useUserStore()

  async function handleLoginSuccess(user: any, settings: any, accountType?: string) {
    setUser(user)
    if (settings) {
      setSettings({
        tradingMode: settings.tradingMode,
        maxBuyRatio: settings.buyAmountRatio,
        maxHoldingRatio: settings.maxPositionRatio,
        cooldownMinutes: settings.cooldownMinutes,
      })
    }
    if (accountType) setAccountType(accountType as any)
    setAuthenticated(true)
    const hasCredentials = await ipc.invoke<VaultHasResponse>(IPC_CHANNELS.VAULT_HAS)
    const anyRegistered = hasCredentials.paper || hasCredentials.real
    setHasCredentials(hasCredentials)
    if (anyRegistered) {
      navigate('/dashboard')
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
    navigate('/dashboard')
  }

  return (
    <div className="relative h-screen w-screen overflow-hidden bg-bg-base text-text-secondary">
      {/* 배경: radial glow + grid overlay */}
      <div
        className="absolute inset-0 pointer-events-none"
        aria-hidden
        style={{
          background:
            'radial-gradient(circle at 50% 15%, rgba(16,185,129,0.10), transparent 55%),' +
            'radial-gradient(circle at 15% 90%, rgba(16,185,129,0.04), transparent 45%),' +
            'radial-gradient(circle at 85% 85%, rgba(59,130,246,0.03), transparent 45%)',
        }}
      />
      <div
        className="absolute inset-0 pointer-events-none"
        aria-hidden
        style={{
          opacity: 0.04,
          backgroundImage:
            'linear-gradient(rgba(255,255,255,.5) 1px, transparent 1px),' +
            'linear-gradient(90deg, rgba(255,255,255,.5) 1px, transparent 1px)',
          backgroundSize: '48px 48px',
          maskImage:
            'radial-gradient(ellipse 60% 60% at 50% 50%, black 30%, transparent 80%)',
          WebkitMaskImage:
            'radial-gradient(ellipse 60% 60% at 50% 50%, black 30%, transparent 80%)',
        }}
      />

      {/* 우상단: 빌드 해시 */}
      <div className="absolute top-4 right-4 z-10 font-mono text-xs text-text-disabled tracking-wider">
        build 2604.18
      </div>

      {/* 좌하단: 언어 선택 (UI only) */}
      <div className="absolute bottom-4 left-4 z-10">
        <button
          type="button"
          className="font-mono text-xs text-text-disabled hover:text-text-tertiary tracking-wider"
          onClick={() => {
            // TODO(impl): i18n locale switcher (PR 후속 — 현재 KO 고정)
            console.log('[AuthPage] language switcher clicked (noop)')
          }}
        >
          KO ▾
        </button>
      </div>

      {/* 중앙 column */}
      <div className="relative z-[2] min-h-full box-border flex flex-col items-center justify-center px-4 py-10 gap-3.5">
        <AuthBrandSection />

        {step === 'login' ? (
          <LoginForm onSuccess={handleLoginSuccess} />
        ) : (
          <KisVaultDualForm onSuccess={handleVaultSaved} />
        )}
      </div>

    </div>
  )
}

/* -------------------------------------------------------------------------- */
/* LoginForm — 디자인 캔버스 기준 마크업 + 기존 IPC 호출 보존                 */
/* -------------------------------------------------------------------------- */
function LoginForm({ onSuccess }: { onSuccess: (user: any, settings: any, accountType?: string) => void }) {
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [rememberMe, setRememberMe] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const [oauthLoading, setOauthLoading] = useState<'google' | 'kakao' | null>(null)

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setError(null)
    setLoading(true)
    try {
      const result = await ipc.invoke<{ user: any; settings: any; accountType?: string }>(
        IPC_CHANNELS.AUTH_LOGIN,
        { email, password },
      )
      onSuccess(result.user, result.settings, result.accountType)
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
      // form 위 인라인 에러 + toast 동시 노출 — 사용자가 두 위치 모두에서 인지 가능.
      showIpcErrorToast(err)
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
      const result = await ipc.invoke<{ user: any; settings: any; accountType?: string }>(
        IPC_CHANNELS.AUTH_OAUTH_START,
        { provider },
      )
      onSuccess(result.user, result.settings, result.accountType)
    } catch (err: any) {
      // user enumeration 방지: 백엔드 메시지를 그대로 노출하지 않고 generic 메시지로 통일
      setError('소셜 로그인에 실패했습니다. 다시 시도해 주세요.')
      console.debug('[auth] oauth failed:', err)
      showIpcErrorToast(err)
    } finally {
      setOauthLoading(null)
    }
  }

  return (
    <>
      <div
        className="w-[380px] max-w-full bg-surface-1 border border-border-subtle rounded-xl px-[26px] pt-5 pb-[22px]"
        style={{
          boxShadow:
            '0 20px 50px rgba(0,0,0,.45), 0 1px 0 rgba(255,255,255,.02) inset',
        }}
      >
        <form onSubmit={handleSubmit} className="flex flex-col">
          <div className="text-text-primary text-base font-semibold tracking-tight whitespace-nowrap">
            로그인
          </div>
          <div className="text-text-tertiary text-sm mt-1">
            계정 정보로 터미널에 접속하세요
          </div>

          <div className="flex flex-col gap-2.5 mt-3.5">
            <AuthInputField
              label="이메일"
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              required
              autoComplete="username"
              leadingIcon={
                <svg
                  width="13"
                  height="13"
                  viewBox="0 0 14 14"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="1.5"
                >
                  <rect x="1.5" y="3" width="11" height="8" rx="1.5" />
                  <path d="M2 4l5 3.5L12 4" />
                </svg>
              }
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
                  className="text-text-tertiary text-xs hover:text-accent-400 whitespace-nowrap"
                  onClick={() => {
                    // TODO(impl): 비밀번호 찾기 플로우 (별도 PR)
                    console.log('[AuthPage] password reset clicked (noop)')
                  }}
                >
                  비밀번호 찾기
                </button>
              }
              leadingIcon={
                <svg
                  width="13"
                  height="13"
                  viewBox="0 0 14 14"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="1.5"
                >
                  <rect x="2.5" y="6" width="9" height="6.5" rx="1" />
                  <path d="M4.5 6V4a2.5 2.5 0 015 0v2" />
                </svg>
              }
            />
          </div>

          {/* 옵션 행 */}
          <div className="flex items-center justify-between gap-2.5 mt-3">
            <label className="inline-flex items-center gap-2 cursor-pointer select-none">
              {/*
                peer 패턴: input 이 sr-only 지만 :focus-visible 시 옆 span 에
                키보드 포커스 링을 그려 a11y 포커스 시각화 보장.
                인라인 hex (#10b981 / #242e3f) → 디자인 토큰화.
              */}
              <input
                type="checkbox"
                checked={rememberMe}
                onChange={(e) => setRememberMe(e.target.checked)}
                className="peer sr-only"
              />
              <span
                className={`w-3.5 h-3.5 rounded-sm grid place-items-center transition-colors ${
                  rememberMe ? 'bg-accent-500' : 'bg-surface-3'
                } peer-focus-visible:ring-2 peer-focus-visible:ring-accent-500/40 peer-focus-visible:ring-offset-2 peer-focus-visible:ring-offset-surface-1`}
                style={{ boxShadow: 'inset 0 0 0 1px rgba(255,255,255,.12)' }}
                aria-hidden
              >
                {rememberMe && (
                  <svg
                    width="9"
                    height="9"
                    viewBox="0 0 12 12"
                    fill="none"
                    stroke="#0b1017"
                    strokeWidth="2.6"
                  >
                    <path d="M2.5 6.2l2.3 2.3L9.5 3.7" />
                  </svg>
                )}
              </span>
              <span className="text-text-secondary text-sm whitespace-nowrap">
                자동 로그인
              </span>
            </label>
          </div>

          {/* 에러 영역 — 디자인은 비워두지만 공간 확보 */}
          <div className={`min-h-[16px] mt-2 transition-opacity ${error ? 'opacity-100' : 'opacity-0'}`}>
            {error && <p className="text-sell text-sm">{error}</p>}
          </div>

          <button
            type="submit"
            disabled={loading || oauthLoading !== null}
            className="w-full h-[38px] rounded-lg bg-accent-500 hover:bg-accent-600 text-accent-foreground font-semibold text-base inline-flex items-center justify-center gap-2 mt-2 disabled:opacity-60 disabled:cursor-not-allowed transition-colors"
            style={{
              boxShadow:
                '0 10px 28px -10px rgba(16,185,129,.7), inset 0 1px 0 rgba(255,255,255,.2)',
            }}
          >
            {loading ? '로그인 중...' : '로그인'}
            {!loading && (
              <svg
                width="14"
                height="14"
                viewBox="0 0 14 14"
                fill="none"
                stroke="currentColor"
                strokeWidth="1.8"
              >
                <path d="M3 7h8M7.5 3.5L11 7l-3.5 3.5" />
              </svg>
            )}
          </button>

          {/* Divider */}
          <div className="flex items-center gap-2.5 mt-4">
            <span className="flex-1 h-px bg-border-subtle" />
            <span className="text-text-disabled text-[10.5px] tracking-[.1em] uppercase whitespace-nowrap">
              또는 소셜 로그인
            </span>
            <span className="flex-1 h-px bg-border-subtle" />
          </div>

          {/* OAuth 버튼 — 진행 중에는 다른 provider 와 이메일 로그인 모두 비활성 */}
          <div className="flex flex-col gap-2 mt-3">
            <OAuthButton
              provider="google"
              onClick={() => handleOAuth('google')}
              disabled={loading || oauthLoading !== null}
              loading={oauthLoading === 'google'}
            />
            <OAuthButton
              provider="kakao"
              onClick={() => handleOAuth('kakao')}
              disabled={loading || oauthLoading !== null}
              loading={oauthLoading === 'kakao'}
            />
          </div>
        </form>
      </div>

      {/* Below card */}
      <div className="flex flex-col items-center gap-1">
        <div className="text-text-tertiary text-sm">
          계정이 없으신가요?{' '}
          <button
            type="button"
            className="text-accent-400 font-medium hover:underline bg-transparent border-0 p-0 cursor-pointer"
            onClick={() => {
              // TODO(impl): shell.openExternal('https://earning-whisperer.example/signup')
              // 보안: URL 화이트리스트 검증 (자체 도메인) + state 파라미터 + main 프로세스 IPC 경유
              console.log('[AuthPage] open signup URL (noop)')
            }}
          >
            웹사이트에서 가입하기 ↗
          </button>
        </div>
        <div className="font-mono text-text-disabled text-xs tracking-wider">
          v1.0.0 · build 2604.18
        </div>
      </div>
    </>
  )
}

/* -------------------------------------------------------------------------- */
/* KisVaultDualForm — 모의/실전 두 카드 폼.                                    */
/*                                                                              */
/* A3: 사용자는 양쪽 모두 또는 한쪽만 입력 가능. "기본 모드" 라디오 로 어느           */
/* 모드를 디폴트로 시작할지 명시. 한쪽만 입력했다면 자동으로 그쪽이 활성.           */
/*                                                                              */
/* 빈 카드(세 필드 모두 비어있음)는 등록 skip. 한쪽이라도 일부만 채우면 검증 에러.    */
/* -------------------------------------------------------------------------- */
export type ModeKey = 'paper' | 'real'

export interface VaultCardState {
  appKey: string
  appSecret: string
  accountNo: string
}

export const EMPTY_CARD: VaultCardState = { appKey: '', appSecret: '', accountNo: '' }

export function isCardEmpty(c: VaultCardState): boolean {
  return c.appKey === '' && c.appSecret === '' && c.accountNo === ''
}

export function isCardComplete(c: VaultCardState): boolean {
  return c.appKey.trim() !== '' && c.appSecret.trim() !== '' && c.accountNo.trim() !== ''
}

/**
 * 입력된 카드와 활성 모드 선택을 받아 VAULT_SAVE 호출 순서를 결정.
 * 활성 모드 먼저 저장하면 vaultHandlers 가 활성 모드 일치 시 issueToken 트리거 (저장 직후 자동 발급).
 * 비활성 모드는 후순위 — vaultHandlers 가 활성 모드 가드로 token 발급 skip.
 *
 * 반환:
 *   - 양쪽 모두 입력 → [activeMode, otherMode]
 *   - 한쪽만 입력 → [filledMode]
 *   - 양쪽 미입력 → []
 */
export function resolveSaveOrder(
  paperFilled: boolean,
  realFilled: boolean,
  activeMode: ModeKey,
): ModeKey[] {
  const order: ModeKey[] = []
  if (activeMode === 'paper') {
    if (paperFilled) order.push('paper')
    if (realFilled) order.push('real')
  } else {
    if (realFilled) order.push('real')
    if (paperFilled) order.push('paper')
  }
  return order
}

/**
 * 카드별 try/catch 결과(성공/실패 모드 + 메시지)를 조합해 사용자 인지용 에러 메시지 반환.
 * null = 양쪽 다 성공 (호출 측이 onSuccess 트리거).
 */
export function composePartialFailureMessage(
  successes: ModeKey[],
  failures: { mode: ModeKey; message: string }[],
): string | null {
  if (failures.length === 0) return null
  const label = (m: ModeKey): string => (m === 'paper' ? '모의' : '실전')
  if (successes.length > 0) {
    const failureLines = failures
      .map((f) => `${label(f.mode)} 키 저장 실패: ${f.message}`)
      .join('\n')
    const successLine = successes.map(label).join('/')
    return `${successLine} 키는 저장됐지만 ${failureLines}\n설정 페이지에서 추가 등록 가능합니다.`
  }
  // 양쪽 다 실패
  return failures.map((f) => `${label(f.mode)} 키 저장 실패: ${f.message}`).join('\n')
}

function KisVaultDualForm({ onSuccess }: { onSuccess: () => void }) {
  const [paperCard, setPaperCard] = useState<VaultCardState>(EMPTY_CARD)
  const [realCard, setRealCard] = useState<VaultCardState>(EMPTY_CARD)
  // 사용자가 명시적으로 선택한 활성 모드. null = 미선택 (한쪽만 입력 시 자동 결정).
  const [selectedActiveMode, setSelectedActiveMode] = useState<ModeKey | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)

  const paperFilled = !isCardEmpty(paperCard)
  const realFilled = !isCardEmpty(realCard)
  // 양쪽 모두 입력 시: 사용자 명시 선택 필수. 한쪽만 입력 시: 자동으로 그쪽이 활성.
  const resolvedActiveMode: ModeKey | null =
    paperFilled && realFilled
      ? selectedActiveMode
      : paperFilled
        ? 'paper'
        : realFilled
          ? 'real'
          : null

  // 최소 한쪽이라도 입력되어야 제출 가능 — disabled 가드.
  const canSubmit = paperFilled || realFilled

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setError(null)

    // 검증: 입력이 시작된 카드는 세 필드 모두 채워져야 함 (부분 입력 거부).
    if (paperFilled && !isCardComplete(paperCard)) {
      setError('모의투자 카드의 모든 필드를 입력해주세요. (App Key / App Secret / 계좌번호)')
      return
    }
    if (realFilled && !isCardComplete(realCard)) {
      setError('실전투자 카드의 모든 필드를 입력해주세요. (App Key / App Secret / 계좌번호)')
      return
    }
    if (!paperFilled && !realFilled) {
      setError('최소 한쪽 모드의 API 키를 입력해주세요.')
      return
    }
    // 양쪽 입력인데 활성 모드 미선택 — 사용자가 어느 쪽으로 시작할지 명시해야 함.
    if (paperFilled && realFilled && selectedActiveMode === null) {
      setError('어느 모드를 기본 모드로 사용할지 선택해주세요.')
      return
    }

    const finalActive = resolvedActiveMode
    if (finalActive === null) {
      // 위 가드들로 도달 불가능하지만 type narrowing 위해 명시.
      setError('활성 모드를 결정할 수 없습니다.')
      return
    }

    setLoading(true)
    try {
      // 1) 활성 모드 먼저 main 에 박아 두면, 후속 VAULT_SAVE 가 활성 모드 일치 시 토큰 발급.
      //    SETTINGS_SET_PAPER_TRADING 은 invalidateRuntime 을 트리거하므로 VAULT_SAVE 선행 필수.
      await ipc.invoke(IPC_CHANNELS.SETTINGS_SET_PAPER_TRADING, {
        value: finalActive === 'paper',
      })

      // 2) 카드별 try/catch 분리 — 부분 저장 실패 시 어느 카드 실패인지 사용자에게 명시.
      // 단일 에러 메시지로는 "첫 카드 성공 + 두 번째 실패" 시 어느 모드 키가 들어갔는지
      // 사용자가 알 수 없어 재등록 흐름이 막힌다 (review hotfix #2).
      const saveOrder = resolveSaveOrder(paperFilled, realFilled, finalActive)
      const failures: { mode: ModeKey; message: string }[] = []
      const successes: ModeKey[] = []
      for (const mode of saveOrder) {
        const card = mode === 'paper' ? paperCard : realCard
        try {
          await ipc.invoke(IPC_CHANNELS.VAULT_SAVE, {
            appKey: card.appKey.trim(),
            appSecret: card.appSecret.trim(),
            accountNo: card.accountNo.trim(),
            isPaperTrading: mode === 'paper',
          })
          successes.push(mode)
        } catch (err: any) {
          failures.push({
            mode,
            message: err?.message ?? '저장 실패',
          })
          // 첫 카드 실패는 toast 만 (사용자가 form 으로 재시도 가능). 마지막 실패는 인라인까지 노출.
          showIpcErrorToast(err)
        }
      }

      const partialMessage = composePartialFailureMessage(successes, failures)
      if (partialMessage === null) {
        onSuccess()
        return
      }
      setError(partialMessage)
    } catch (err: any) {
      setError(err?.message ?? 'API 키 저장에 실패했습니다.')
      showIpcErrorToast(err)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div
      className="w-[460px] max-w-full bg-surface-1 border border-border-subtle rounded-xl px-[26px] pt-5 pb-[22px]"
      style={{
        boxShadow:
          '0 20px 50px rgba(0,0,0,.45), 0 1px 0 rgba(255,255,255,.02) inset',
      }}
    >
      <form onSubmit={handleSubmit} className="flex flex-col gap-3.5">
        <div>
          <h2 className="text-text-primary text-base font-semibold tracking-tight">
            KIS API 키 등록
          </h2>
          <p className="text-text-tertiary text-xs mt-1">
            모의 / 실전 환경별로 키쌍을 등록합니다. 한쪽만 등록해도 진행할 수 있고, 나중에 설정에서 다른 모드를 추가할 수 있습니다.
          </p>
        </div>

        <VaultCard
          mode="paper"
          title="KIS 모의투자"
          accentTone="paper"
          card={paperCard}
          onChange={setPaperCard}
          activeRadio={resolvedActiveMode === 'paper'}
          onActivateRadio={() => setSelectedActiveMode('paper')}
          showRadio={paperFilled && realFilled}
          autoActivated={paperFilled && !realFilled}
        />

        <VaultCard
          mode="real"
          title="KIS 실전투자"
          accentTone="real"
          card={realCard}
          onChange={setRealCard}
          activeRadio={resolvedActiveMode === 'real'}
          onActivateRadio={() => setSelectedActiveMode('real')}
          showRadio={paperFilled && realFilled}
          autoActivated={realFilled && !paperFilled}
        />

        {error && <p className="text-sell text-sm">{error}</p>}

        <button
          type="submit"
          disabled={loading || !canSubmit}
          className="w-full h-[38px] rounded-lg bg-accent-500 hover:bg-accent-600 text-accent-foreground font-semibold text-base inline-flex items-center justify-center gap-2 mt-1 disabled:opacity-60 disabled:cursor-not-allowed transition-colors"
          style={{
            boxShadow:
              '0 10px 28px -10px rgba(16,185,129,.7), inset 0 1px 0 rgba(255,255,255,.2)',
          }}
        >
          {loading ? '저장 중...' : '저장하고 시작'}
        </button>
      </form>
    </div>
  )
}

/* -------------------------------------------------------------------------- */
/* VaultCard — 한 모드용 입력 카드. paper/real 색조만 분기.                     */
/* -------------------------------------------------------------------------- */
function VaultCard({
  mode,
  title,
  accentTone,
  card,
  onChange,
  activeRadio,
  onActivateRadio,
  showRadio,
  autoActivated,
}: {
  mode: ModeKey
  title: string
  accentTone: 'paper' | 'real'
  card: VaultCardState
  onChange: (next: VaultCardState) => void
  activeRadio: boolean
  onActivateRadio: () => void
  showRadio: boolean
  autoActivated: boolean
}) {
  const tone =
    accentTone === 'paper'
      ? { color: '#f59e0b', bg: 'rgba(245,158,11,0.06)', border: 'rgba(245,158,11,0.3)' }
      : { color: '#ef4444', bg: 'rgba(239,68,68,0.06)', border: 'rgba(239,68,68,0.3)' }

  return (
    <div
      className="rounded-md border bg-surface-2 px-3 pt-2.5 pb-3 flex flex-col gap-2"
      style={{ borderColor: tone.border, background: tone.bg }}
    >
      <div className="flex items-center gap-2">
        <span
          className="text-text-primary text-sm font-semibold tracking-tight"
          style={{ color: tone.color }}
        >
          {title}
        </span>
        {autoActivated && (
          <span
            className="ml-auto inline-flex items-center gap-1 px-1.5 py-0.5 rounded-sm text-[10px] font-semibold tracking-wider whitespace-nowrap"
            style={{
              background: 'rgba(16,185,129,0.10)',
              color: '#34d399',
              border: '1px solid rgba(16,185,129,0.25)',
            }}
          >
            기본 모드
          </span>
        )}
      </div>

      <AuthInputField
        label="App Key"
        value={card.appKey}
        onChange={(e) => onChange({ ...card, appKey: e.target.value })}
      />
      <AuthInputField
        label="App Secret"
        isPassword
        value={card.appSecret}
        onChange={(e) => onChange({ ...card, appSecret: e.target.value })}
      />
      <AuthInputField
        label="계좌번호 (예: 5012345601)"
        value={card.accountNo}
        onChange={(e) => onChange({ ...card, accountNo: e.target.value })}
      />

      {showRadio && (
        <label className="inline-flex items-center gap-2 cursor-pointer select-none mt-1">
          <input
            type="radio"
            name="vault-active-mode"
            checked={activeRadio}
            onChange={onActivateRadio}
            value={mode}
            className="peer sr-only"
          />
          <span
            className={`w-3.5 h-3.5 rounded-full grid place-items-center transition-colors ${
              activeRadio ? 'bg-accent-500' : 'bg-surface-3'
            } peer-focus-visible:ring-2 peer-focus-visible:ring-accent-500/40 peer-focus-visible:ring-offset-2 peer-focus-visible:ring-offset-surface-2`}
            style={{ boxShadow: 'inset 0 0 0 1px rgba(255,255,255,.15)' }}
            aria-hidden
          >
            {activeRadio && (
              <span className="w-1.5 h-1.5 rounded-full bg-accent-foreground" />
            )}
          </span>
          <span className="text-text-secondary text-xs whitespace-nowrap">
            기본 모드로 사용
          </span>
        </label>
      )}
      {showRadio && (
        <span className="text-text-disabled text-[10px] tracking-wide leading-snug">
          설정에서 언제든 변경 가능
        </span>
      )}
    </div>
  )
}
