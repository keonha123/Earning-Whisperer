import { IPC_CHANNELS } from '../../lib/ipcChannels'
import type { VaultSavePayload } from '../components/settings/KisKeyForm'

/**
 * 로그인 직후 이동과 키 등록 권유 화면의 저장 순서 (docs/design/screens/login.md).
 * AuthPage 가 쓰고, 화면 없이 테스트할 수 있게 순수 함수로 둔다.
 */

export type CredentialsPresence = { paper: boolean; real: boolean }

/**
 * 로그인 뒤 어디로 갈지 정한다.
 *   - 페이퍼 계정: KIS 키가 필요 없고 설정에도 KIS 판이 없어 저장한 키를 관리할 곳이 없으므로 늘 홈
 *   - 키 조회 실패(null): 권유 화면은 늘 신규 등록이라 이미 있는 키를 덮어쓸 수 있으므로 홈
 *   - 한쪽이라도 키 있음: 홈
 *   - 키 없음: 키 등록 권유
 */
export function decideAfterLogin(
  has: CredentialsPresence | null,
  accountType: string | null | undefined,
): 'home' | 'offer' {
  if (accountType === 'SELF_PAPER') return 'home'
  if (has === null || has.paper || has.real) return 'home'
  return 'offer'
}

type Invoke = <T = unknown>(channel: string, payload?: unknown) => Promise<T>

/**
 * 권유 화면에서 고른 계좌로 키를 저장한다.
 * 활성 모드를 먼저 정해 두면 VAULT_SAVE 가 같은 모드일 때 저장 직후 토큰을 발급한다.
 * SETTINGS_SET_PAPER_TRADING 은 런타임을 무효화하므로 VAULT_SAVE 보다 먼저 부른다.
 * VAULT_SAVE 가 실패하면 모드를 되돌린다 — 키 없는 실전 모드로 남은 채 `나중에` 로 들어가지 않게.
 * 되돌리기 실패는 삼키고 원래 저장 오류를 던진다.
 */
export async function saveOfferedKey(invoke: Invoke, payload: VaultSavePayload): Promise<void> {
  const prev = await invoke<boolean>(IPC_CHANNELS.SETTINGS_GET_PAPER_TRADING)
  await invoke(IPC_CHANNELS.SETTINGS_SET_PAPER_TRADING, { value: payload.isPaperTrading })
  try {
    await invoke(IPC_CHANNELS.VAULT_SAVE, payload)
  } catch (err) {
    if (typeof prev === 'boolean' && prev !== payload.isPaperTrading) {
      await invoke(IPC_CHANNELS.SETTINGS_SET_PAPER_TRADING, { value: prev }).catch(() => {})
    }
    throw err
  }
}
