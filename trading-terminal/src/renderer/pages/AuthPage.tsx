import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { ipc, IPC_CHANNELS } from '../lib/ipc'
import { useConnectionStore } from '../store/useConnectionStore'
import { useUserStore } from '../store/useUserStore'
import AuthBrandSection from '../components/auth/AuthBrandSection'
import AuthInputField from '../components/auth/AuthInputField'
import OAuthButton from '../components/auth/OAuthButton'

type Step = 'login' | 'vault'

export default function AuthPage() {
  const [step, setStep] = useState<Step>('login')
  const navigate = useNavigate()
  const { setAuthenticated, setHasCredentials } = useConnectionStore()
  const { setUser, setSettings } = useUserStore()

  async function handleLoginSuccess(user: any, settings: any) {
    setUser(user)
    if (settings) {
      setSettings({
        tradingMode: settings.tradingMode,
        maxBuyRatio: settings.buyAmountRatio,
        maxHoldingRatio: settings.maxPositionRatio,
        cooldownMinutes: settings.cooldownMinutes,
      })
    }
    setAuthenticated(true)
    const hasCredentials = await ipc.invoke<boolean>(IPC_CHANNELS.VAULT_HAS)
    if (hasCredentials) {
      setHasCredentials(true)
      navigate('/dashboard')
    } else {
      setStep('vault')
    }
  }

  async function handleVaultSaved() {
    setHasCredentials(true)
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
          <KisVaultForm onSuccess={handleVaultSaved} />
        )}
      </div>

    </div>
  )
}

/* -------------------------------------------------------------------------- */
/* LoginForm — 디자인 캔버스 기준 마크업 + 기존 IPC 호출 보존                 */
/* -------------------------------------------------------------------------- */
function LoginForm({ onSuccess }: { onSuccess: (user: any, settings: any) => void }) {
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
      const result = await ipc.invoke<{ user: any; settings: any }>(
        IPC_CHANNELS.AUTH_LOGIN,
        { email, password },
      )
      onSuccess(result.user, result.settings)
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
      const result = await ipc.invoke<{ user: any; settings: any }>(
        IPC_CHANNELS.AUTH_OAUTH_START,
        { provider },
      )
      onSuccess(result.user, result.settings)
    } catch (err: any) {
      // user enumeration 방지: 백엔드 메시지를 그대로 노출하지 않고 generic 메시지로 통일
      setError('소셜 로그인에 실패했습니다. 다시 시도해 주세요.')
      console.debug('[auth] oauth failed:', err)
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
/* KisVaultForm — 2-step 흐름 보존. 기존 비즈니스 로직 그대로,                 */
/* 카드 컨테이너만 새 디자인 토큰으로 정리.                                   */
/* -------------------------------------------------------------------------- */
function KisVaultForm({ onSuccess }: { onSuccess: () => void }) {
  const [appKey, setAppKey] = useState('')
  const [appSecret, setAppSecret] = useState('')
  const [accountNo, setAccountNo] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setError(null)
    setLoading(true)
    try {
      await ipc.invoke(IPC_CHANNELS.VAULT_SAVE, { appKey, appSecret, accountNo })
      onSuccess()
    } catch (err: any) {
      setError(err?.message ?? 'API 키 저장에 실패했습니다.')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div
      className="w-[420px] max-w-full bg-surface-1 border border-border-subtle rounded-xl px-[26px] pt-5 pb-[22px]"
      style={{
        boxShadow:
          '0 20px 50px rgba(0,0,0,.45), 0 1px 0 rgba(255,255,255,.02) inset',
      }}
    >
      <form onSubmit={handleSubmit} className="flex flex-col gap-3">
        <div>
          <h2 className="text-text-primary text-base font-semibold tracking-tight">
            KIS API 키 등록
          </h2>
        </div>

        <div className="p-3 bg-sell/10 border border-sell/30 rounded-md text-sell text-sm">
          ⚠ 모의투자 API 키를 사용하고 있습니다. 실전 투자 키는 사용하지 마세요.
        </div>

        <AuthInputField
          label="App Key"
          value={appKey}
          onChange={(e) => setAppKey(e.target.value)}
          required
        />
        <AuthInputField
          label="App Secret"
          isPassword
          value={appSecret}
          onChange={(e) => setAppSecret(e.target.value)}
          required
        />
        <AuthInputField
          label="계좌번호 (예: 5012345601)"
          value={accountNo}
          onChange={(e) => setAccountNo(e.target.value)}
          required
        />

        {error && <p className="text-sell text-sm">{error}</p>}

        <button
          type="submit"
          disabled={loading}
          className="w-full h-[38px] rounded-lg bg-accent-500 hover:bg-accent-600 text-accent-foreground font-semibold text-base inline-flex items-center justify-center gap-2 mt-1 disabled:opacity-60 disabled:cursor-not-allowed transition-colors"
          style={{
            boxShadow:
              '0 10px 28px -10px rgba(16,185,129,.7), inset 0 1px 0 rgba(255,255,255,.2)',
          }}
        >
          {loading ? '저장 중...' : '저장 및 시작'}
        </button>
      </form>
    </div>
  )
}
