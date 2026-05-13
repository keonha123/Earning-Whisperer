import { BrowserWindow } from 'electron'
import { KisService } from '../services/KisService'
import { TradeExecutor } from '../services/TradeExecutor'
import { BackendClient } from '../services/BackendClient'
import { mainState } from '../store/mainState'
import { IPC_CHANNELS } from '../../lib/ipcChannels'
import { IpcError, sanitizeAxiosErrorDetails } from '../../lib/types/ipcError'
import { registerHandler } from './registerHandler'

interface ManualOrderRequest {
  side: 'BUY' | 'SELL'
  ticker: string
  qty: number
  price: number | null
}

function pushToRenderer(channel: string, payload: unknown) {
  BrowserWindow.getAllWindows().forEach((win) => {
    if (!win.isDestroyed()) win.webContents.send(channel, payload)
  })
}

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

  registerHandler(IPC_CHANNELS.KIS_PLACE_MANUAL_ORDER, async (_e, req: ManualOrderRequest) => {
    if (!req?.ticker || typeof req.qty !== 'number' || req.qty <= 0) {
      throw new IpcError('VALIDATION_ERROR', '올바르지 않은 주문 파라미터입니다.')
    }
    if (req.price != null && (!Number.isFinite(req.price) || req.price <= 0)) {
      throw new IpcError('VALIDATION_ERROR', '올바르지 않은 지정가입니다.')
    }
    if (mainState.isOrderInProgress) {
      throw new IpcError('ORDER_IN_PROGRESS', '이미 주문이 진행 중입니다.')
    }

    mainState.setOrderInProgress(true)
    try {
      const price = req.price ?? undefined
      const orderResult = await KisService.placeOrder(req.side, req.ticker, req.qty, price)

      const payload = {
        ticker: req.ticker,
        side: req.side,
        order_type: req.price != null ? ('LIMIT' as const) : ('MARKET' as const),
        order_qty: req.qty,
        price: req.price ?? 0,
        executed_qty: orderResult.executedQty,
        executed_price: orderResult.executedPrice,
        broker_order_id: orderResult.orderId || null,
        status: 'EXECUTED' as const,
        error_message: null,
      }
      BackendClient.recordManualTrade(payload).catch((e) =>
        console.error('[kisHandlers] 수동 주문 기록 실패:', e),
      )

      // 포트폴리오 동기화 (비동기)
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
        .catch((e) => console.error('[kisHandlers] 포트폴리오 동기화 실패:', e))

      const result = {
        status: 'EXECUTED' as const,
        orderId: orderResult.orderId,
        executedPrice: orderResult.executedPrice,
        executedQty: orderResult.executedQty,
        errorMessage: null,
      }
      pushToRenderer(IPC_CHANNELS.TRADE_EXECUTED, result)
      return result
    } catch (e) {
      const err = toKisError(e, '수동 주문 실패')
      const failPayload = {
        ticker: req.ticker,
        side: req.side,
        order_type: req.price != null ? ('LIMIT' as const) : ('MARKET' as const),
        order_qty: req.qty,
        price: req.price ?? 0,
        executed_qty: 0,
        executed_price: null,
        broker_order_id: null,
        status: 'FAILED' as const,
        error_message: err.message,
      }
      BackendClient.recordManualTrade(failPayload).catch(() => {})
      pushToRenderer(IPC_CHANNELS.TRADE_FAILED, { errorMessage: err.message })
      throw err
    } finally {
      mainState.setOrderInProgress(false)
    }
  })
}
