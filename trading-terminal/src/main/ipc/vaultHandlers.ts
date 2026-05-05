import { KisService } from '../services/KisService'
import { mainState } from '../store/mainState'
import { IPC_CHANNELS } from '../../lib/ipcChannels'
import { IpcError } from '../../lib/types/ipcError'
import { registerHandler } from './registerHandler'

/**
 * 비어있지 않은 string 검증.
 * 공백만 있는 문자열 (`'   '`) 도 거부 — keytar 에 박히면 hasCredentials 가 등록됨으로
 * 오인하는 경로 차단 (truthy 한 빈 값이 자격증명 검증을 무력화하지 않도록).
 */
function assertNonBlankString(value: unknown, fieldName: string): asserts value is string {
  if (typeof value !== 'string' || value.trim().length === 0) {
    throw new IpcError('VALIDATION', `${fieldName} must be a non-empty string`)
  }
}

export function registerVaultHandlers() {
  registerHandler<
    { appKey: string; appSecret: string; accountNo: string; isPaperTrading: boolean },
    { success: true }
  >(
    IPC_CHANNELS.VAULT_SAVE,
    async (_e, payload) => {
      // 입력 strict 검증 — settingsHandlers 의 boolean 검증 패턴 재사용.
      // truthy 값으로 우회하거나 빈 문자열을 keytar 에 박아 "등록됨" 으로 오인되는 경로 차단.
      if (typeof payload?.isPaperTrading !== 'boolean') {
        throw new IpcError('VALIDATION', 'isPaperTrading must be boolean')
      }
      assertNonBlankString(payload?.appKey, 'appKey')
      assertNonBlankString(payload?.appSecret, 'appSecret')
      assertNonBlankString(payload?.accountNo, 'accountNo')

      const { appKey, appSecret, accountNo, isPaperTrading } = payload
      await KisService.saveCredentials(appKey, appSecret, accountNo, isPaperTrading)
      // 저장 대상 모드와 현재 활성 모드가 일치할 때만 토큰 발급 시도.
      // 다른 모드 키 등록(예: paper 활성 상태에서 real 키 등록)은 발급 skip — A3 의 양쪽 등록 UX 지원.
      if (isPaperTrading === mainState.isPaperTrading) {
        try {
          await KisService.issueToken()
        } catch (e) {
          console.warn(
            '[Vault] 자격증명 저장 후 KIS 토큰 발급 실패:',
            e instanceof Error ? e.message : 'unknown error',
          )
        }
      }
      return { success: true }
    },
  )

  registerHandler<void, { paper: boolean; real: boolean }>(
    IPC_CHANNELS.VAULT_HAS,
    async () => {
      return KisService.hasCredentials()
    },
  )

  registerHandler<{ isPaperTrading: boolean }, { success: true }>(
    IPC_CHANNELS.VAULT_DELETE,
    async (_e, payload) => {
      // 삭제 대상 모드 strict 검증 — 임의 truthy 로 활성 모드와 다른 slot 이 지워지는 사고 방지.
      if (typeof payload?.isPaperTrading !== 'boolean') {
        throw new IpcError('VALIDATION', 'isPaperTrading must be boolean')
      }
      await KisService.deleteCredentials(payload.isPaperTrading)
      return { success: true }
    },
  )
}
