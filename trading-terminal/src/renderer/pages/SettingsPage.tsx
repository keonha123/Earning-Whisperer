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

  async function handleSave(e: React.FormEvent) {
    e.preventDefault()
    setSaving(true)
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
    <div className="flex flex-col gap-6 max-w-3xl">
      <h2 className="text-md font-semibold text-text-primary">설정</h2>

      <div className="grid grid-cols-2 gap-6">
        {/* 리스크 파라미터 */}
        <form onSubmit={handleSave} className="card flex flex-col gap-4">
          <h3 className="text-sm font-semibold text-text-primary">리스크 파라미터</h3>

          <Field label="1회 매수 비율 (0~1)">
            <input
              className="input-base"
              type="number" min={0} max={1} step={0.01}
              value={form.maxBuyRatio}
              onChange={(e) => setForm({ ...form, maxBuyRatio: Number(e.target.value) })}
            />
          </Field>

          <Field label="최대 보유 비중 (0~1)">
            <input
              className="input-base"
              type="number" min={0} max={1} step={0.01}
              value={form.maxHoldingRatio}
              onChange={(e) => setForm({ ...form, maxHoldingRatio: Number(e.target.value) })}
            />
          </Field>

          <Field label="쿨다운 (분)">
            <input
              className="input-base"
              type="number" min={0} max={60}
              value={form.cooldownMinutes}
              onChange={(e) => setForm({ ...form, cooldownMinutes: Number(e.target.value) })}
            />
          </Field>

          <button type="submit" className="btn-primary" disabled={saving}>
            {saved ? '✓ 저장됨' : saving ? '저장 중...' : '저장'}
          </button>
        </form>

        {/* KIS 연동 상태 */}
        <div className="card flex flex-col gap-4">
          <h3 className="text-sm font-semibold text-text-primary">KIS 연동</h3>

          <div className="flex items-center justify-between">
            <span className="text-text-secondary text-sm">API 키</span>
            <span className={hasCredentials ? 'badge-success' : 'badge-danger'}>
              {hasCredentials ? '등록됨' : '미등록'}
            </span>
          </div>

          <div className="flex items-center justify-between">
            <span className="text-text-secondary text-sm">토큰 상태</span>
            <span className={kisTokenStatus === 'VALID' ? 'badge-success' : 'badge-danger'}>
              {kisTokenStatus}
            </span>
          </div>

          <div className="flex flex-col gap-2 mt-2">
            <button className="btn-ghost text-sm" onClick={handleIssueToken}>
              토큰 재발급
            </button>
            <button className="btn-danger-ghost text-sm" onClick={handleDeleteCredentials} disabled={!hasCredentials}>
              API 키 삭제
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex flex-col gap-1.5">
      <label className="text-sm text-text-secondary">{label}</label>
      {children}
    </div>
  )
}
