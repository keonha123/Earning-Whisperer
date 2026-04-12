import { BrowserWindow } from 'electron'
import { mainState } from '../store/mainState'
import { KisService } from './KisService'
import { BackendClient } from './BackendClient'
import { NotificationService } from './NotificationService'
import { IPC_CHANNELS } from '../../lib/ipcChannels'

export interface TradeSignal {
  trade_id: string
  action: 'BUY' | 'SELL'
  /**
   * 주문 비율. 서버 PortfolioSettings.buyAmountRatio 값이 실려 온다.
   * BUY: 예수금 대비 매수 비율 → qty = floor(orderableCash × ratio / currentPrice)
   * SELL: 보유수량 대비 매도 비율 → qty = max(1, floor(holdingQty × ratio))
   */
  order_ratio: number
  ticker: string
  ai_score: number
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
      // Step 1: 잔고 조회 (+ BUY 시 현재가 조회) → 수량 산출
      const balance = await KisService.getBalance()
      const currentPrice = signal.action === 'BUY'
        ? await KisService.getCurrentPrice(signal.ticker)
        : 0
      const finalQty = calcQty(signal, balance, currentPrice)

      if (finalQty <= 0) {
        const reason = failureReason(signal, balance, currentPrice)
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

type BalanceLite = { orderableCash: number; holdings: { ticker: string; qty: number }[] }

/**
 * 주문 수량 산출 — 서버가 내려준 order_ratio를 로컬 실잔고·실가격에 적용한다.
 * 자본시장법상 수량 결정 주체는 사용자 로컬(본 함수)이며, 서버는 비율까지만 결정한다.
 */
function calcQty(signal: TradeSignal, balance: BalanceLite, currentPrice: number): number {
  const ratio = signal.order_ratio
  if (!(ratio > 0 && ratio <= 1)) return 0

  if (signal.action === 'BUY') {
    const cash = Number.isFinite(balance.orderableCash) ? balance.orderableCash : 0
    if (cash <= 0 || !Number.isFinite(currentPrice) || currentPrice <= 0) return 0
    const qty = Math.floor(cash * ratio / currentPrice)
    return Number.isFinite(qty) ? qty : 0
  }

  // SELL: 보유수량 × ratio. floor=0이면 주문 안 함 (서버 의도 비율 초과 매도 방지)
  const rawQty = balance.holdings.find((h) => h.ticker === signal.ticker)?.qty
  const available = Number.isFinite(rawQty) ? rawQty! : 0
  if (available <= 0) return 0
  return Math.floor(available * ratio)
}

function failureReason(signal: TradeSignal, balance: BalanceLite, currentPrice: number): string {
  if (!(signal.order_ratio > 0 && signal.order_ratio <= 1)) return `비정상 order_ratio=${signal.order_ratio}`
  if (signal.action === 'BUY') {
    if (currentPrice <= 0) return '현재가 조회 실패'
    if (balance.orderableCash <= 0) return '예수금 부족'
    return '예수금 대비 주문 비율이 1주 가격에 못 미침'
  }
  const rawQty = balance.holdings.find((h) => h.ticker === signal.ticker)?.qty
  const available = Number.isFinite(rawQty) ? rawQty! : 0
  if (available <= 0) return '보유 수량 없음'
  return '보유수량 대비 비율이 1주에 못 미침'
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
