import { BrowserWindow } from 'electron'
import { mainState } from '../store/mainState'
import { KisService } from './KisService'
import { BackendClient } from './BackendClient'
import { NotificationService } from './NotificationService'
import { IPC_CHANNELS } from '../../lib/ipcChannels'

export interface TradeSignal {
  trade_id: string
  action: 'BUY' | 'SELL'
  target_qty: number
  ticker: string
  ema_score: number
}

export interface TradeResult {
  tradeId: string
  status: 'EXECUTED' | 'FAILED'
  orderId: string | null
  executedPrice: number | null
  executedQty: number
  errorMessage: string | null
}

function pushToRenderer(channel: string, payload: unknown) {
  BrowserWindow.getAllWindows().forEach((win) => {
    if (!win.isDestroyed()) win.webContents.send(channel, payload)
  })
}

export const TradeExecutor = {
  async execute(signal: TradeSignal): Promise<TradeResult> {
    if (mainState.isOrderInProgress) {
      return failResult(signal.trade_id, '이미 주문이 진행 중입니다.')
    }

    mainState.setOrderInProgress(true)

    try {
      // Step 1: 잔고 조회 + 수량 보정
      const balance = await KisService.getBalance()
      const finalQty = adjustQty(signal, balance)

      if (finalQty <= 0) {
        const reason = signal.action === 'BUY' ? '예수금 부족' : '보유 수량 없음'
        return await sendFailCallback(signal.trade_id, reason)
      }

      // Step 2: KIS 주문
      const orderResult = await KisService.placeOrder(signal.action, signal.ticker, finalQty)

      // Step 3: 백엔드 콜백
      const result: TradeResult = {
        tradeId: signal.trade_id,
        status: 'EXECUTED',
        orderId: orderResult.orderId,
        executedPrice: orderResult.executedPrice,
        executedQty: orderResult.executedQty,
        errorMessage: null,
      }

      await BackendClient.sendCallback(signal.trade_id, {
        status: 'EXECUTED',
        broker_order_id: orderResult.orderId,
        executed_price: orderResult.executedPrice,
        executed_qty: orderResult.executedQty,
        error_message: null,
      })

      // Step 4: 포트폴리오 동기화 (비동기)
      syncPortfolioAsync()

      NotificationService.notifyTradeExecuted(signal.ticker, signal.action, orderResult.executedQty, orderResult.executedPrice)
      pushToRenderer(IPC_CHANNELS.TRADE_EXECUTED, result)
      return result
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : '알 수 없는 오류'
      return await sendFailCallback(signal.trade_id, msg)
    } finally {
      mainState.setOrderInProgress(false)
    }
  },
}

function adjustQty(signal: TradeSignal, balance: { orderableCash: number; holdings: { ticker: string; qty: number }[] }): number {
  if (signal.action === 'BUY') {
    // 예수금 기반 단순 검증 (실제 수량 보정은 백엔드 target_qty 기준)
    if (balance.orderableCash <= 0) return 0
    return signal.target_qty
  } else {
    const holding = balance.holdings.find((h) => h.ticker === signal.ticker)
    const available = holding?.qty ?? 0
    return Math.min(signal.target_qty, available)
  }
}

async function sendFailCallback(tradeId: string, reason: string): Promise<TradeResult> {
  const result: TradeResult = {
    tradeId,
    status: 'FAILED',
    orderId: null,
    executedPrice: null,
    executedQty: 0,
    errorMessage: reason,
  }

  try {
    await BackendClient.sendCallback(tradeId, {
      status: 'FAILED',
      broker_order_id: null,
      executed_price: null,
      executed_qty: 0,
      error_message: reason,
    })
  } catch (e) {
    console.error('[TradeExecutor] 콜백 전송 실패:', e)
  }

  NotificationService.notifyTradeFailed(tradeId, reason)
  BrowserWindow.getAllWindows().forEach((win) => {
    if (!win.isDestroyed()) win.webContents.send(IPC_CHANNELS.TRADE_FAILED, result)
  })

  return result
}

function syncPortfolioAsync() {
  KisService.getBalance()
    .then((balance) =>
      BackendClient.syncPortfolio({
        total_cash: balance.totalCash,
        holdings: balance.holdings.map((h) => ({
          ticker: h.ticker,
          qty: h.qty,
          avg_price: h.avgPrice,
        })),
      }),
    )
    .catch((e) => console.error('[TradeExecutor] 포트폴리오 동기화 실패:', e))
}

function failResult(tradeId: string, reason: string): TradeResult {
  return {
    tradeId,
    status: 'FAILED',
    orderId: null,
    executedPrice: null,
    executedQty: 0,
    errorMessage: reason,
  }
}
