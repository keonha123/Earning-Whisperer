import axios from 'axios'
import WebSocket from 'ws'
import keytar from 'keytar'
import { BrowserWindow } from 'electron'
import { mainState } from '../store/mainState'
import { IPC_CHANNELS } from '../../lib/ipcChannels'
import { markKisWsCovered, clearKisWsCovered } from './PricePoller'

const KIS_WS_URL = 'wss://openapi.koreainvestment.com:9443/websocket'
const KIS_APPROVAL_URL = 'https://openapi.koreainvestment.com:9443/oauth2/Approval'
const KEYTAR_SERVICE = 'EarningWhisperer'
const TR_HDFSCNT0 = 'HDFSCNT0'

const RECONNECT_DELAY_MS = 5_000
const MAX_SLOTS = 41
// Each ticker requires 2 subscriptions: regular (DNAS) + day market (RBAQ)
const SLOTS_PER_TICKER = 2
export const MAX_TICKERS = Math.floor(MAX_SLOTS / SLOTS_PER_TICKER)  // 20

type WsState = 'DISCONNECTED' | 'CONNECTING' | 'CONNECTED'

let ws: WebSocket | null = null
let approvalKey: string | null = null
let storedAppKey: string | null = null
let storedAppSecret: string | null = null
let wsState: WsState = 'DISCONNECTED'
let reconnectTimer: NodeJS.Timeout | null = null
const subscribedTickers = new Set<string>()

function pushToRenderer(channel: string, payload: unknown) {
  BrowserWindow.getAllWindows().forEach((win) => {
    if (!win.isDestroyed()) win.webContents.send(channel, payload)
  })
}

async function getApprovalKey(appKey: string, appSecret: string): Promise<string> {
  const { data } = await axios.post(
    KIS_APPROVAL_URL,
    { grant_type: 'client_credentials', appkey: appKey, secretkey: appSecret },
    { timeout: 10_000 },
  )
  if (!data.approval_key) throw new Error('KIS WebSocket approval_key 미반환')
  return data.approval_key as string
}

function buildMessage(trKey: string, trType: '1' | '2'): string {
  return JSON.stringify({
    header: {
      approval_key: approvalKey,
      custtype: 'P',
      tr_type: trType,
      'content-type': 'utf-8',
    },
    body: { input: { tr_id: TR_HDFSCNT0, tr_key: trKey } },
  })
}

/**
 * tr_key 포맷: {D|R}{exchange 3chars}{ticker}
 * - 정규장(야간): DNAS{ticker}
 * - 데이마켓:     RBAQ{ticker}
 *
 * TODO: exchange 다양화 (NYSE: NYS/BAY, AMEX: AMS/BAA). 현재는 NASDAQ 단일 가정.
 */
function trKeysFor(ticker: string): [string, string] {
  return [`DNAS${ticker}`, `RBAQ${ticker}`]
}

function sendSubscribe(ticker: string) {
  if (!ws || ws.readyState !== WebSocket.OPEN) return
  const [regular, day] = trKeysFor(ticker)
  ws.send(buildMessage(regular, '1'))
  ws.send(buildMessage(day, '1'))
}

function sendUnsubscribe(ticker: string) {
  if (!ws || ws.readyState !== WebSocket.OPEN) return
  const [regular, day] = trKeysFor(ticker)
  ws.send(buildMessage(regular, '2'))
  ws.send(buildMessage(day, '2'))
}

/**
 * HDFSCNT0 시세 메시지 파싱.
 * 형식: "0|HDFSCNT0|count|MKSC_SHRN_ISCD^STCK_CNTG_HOUR^STCK_PRPR^PRDY_VRSS_SIGN^PRDY_VRSS^..."
 * - fields[0]: tr_key (예: "DNASAAPL")
 * - fields[2]: STCK_PRPR (현재가)
 * - fields[3]: PRDY_VRSS_SIGN (부호: 1/2=상승, 4/5=하락)
 * - fields[4]: PRDY_VRSS (전일 대비 절대값)
 */
function parseHdfscnt0(raw: string): { ticker: string; price: number; previousClose: number } | null {
  const parts = raw.split('|')
  if (parts.length < 4 || parts[0] !== '0' || parts[1] !== TR_HDFSCNT0) return null
  const fields = parts[3].split('^')
  if (fields.length < 5) return null

  const trKey = fields[0]
  if (!trKey || trKey.length < 5) return null
  const ticker = trKey.slice(4)  // 1-char prefix + 3-char exchange = 4 chars

  const price = parseFloat(fields[2])
  if (!ticker || !Number.isFinite(price) || price <= 0) return null

  const sign = fields[3]
  const diffAbs = parseFloat(fields[4])
  const diff = (sign === '4' || sign === '5') ? -Math.abs(diffAbs) : Math.abs(diffAbs)
  const previousClose = Number.isFinite(diff) ? price - diff : 0

  return { ticker, price, previousClose }
}

function scheduleReconnect() {
  if (reconnectTimer || !storedAppKey || !storedAppSecret) return
  reconnectTimer = setTimeout(async () => {
    reconnectTimer = null
    if (wsState === 'DISCONNECTED' && storedAppKey && storedAppSecret) {
      console.info('[KisWS] 재연결 시도')
      await KisWebSocketService.connect(storedAppKey, storedAppSecret)
    }
  }, RECONNECT_DELAY_MS)
}

export const KisWebSocketService = {
  isConnected(): boolean {
    return wsState === 'CONNECTED'
  },

  subscribedCount(): number {
    return subscribedTickers.size * SLOTS_PER_TICKER
  },

  /**
   * keytar 에서 실전(real) 앱키를 읽어 WebSocket 연결.
   * 실전 키 미등록 시 silent skip (페이퍼/SELF_PAPER 사용자는 KIS WS 불필요).
   */
  async connectWithStoredKey(): Promise<void> {
    const appKey = await keytar.getPassword(KEYTAR_SERVICE, 'kis-appKey-real')
    const appSecret = await keytar.getPassword(KEYTAR_SERVICE, 'kis-appSecret-real')
    if (!appKey || !appSecret) {
      console.info('[KisWS] 실전 앱키 미등록 — KIS WebSocket 미연결')
      return
    }
    await KisWebSocketService.connect(appKey, appSecret)
  },

  async connect(appKey: string, appSecret: string): Promise<void> {
    if (wsState !== 'DISCONNECTED') return

    wsState = 'CONNECTING'
    storedAppKey = appKey
    storedAppSecret = appSecret

    try {
      approvalKey = await getApprovalKey(appKey, appSecret)
    } catch (e) {
      console.warn('[KisWS] approval key 발급 실패:', e instanceof Error ? e.message : e)
      wsState = 'DISCONNECTED'
      scheduleReconnect()
      return
    }

    ws = new WebSocket(KIS_WS_URL)

    ws.on('open', () => {
      wsState = 'CONNECTED'
      console.info('[KisWS] 연결됨')
      // 재연결 후 기존 ticker 재구독
      for (const ticker of subscribedTickers) {
        sendSubscribe(ticker)
      }
    })

    ws.on('message', (data: Buffer) => {
      const raw = data.toString('utf-8')
      // 시스템 메시지 — JSON 형식
      if (raw.startsWith('{')) {
        try {
          const msg = JSON.parse(raw) as { header?: { tr_id?: string } }
          if (msg?.header?.tr_id === 'PINGPONG') {
            ws?.send(JSON.stringify({ header: { tr_id: 'PINGPONG' } }))
          }
        } catch {
          // ignore malformed system message
        }
        return
      }
      // 데이터 메시지 — 파이프 구분
      const parsed = parseHdfscnt0(raw)
      if (!parsed) return

      const { ticker, price, previousClose } = parsed
      mainState.updatePricesCache({ [ticker]: price })
      markKisWsCovered([ticker])
      pushToRenderer(IPC_CHANNELS.PRICES_UPDATE, [{
        ticker,
        currentPrice: price,
        previousClose,
        lastUpdated: Date.now(),
      }])
    })

    ws.on('close', () => {
      wsState = 'DISCONNECTED'
      clearKisWsCovered()
      console.info('[KisWS] 연결 종료 — 재연결 예약')
      scheduleReconnect()
    })

    ws.on('error', (err) => {
      console.warn('[KisWS] WebSocket 오류:', err.message)
    })
  },

  disconnect(): void {
    if (reconnectTimer) {
      clearTimeout(reconnectTimer)
      reconnectTimer = null
    }
    ws?.close()
    ws = null
    wsState = 'DISCONNECTED'
    approvalKey = null
    storedAppKey = null
    storedAppSecret = null
    subscribedTickers.clear()
    clearKisWsCovered()
  },

  subscribe(ticker: string): void {
    if (!ticker || subscribedTickers.has(ticker)) return
    subscribedTickers.add(ticker)
    if (wsState === 'CONNECTED') sendSubscribe(ticker)
  },

  unsubscribe(ticker: string): void {
    if (!subscribedTickers.has(ticker)) return
    subscribedTickers.delete(ticker)
    if (wsState === 'CONNECTED') sendUnsubscribe(ticker)
  },
}
