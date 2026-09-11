import { BrowserWindow } from 'electron'
import { KisService } from '../services/KisService'
import { TradeExecutor, type TradeSignal } from '../services/TradeExecutor'
import { BackendClient, type AssetHistoryPoint } from '../services/BackendClient'
import { mainState } from '../store/mainState'
import { IPC_CHANNELS } from '../../lib/ipcChannels'
import { immediateFillPrice } from '../../lib/orderPricing'
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
async function executeSelfPaperManual(req: ManualOrderRequest) {
  const cash = mainState.selfPaperCash ?? 0
  const holdings = mainState.selfPaperHoldings
  const currentPrice = mainState.getPriceFromCache(req.ticker) ?? 0
  const executedPrice = req.price ?? currentPrice

  if (executedPrice <= 0) {
    throw new IpcError('KIS_ERROR', '현재가 정보를 찾을 수 없습니다.')
  }

  if (req.side === 'BUY') {
    if (cash < executedPrice * req.qty) {
      throw new IpcError('KIS_ERROR', '잔고가 부족합니다.')
    }
  } else {
    const holding = holdings.find((h) => h.ticker === req.ticker)
    if (!holding || holding.qty < req.qty) {
      throw new IpcError('KIS_ERROR', '보유 수량이 부족합니다.')
    }
  }

  const updatedCash = req.side === 'BUY'
    ? cash - executedPrice * req.qty
    : cash + executedPrice * req.qty

  const updatedHoldings = req.side === 'BUY'
    ? (() => {
        const existing = holdings.find((h) => h.ticker === req.ticker)
        return existing
          ? holdings.map((h) => h.ticker === req.ticker ? { ...h, qty: h.qty + req.qty } : h)
          : [...holdings, { ticker: req.ticker, qty: req.qty }]
      })()
    : holdings
        .map((h) => h.ticker === req.ticker ? { ...h, qty: h.qty - req.qty } : h)
        .filter((h) => h.qty > 0)

  mainState.setSelfPaperBalance(updatedCash, updatedHoldings)
  pushToRenderer(IPC_CHANNELS.SELF_PAPER_BALANCE_UPDATED, {
    cash: updatedCash,
    holdings: updatedHoldings,
  })

  BackendClient.recordManualTrade({
    ticker: req.ticker,
    side: req.side,
    order_type: req.price != null ? 'LIMIT' : 'MARKET',
    order_qty: req.qty,
    price: executedPrice,
    executed_qty: req.qty,
    executed_price: executedPrice,
    broker_order_id: null,
    status: 'EXECUTED',
    error_message: null,
  }).catch((e) => console.error('[kisHandlers] SELF_PAPER 수동 주문 기록 실패:', e))

  const result = {
    status: 'EXECUTED' as const,
    orderId: null,
    executedPrice,
    executedQty: req.qty,
    errorMessage: null,
  }
  pushToRenderer(IPC_CHANNELS.TRADE_EXECUTED, result)
  return result
}

/**
 * "즉시 체결" 수동 주문이 KIS 로 나갈 때 쓸 지정가를 조회·산출한다.
 *
 * 기준가는 KIS 현재가(HHDFS00000300) 를 먼저 쓰고, 비어 오면 백엔드 시세 스트림이
 * 채운 pricesCache 로 폴백한다. KIS 모의투자 계좌는 해외주식 시세가 비어 오는 경우가
 * 있고, 그때 캐시 값은 화면에 표시된 현재가와 같은 출처라 사용자가 본 값과 일치한다.
 *
 * 양쪽 모두 없으면 주문을 보내지 않고 실패시킨다 — 0달러 지정가로 나가서
 * 영원히 미체결로 남는 것보다 즉시 에러가 낫다.
 */
async function resolveImmediateFillPrice(side: 'BUY' | 'SELL', ticker: string): Promise<number> {
  const { currentPrice } = await KisService.getCurrentPrice(ticker)
  let basis = currentPrice
  if (!(basis > 0)) {
    basis = mainState.getPriceFromCache(ticker) ?? 0
    if (basis > 0) {
      console.warn(`[kisHandlers] KIS 현재가 없음 — 시세 캐시로 폴백 ticker=${ticker} price=${basis}`)
    }
  }
  const price = immediateFillPrice(side, basis)
  if (price == null) {
    throw new IpcError('KIS_ERROR', '현재가를 조회할 수 없어 주문을 보내지 않았습니다.')
  }
  return price
}

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
    if (mainState.accountType === 'SELF_PAPER') {
      const cash = mainState.selfPaperCash ?? 0
      return {
        orderableCash: cash,
        totalCash: cash,
        holdings: mainState.selfPaperHoldings.map((h) => ({
          ticker: h.ticker,
          qty: h.qty,
          avgPrice: 0,
          currentPrice: mainState.getPriceFromCache(h.ticker) ?? 0,
        })),
      }
    }
    try {
      return await KisService.getBalance()
    } catch (e) {
      throw toKisError(e, '잔고 조회 실패')
    }
  })

  registerHandler<TradeSignal>(IPC_CHANNELS.KIS_PLACE_ORDER, async (_e, signal) => {
    try {
      return await TradeExecutor.execute(signal)
    } catch (e) {
      throw toKisError(e, '주문 실패')
    }
  })

  registerHandler(IPC_CHANNELS.KIS_PLACE_MANUAL_ORDER, async (_e, req: ManualOrderRequest) => {
    if (!req?.ticker || typeof req.qty !== 'number' || req.qty <= 0) {
      throw new IpcError('VALIDATION', '올바르지 않은 주문 파라미터입니다.')
    }
    if (req.price != null && (!Number.isFinite(req.price) || req.price <= 0)) {
      throw new IpcError('VALIDATION', '올바르지 않은 지정가입니다.')
    }
    if (mainState.isOrderInProgress) {
      throw new IpcError('BUSINESS_RULE', '이미 주문이 진행 중입니다.')
    }

    // SELF_PAPER 수동 주문 — KIS API 미경유, pricesCache 현재가 기준 즉시 가상 체결
    if (mainState.accountType === 'SELF_PAPER') {
      return executeSelfPaperManual(req)
    }

    mainState.setOrderInProgress(true)
    // catch 블록의 기록 payload 도 실제로 보낸 가격을 남겨야 하므로 try 밖에서 선언한다.
    // null = 아직 가격이 확정되지 않음 (현재가 조회 실패 등) → KIS 로 아무것도 나가지 않았다.
    let orderPrice: number | null = req.price
    try {
      // req.price == null 은 "즉시 체결" 의도다. KIS 해외주식 매수에는 시장가 코드가
      // 없으므로 현재가 기준 버퍼 지정가로 환산해서 보낸다 (orderPricing 주석 참고).
      if (req.price == null) {
        orderPrice = await resolveImmediateFillPrice(req.side, req.ticker)
      }
      // 위 분기를 통과했으므로 orderPrice 는 확정값이다.
      const orderResult = await KisService.placeOrder(
        req.side,
        req.ticker,
        req.qty,
        orderPrice as number,
      )

      const payload = {
        ticker: req.ticker,
        side: req.side,
        // 브로커에 실제로 나간 주문은 항상 지정가다.
        order_type: 'LIMIT' as const,
        order_qty: req.qty,
        price: orderPrice as number,
        executed_qty: orderResult.executedQty,
        executed_price: orderResult.executedPrice,
        broker_order_id: orderResult.orderId || null,
        status: orderResult.executedQty > 0 ? ('EXECUTED' as const) : ('PENDING' as const),
        error_message: null,
      }
      BackendClient.recordManualTrade(payload).catch((e) =>
        console.error('[kisHandlers] 수동 주문 기록 실패:', e),
      )

      // 포트폴리오 동기화 (비동기)
      KisService.getBalance()
        .then((balance) =>
          BackendClient.syncPortfolio({
            cash_balance: balance.totalCash,
            positions: balance.holdings.map((h) => ({
              ticker: h.ticker,
              quantity: h.qty,
              avg_price: h.avgPrice,
            })),
          }),
        )
        .catch((e: any) =>
          // raw AxiosError 를 그대로 찍으면 config.headers 의 appkey/appsecret 이 로그에 남는다
          console.error('[kisHandlers] 포트폴리오 동기화 실패:', e?.response?.data ?? e?.message),
        )

      const result = {
        status: orderResult.executedQty > 0 ? ('EXECUTED' as const) : ('PENDING' as const),
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
        // 가격 확정 전에 실패했다면 KIS 로 나간 주문이 없다 — 존재하지 않는 "$0 지정가"
        // 시도를 기록하지 않도록 주문 유형을 원래 의도(즉시 체결)대로 남긴다.
        order_type: orderPrice != null ? ('LIMIT' as const) : ('MARKET' as const),
        order_qty: req.qty,
        price: orderPrice ?? 0,
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

  registerHandler<{ days: number }, AssetHistoryPoint[]>(
    IPC_CHANNELS.KIS_GET_ASSET_TIMESERIES,
    async (_e, payload) => {
      const days = [7, 30, 90].includes(payload?.days) ? payload.days : 30
      return BackendClient.getAssetHistory(days)
    },
  )
}
