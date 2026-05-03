import { StompService } from '../services/StompService'
import { BackendClient } from '../services/BackendClient'
import { IPC_CHANNELS } from '../../lib/ipcChannels'
import { registerHandler } from './registerHandler'

export function registerWsHandlers() {
  registerHandler(IPC_CHANNELS.WS_CONNECT, () => {
    StompService.connect()
  })

  registerHandler(IPC_CHANNELS.WS_DISCONNECT, () => {
    StompService.disconnect()
  })

  registerHandler<{ page: number; size: number }, unknown>(
    IPC_CHANNELS.TRADES_GET,
    async (_e, { page, size }) => {
      return BackendClient.getTrades(page, size)
    },
  )

  registerHandler<{ tradeId: string; reason: string }, void>(
    IPC_CHANNELS.TRADE_CANCEL,
    async (_e, { tradeId, reason }) => {
      await BackendClient.sendCallback(tradeId, {
        status: 'FAILED',
        broker_order_id: null,
        executed_price: null,
        executed_qty: 0,
        error_message: reason,
      })
    },
  )

  /*
   * 트랜스크립트 동적 구독 (Contract 4.5).
   * Renderer 가 사용자의 어닝콜 ticker 변경에 따라 SUBSCRIBE/UNSUBSCRIBE 를 명령한다.
   * fire-and-forget 패턴 — 결과를 invoke 응답으로 돌려줄 필요 없음.
   *
   * payload 가 falsy 하거나 ticker 가 비문자열인 경우는 silent ignore (방어).
   */
  registerHandler<{ ticker: string }, void>(IPC_CHANNELS.TRANSCRIPT_SUBSCRIBE, (_e, payload) => {
    if (!payload || typeof payload.ticker !== 'string') return
    StompService.subscribeTranscript(payload.ticker)
  })

  registerHandler<{ ticker: string }, void>(IPC_CHANNELS.TRANSCRIPT_UNSUBSCRIBE, (_e, payload) => {
    if (!payload || typeof payload.ticker !== 'string') return
    StompService.unsubscribeTranscript(payload.ticker)
  })
}
