import fs from 'fs'
import path from 'path'
import { app, dialog } from 'electron'
import { StompService } from '../services/StompService'
import { BackendClient } from '../services/BackendClient'
import { mainState } from '../store/mainState'
import { SubscriptionManager } from '../services/SubscriptionManager'
import { IPC_CHANNELS } from '../../lib/ipcChannels'
import { registerHandler } from './registerHandler'

export function registerWsHandlers() {
  registerHandler(IPC_CHANNELS.WS_CONNECT, () => {
    StompService.connect()
  })

  registerHandler(IPC_CHANNELS.WS_DISCONNECT, () => {
    StompService.disconnect()
  })

  registerHandler<{ page: number; size: number; startDate?: string }, unknown>(
    IPC_CHANNELS.TRADES_GET,
    async (_e, { page, size, startDate }) => {
      return BackendClient.getTrades(page, size, startDate)
    },
  )

  registerHandler<
    { filename: string; csvContent: string },
    { saved: boolean; filePath?: string }
  >(
    IPC_CHANNELS.SHELL_SAVE_CSV,
    async (_e, { filename, csvContent }) => {
      // 파일명 sanitize — 경로 구분자 및 특수문자 제거
      const safeName = filename.replace(/[^A-Za-z0-9_\-]/g, '_').slice(0, 80) + '.csv'
      const downloadsDir = app.getPath('downloads')
      const { canceled, filePath } = await dialog.showSaveDialog({
        defaultPath: path.join(downloadsDir, safeName),
        filters: [{ name: 'CSV', extensions: ['csv'] }],
      })
      if (canceled || !filePath) return { saved: false }
      // UTF-8 BOM — Excel 한글 호환
      const BOM = '﻿'
      await fs.promises.writeFile(filePath, BOM + csvContent, 'utf-8')
      return { saved: true, filePath }
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
  registerHandler<{ ticker: string }, void>(
    IPC_CHANNELS.TRADE_SESSION_START,
    (_e, payload) => {
      if (!payload || typeof payload.ticker !== 'string' || !payload.ticker) return
      mainState.setTradeSession(true, payload.ticker)
      SubscriptionManager.setActiveSession(payload.ticker)
    },
  )

  registerHandler<undefined, void>(
    IPC_CHANNELS.TRADE_SESSION_END,
    () => {
      mainState.setTradeSession(false)
      SubscriptionManager.setActiveSession(null)
    },
  )

  registerHandler<{ ticker: string }, void>(IPC_CHANNELS.TRANSCRIPT_SUBSCRIBE, (_e, payload) => {
    if (!payload || typeof payload.ticker !== 'string') return
    StompService.subscribeTranscript(payload.ticker)
  })

  registerHandler<{ ticker: string }, void>(IPC_CHANNELS.TRANSCRIPT_UNSUBSCRIBE, (_e, payload) => {
    if (!payload || typeof payload.ticker !== 'string') return
    StompService.unsubscribeTranscript(payload.ticker)
  })
}
