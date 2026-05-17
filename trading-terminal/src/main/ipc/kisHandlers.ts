import { KisService } from '../services/KisService'
import { TradeExecutor } from '../services/TradeExecutor'
import { IPC_CHANNELS } from '../../lib/ipcChannels'
import { IpcError, sanitizeAxiosErrorDetails } from '../../lib/types/ipcError'
import { registerHandler } from './registerHandler'

/**
 * KIS 측 비즈니스 에러는 KIS_ERROR code 로 분류해 사용자가 인증/네트워크 에러와
 * 구분하여 인지할 수 있도록 한다 (잔고 부족 / 주문 거부 / 토큰 발급 실패 등).
 * 이미 IpcError 인 경우 (BackendClient interceptor 통과분) 는 그대로 propagate.
 *
 * **중요 (보안)**: raw axios error 를 details 로 박지 말 것 —
 * `config.headers` 에 KIS appkey/appsecret/Bearer token 이 평문 보존되며 toJSON 으로
 * 자동 직렬화된다. sanitizeAxiosErrorDetails 로 status/data/code 만 추출해 사용.
 */
function toKisError(e: unknown, fallbackMessage: string): IpcError {
  if (e instanceof IpcError) return e
  const message = e instanceof Error ? e.message : fallbackMessage
  return new IpcError('KIS_ERROR', message, sanitizeAxiosErrorDetails(e))
}

export function registerKisHandlers() {
  registerHandler(IPC_CHANNELS.KIS_ISSUE_TOKEN, async () => {
    try {
      await KisService.issueToken()
      return KisService.getTokenStatus()
    } catch (e) {
      throw toKisError(e, 'KIS 토큰 발급 실패')
    }
  })

  registerHandler(IPC_CHANNELS.KIS_GET_TOKEN_STATUS, () => {
    return KisService.getTokenStatus()
  })

  registerHandler(IPC_CHANNELS.KIS_GET_BALANCE, async () => {
    try {
      return await KisService.getBalance()
    } catch (e) {
      throw toKisError(e, '잔고 조회 실패')
    }
  })

  registerHandler(IPC_CHANNELS.KIS_PLACE_ORDER, async (_e, signal) => {
    try {
      return await TradeExecutor.execute(signal)
    } catch (e) {
      throw toKisError(e, '주문 실패')
    }
  })
}
