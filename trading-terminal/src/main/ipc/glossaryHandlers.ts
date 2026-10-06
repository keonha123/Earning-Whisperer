import { BackendClient } from '../services/BackendClient'
import { IPC_CHANNELS } from '../../lib/ipcChannels'
import { isIpcError } from '../../lib/types/ipcError'
import { registerHandler } from './registerHandler'

/**
 * 어닝콜 용어 사전 IPC handler (Contract 7.9).
 *
 * - GLOSSARY_GET (invoke): 사전 전체 조회. renderer 가 세션당 한 번 부른다.
 *   사전이 없어도 자막 · 번역은 그대로 보여야 하므로 실패는 null 로 돌려준다.
 *   AUTH_EXPIRED 만 rethrow — 토큰 만료 신호를 다른 IPC 와 일관되게 사용자에게 노출.
 */
export function registerGlossaryHandlers() {
  registerHandler<undefined, unknown>(IPC_CHANNELS.GLOSSARY_GET, async () => {
    try {
      return await BackendClient.getGlossary()
    } catch (e) {
      if (isIpcError(e) && e.code === 'AUTH_EXPIRED') throw e
      console.error('[glossaryHandlers] 용어 사전 조회 실패:', e)
      return null
    }
  })
}
