import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { ipc, IPC_CHANNELS } from '../lib/ipc'
import { useConnectionStore } from '../store/useConnectionStore'
import { useUserStore } from '../store/useUserStore'

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
    <div className="h-screen bg-bg-base flex flex-col items-center justify-center">
      <div className="mb-8 text-center">
        <h1 className="text-2xl font-bold text-text-primary">EarningWhisperer</h1>
        <p className="text-text-secondary text-sm mt-1">Trading Terminal</p>
      </div>

      {step === 'login' ? (
        <LoginForm onSuccess={handleLoginSuccess} />
      ) : (
        <KisVaultForm onSuccess={handleVaultSaved} />
      )}
    </div>
  )
}

function LoginForm({ onSuccess }: { onSuccess: (user: any, settings: any) => void }) {
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setError(null)
    setLoading(true)
    try {
      const result = await ipc.invoke<{ user: any; settings: any }>(IPC_CHANNELS.AUTH_LOGIN, { email, password })
      onSuccess(result.user, result.settings)
    } catch (err: any) {
      setError(err?.message ?? '로그인에 실패했습니다.')
    } finally {
      setLoading(false)
    }
  }

  return (
    <form onSubmit={handleSubmit} className="card w-96 flex flex-col gap-4">
      <h2 className="text-md font-semibold text-text-primary">로그인</h2>

      <div className="flex flex-col gap-1.5">
        <label className="text-sm text-text-secondary">이메일</label>
        <input className="input-base" type="email" value={email} onChange={(e) => setEmail(e.target.value)} required />
      </div>

      <div className="flex flex-col gap-1.5">
        <label className="text-sm text-text-secondary">비밀번호</label>
        <input className="input-base" type="password" value={password} onChange={(e) => setPassword(e.target.value)} required />
      </div>

      {error && <p className="text-sell text-sm">{error}</p>}

      <button type="submit" className="btn-primary w-full" disabled={loading}>
        {loading ? '로그인 중...' : '로그인'}
      </button>
    </form>
  )
}

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
    <form onSubmit={handleSubmit} className="card w-96 flex flex-col gap-4">
      <div>
        <h2 className="text-md font-semibold text-text-primary">KIS API 키 등록</h2>
        <p className="text-text-secondary text-xs mt-1">
          키는 이 PC의 OS 자격 증명 관리자에만 암호화 저장됩니다. 서버로 전송되지 않습니다.
        </p>
      </div>

      <div className="p-3 bg-sell/10 border border-sell/30 rounded-md text-sell text-xs">
        ⚠ 모의투자 API 키를 사용하고 있습니다. 실전 투자 키는 사용하지 마세요.
      </div>

      <div className="flex flex-col gap-1.5">
        <label className="text-sm text-text-secondary">App Key</label>
        <input className="input-base" value={appKey} onChange={(e) => setAppKey(e.target.value)} required />
      </div>

      <div className="flex flex-col gap-1.5">
        <label className="text-sm text-text-secondary">App Secret</label>
        <input className="input-base" type="password" value={appSecret} onChange={(e) => setAppSecret(e.target.value)} required />
      </div>

      <div className="flex flex-col gap-1.5">
        <label className="text-sm text-text-secondary">계좌번호 (예: 5012345601)</label>
        <input className="input-base" value={accountNo} onChange={(e) => setAccountNo(e.target.value)} required />
      </div>

      {error && <p className="text-sell text-sm">{error}</p>}

      <button type="submit" className="btn-primary w-full" disabled={loading}>
        {loading ? '저장 중...' : '저장 및 시작'}
      </button>
    </form>
  )
}
