import { useState } from 'react'
import AuthInputField from '../auth/AuthInputField'
import { showIpcErrorToast } from '../common/Toast'
import { isIpcError } from '../../../lib/types/ipcError'

/**
 * KisKeyForm — KIS 키 한 벌(App Key · App Secret · 계좌번호 · HTS ID) 입력 폼.
 *
 * 첫 로그인 직후의 키 등록 권유(AuthPage)와 설정의 등록 · 수정이 같이 쓴다.
 * 폼은 입력 · 검증 · 비밀값 정리만 맡고, 저장 IPC 는 호출하는 쪽이 onSubmit 에서 한다
 * (권유 화면은 모드 설정 → VAULT_SAVE, 설정은 VAULT_SAVE 만 부른다).
 */

export type KisMode = 'paper' | 'real'

export const KIS_MODE_LABEL: Record<KisMode, string> = {
  paper: 'KIS 모의투자',
  real: 'KIS 실전투자',
}

export interface KisKeyValues {
  appKey: string
  appSecret: string
  accountNo: string
  htsId: string
}

export interface MaskedKisKey {
  appKeyMasked: string
  accountNoMasked: string
  htsId: string | null
}

export interface VaultSavePayload {
  appKey: string
  appSecret: string
  accountNo: string
  isPaperTrading: boolean
  htsId: string
}

/**
 * 제출 전 검증. 신규 등록이면 HTS ID 를 뺀 세 칸이 모두 필요하다.
 * 수정이면 빈 칸은 "기존 값 유지" 라 검증하지 않는다(VAULT_SAVE 가 기존 값으로 채운다).
 */
export function validateKisKeyInput(values: KisKeyValues, isNew: boolean): string | null {
  if (!isNew) return null
  if (values.appKey.trim() === '' || values.appSecret.trim() === '' || values.accountNo.trim() === '') {
    return 'App Key, App Secret, 계좌번호를 모두 입력해 주세요.'
  }
  return null
}

/**
 * VAULT_SAVE 인자. HTS ID 는 수정 폼에 기존 값이 미리 채워지므로, 빈 칸은 사용자가 지운 것이다.
 * 그대로 빈 문자열로 보내야 삭제가 반영된다.
 */
export function toVaultSavePayload(values: KisKeyValues, mode: KisMode): VaultSavePayload {
  return {
    appKey: values.appKey.trim(),
    appSecret: values.appSecret.trim(),
    accountNo: values.accountNo.trim(),
    isPaperTrading: mode === 'paper',
    htsId: values.htsId.trim(),
  }
}

interface KisKeyFormProps {
  mode: KisMode
  /** 이미 등록된 키. 있으면 수정 흐름이다 — 바꿀 칸만 입력한다. appSecret 은 되돌려 받지 않는다. */
  existing?: MaskedKisKey | null
  submitLabel: string
  /** 왼쪽 보조 버튼 (나중에 · 취소). */
  secondaryLabel?: string
  onSecondary?: () => void
  /** 저장. 실패하면 throw — 폼이 문구를 보여 준다. */
  onSubmit: (payload: VaultSavePayload) => Promise<void>
  /** 설정 안처럼 좁은 자리에서 작은 버튼을 쓴다. */
  compact?: boolean
  autoFocus?: boolean
  /** 저장 직전 확인(실전 계좌 등). false 면 저장하지 않고 폼에 머문다. */
  confirmSubmit?: () => Promise<boolean>
  /** 저장 중 여부를 바깥에 알린다 — 저장 중에 계좌 전환을 막는 데 쓴다. */
  onSavingChange?: (saving: boolean) => void
}

const EMPTY: KisKeyValues = { appKey: '', appSecret: '', accountNo: '', htsId: '' }

export default function KisKeyForm({
  mode,
  existing = null,
  submitLabel,
  secondaryLabel,
  onSecondary,
  onSubmit,
  compact = false,
  autoFocus = false,
  confirmSubmit,
  onSavingChange,
}: KisKeyFormProps) {
  // HTS ID 는 비밀값이 아니라 로그인 아이디라 기존 값을 그대로 채운다.
  const [values, setValues] = useState<KisKeyValues>({ ...EMPTY, htsId: existing?.htsId ?? '' })
  const [error, setError] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)
  // 저장 전 확인 창이 떠 있는 동안 — 다시 제출되지 않게 막는다
  const [confirming, setConfirming] = useState(false)

  const set = (key: keyof KisKeyValues) => (e: React.ChangeEvent<HTMLInputElement>) =>
    setValues((v) => ({ ...v, [key]: e.target.value }))

  // 취소 · 저장 뒤에는 입력값을 비운다 — 비밀값이 state 에 남아 있는 시간을 줄인다.
  // 언마운트되면 state 는 함께 사라진다.
  function handleSecondary() {
    setValues(EMPTY)
    onSecondary?.()
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    if (saving || confirming) return
    setError(null)
    const invalid = validateKisKeyInput(values, existing === null)
    if (invalid) {
      setError(invalid)
      return
    }
    if (confirmSubmit) {
      setConfirming(true)
      const ok = await confirmSubmit().finally(() => setConfirming(false))
      if (!ok) return
    }
    setSaving(true)
    onSavingChange?.(true)
    try {
      await onSubmit(toVaultSavePayload(values, mode))
      setValues(EMPTY)
    } catch (err: unknown) {
      // 입력 검증 실패만 사유를 그대로 보여 준다. 그 밖의 오류 문구는 고정하고 알림에 맡긴다.
      if (isIpcError(err) && err.code === 'VALIDATION') {
        setError(err.message)
      } else {
        setError('키를 저장하지 못했습니다. 잠시 후 다시 시도해 주세요.')
        showIpcErrorToast(err)
      }
    } finally {
      setSaving(false)
      onSavingChange?.(false)
    }
  }

  const btnSize = compact ? ' gbtn-sm' : ''

  return (
    <form onSubmit={handleSubmit} className="flex flex-col gap-3">
      {existing && (
        <p className="text-ink-3 text-[12.5px] leading-snug">
          바꿀 칸만 입력합니다. 비워 둔 칸은 지금 값을 그대로 씁니다.
        </p>
      )}
      <AuthInputField
        label="App Key"
        value={values.appKey}
        placeholder={existing?.appKeyMasked}
        onChange={set('appKey')}
        autoFocus={autoFocus}
      />
      <AuthInputField
        label="App Secret"
        isPassword
        // 저장된 비밀번호 자동완성이 끼어들지 않게 한다
        autoComplete="new-password"
        value={values.appSecret}
        placeholder={existing ? '바꿀 때만 입력' : undefined}
        onChange={set('appSecret')}
      />
      <AuthInputField
        label="계좌번호"
        inputMode="numeric"
        value={values.accountNo}
        placeholder={existing?.accountNoMasked ?? '숫자 8자리 또는 10자리'}
        onChange={set('accountNo')}
        className="tabular-nums"
      />
      <AuthInputField
        label="HTS ID (선택)"
        value={values.htsId}
        placeholder="한국투자증권 로그인 아이디"
        onChange={set('htsId')}
      />
      <p className="text-ink-3 text-[12px] leading-snug -mt-1">
        HTS ID 를 넣으면 체결을 실시간으로 알려 드립니다. 비워 두면 거래 내역을 열거나 새로 고칠 때 확인합니다.
      </p>

      <p className="min-h-[18px] text-danger text-[12.5px] leading-snug whitespace-pre-line" role="alert">
        {error}
      </p>

      <div className={`flex items-center gap-2 ${secondaryLabel ? 'justify-between' : 'justify-end'}`}>
        {secondaryLabel && (
          <button type="button" onClick={handleSecondary} disabled={saving} className={`gbtn${btnSize}`}>
            {secondaryLabel}
          </button>
        )}
        <button type="submit" disabled={saving || confirming} className={`gbtn gbtn-olive${btnSize}`}>
          {saving ? '저장 중' : submitLabel}
        </button>
      </div>
    </form>
  )
}
