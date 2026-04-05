import { useState } from 'react'
import { ipc, IPC_CHANNELS } from '../lib/ipc'
import { useUserStore } from '../store/useUserStore'
import { useConnectionStore } from '../store/useConnectionStore'

export default function SettingsPage() {
  const { settings, setSettings } = useUserStore()
  const { kisTokenStatus, hasCredentials, setHasCredentials, setKisTokenStatus } = useConnectionStore()

  const [form, setForm] = useState({ ...settings })
  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState(false)
  const [saveError, setSaveError] = useState<string | null>(null)

  async function handleSave(e: React.FormEvent) {
    e.preventDefault()
    setSaving(true)
    setSaveError(null)
    try {
      await ipc.invoke(IPC_CHANNELS.SETTINGS_UPDATE, {
        tradingMode: form.tradingMode,
        maxBuyRatio: form.maxBuyRatio,
        maxHoldingRatio: form.maxHoldingRatio,
        cooldownMinutes: form.cooldownMinutes,
      })
      setSettings(form)
      setSaved(true)
      setTimeout(() => setSaved(false), 2000)
    } catch (e: any) {
      setSaveError(e?.message ?? '저장에 실패했습니다.')
    } finally {
      setSaving(false)
    }
  }

  async function handleDeleteCredentials() {
    if (!confirm('KIS API 키를 삭제하시겠습니까?')) return
    await ipc.invoke(IPC_CHANNELS.VAULT_DELETE)
    setHasCredentials(false)
  }

  async function handleIssueToken() {
    try {
      await ipc.invoke(IPC_CHANNELS.KIS_ISSUE_TOKEN)
      setKisTokenStatus('VALID')
    } catch (e: any) {
      alert('토큰 발급 실패: ' + e?.message)
    }
  }

  return (
    <div className="flex flex-col gap-4 max-w-2xl">
      {/* 섹션: 리스크 파라미터 */}
      <section className="card p-0 overflow-hidden">
        <div className="px-5 py-4 border-b border-[#1e2738] flex items-center gap-3">
          <div className="w-7 h-7 rounded-md bg-brand/10 border border-brand/20
                          flex items-center justify-center shrink-0">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none"
                 stroke="#3b82f6" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
              <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" />
            </svg>
          </div>
          <div>
            <p className="text-sm font-semibold text-text-primary">리스크 파라미터</p>
            <p className="text-[10px] text-text-disabled mt-0.5">자동 매매 시 적용되는 위험 관리 규칙</p>
          </div>
        </div>

        <form onSubmit={handleSave} className="px-5 py-5 flex flex-col gap-5">
          <RatioField
            label="1회 매수 비율"
            description="신호 1건당 현금의 최대 사용 비율"
            value={form.maxBuyRatio}
            onChange={(v) => setForm({ ...form, maxBuyRatio: v })}
            min={0} max={1} step={0.01}
            color="#3b82f6"
          />
          <RatioField
            label="최대 보유 비중"
            description="단일 종목의 포트폴리오 최대 비중"
            value={form.maxHoldingRatio}
            onChange={(v) => setForm({ ...form, maxHoldingRatio: v })}
            min={0} max={1} step={0.01}
            color="#22c55e"
          />

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

          {saveError && (
            <p className="text-sell text-xs">{saveError}</p>
          )}

          <div className="pt-1">
            <button
              type="submit"
              className={`btn-primary w-full transition-all duration-200
                          ${saved ? 'bg-buy hover:bg-buy' : ''}`}
              disabled={saving}
            >
              {saved ? (
                <span className="flex items-center justify-center gap-2">
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none"
                       stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
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
                 stroke="#94a3b8" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
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
}

function RatioField({ label, description, value, onChange, min, max, step, color }: {
  label: string
  description: string
  value: number
  onChange: (v: number) => void
  min: number
  max: number
  step: number
  color: string
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
      <div className="w-full h-1 bg-[#1e2738] rounded-full overflow-hidden">
        <div
          className="h-full rounded-full transition-all duration-300"
          style={{ width: `${Math.min(value * 100, 100)}%`, backgroundColor: color }}
        />
      </div>
    </div>
  )
}

function KisStep({ done, label, sublabel }: {
  done: boolean
  label: string
  sublabel: string
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
               stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
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
