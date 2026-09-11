import { createDecipheriv } from 'node:crypto'
import axios from 'axios'
import WebSocket from 'ws'
import keytar from 'keytar'
import { BrowserWindow } from 'electron'
import { mainState } from '../store/mainState'
import { IPC_CHANNELS } from '../../lib/ipcChannels'
import { markKisWsCovered, clearKisWsCovered } from './PricePoller'

/**
 * KIS WebSocket 엔드포인트 (공식 샘플 legacy/websocket/python 기준).
 *
 * 이전에는 실전 주소 하나(`wss://openapi.koreainvestment.com:9443/websocket`)만 하드코딩돼
 * 있었는데 공식 규격과 다르다. 실전 앱키가 등록된 적이 없어 이 코드가 한 번도 연결되지
 * 않았고, 그래서 주소가 틀린 것도 드러나지 않았다.
 */
const WS_URL_REAL = 'ws://ops.koreainvestment.com:21000'
const WS_URL_PAPER = 'ws://ops.koreainvestment.com:31000'
const APPROVAL_URL_REAL = 'https://openapi.koreainvestment.com:9443/oauth2/Approval'
const APPROVAL_URL_PAPER = 'https://openapivts.koreainvestment.com:29443/oauth2/Approval'

const KEYTAR_SERVICE = 'EarningWhisperer'
/** 해외주식 실시간 체결가 (시세). */
const TR_HDFSCNT0 = 'HDFSCNT0'
/** 해외주식 실시간 체결통보. 모의는 뒤가 9. tr_key 는 종목이 아니라 HTS ID. */
const TR_NOTICE_REAL = 'H0GSCNI0'
const TR_NOTICE_PAPER = 'H0GSCNI9'

function wsUrl(paper: boolean): string {
  return paper ? WS_URL_PAPER : WS_URL_REAL
}

function approvalUrl(paper: boolean): string {
  return paper ? APPROVAL_URL_PAPER : APPROVAL_URL_REAL
}

function noticeTrId(paper: boolean): string {
  return paper ? TR_NOTICE_PAPER : TR_NOTICE_REAL
}

const RECONNECT_DELAY_MS = 5_000
const MAX_SLOTS = 41
// Each ticker requires 2 subscriptions: regular (night) + day market
const SLOTS_PER_TICKER = 2
export const MAX_TICKERS = Math.floor(MAX_SLOTS / SLOTS_PER_TICKER)  // 20

// --------------------------------------------------------------------------
// Exchange routing
// --------------------------------------------------------------------------

export type KisExchange = 'NAS' | 'NYS' | 'AMS'

// tr_key 접두사 매핑 (아키텍처 결정 문서 §2 검증 완료 항목 기준)
// 정규장(야간): D + {NAS|NYS|AMS} + ticker
// 데이마켓:     R + {BAQ|BAY|BAA} + ticker
const NIGHT_PREFIX: Record<KisExchange, string> = { NAS: 'DNAS', NYS: 'DNYS', AMS: 'DAMS' }
const DAY_PREFIX:   Record<KisExchange, string> = { NAS: 'RBAQ', NYS: 'RBAY', AMS: 'RBAA' }

// 알려진 NYSE 상장 종목. 목록 미포함 ticker는 NASDAQ 으로 fallback.
// AMEX 개별 종목은 현재 대상 없음 (ETF/소형주 위주) — 필요 시 exchangeOverrides 로 주입.
const STATIC_NYSE: ReadonlySet<string> = new Set([
  // Financials
  'JPM', 'BAC', 'WFC', 'C', 'GS', 'MS', 'BX', 'KKR',
  // Consumer / Retail
  'WMT', 'TGT', 'HD', 'MCD', 'NKE', 'DIS', 'KO', 'PEP', 'PG', 'MO', 'PM',
  // Energy
  'XOM', 'CVX', 'COP',
  // Healthcare
  'JNJ', 'PFE', 'MRK', 'ABT', 'BMY', 'UNH',
  // Industrials / Defense / Telecom
  'IBM', 'GE', 'BA', 'CAT', 'MMM', 'F', 'GM', 'T', 'VZ', 'UPS', 'FDX', 'LMT', 'RTX',
  // Payments
  'V', 'MA',
  // Tech / Internet on NYSE
  'UBER', 'SNAP', 'CRM', 'TWLO', 'DASH',
  // Chinese ADRs on NYSE
  'NIO', 'XPEV',
])

// 런타임 override — setExchangeHints() 로 주입. 정적 맵보다 우선.
const exchangeOverrides = new Map<string, KisExchange>()

/**
 * 외부에서 exchange 정보를 주입할 때 사용.
 * 백엔드가 WatchlistItem 에 exchange 필드를 추가하는 시점에 watchlistHandlers 에서 호출.
 */
export function setExchangeHints(hints: Record<string, KisExchange>): void {
  for (const [ticker, exchange] of Object.entries(hints)) {
    exchangeOverrides.set(ticker, exchange)
  }
}

export function resolveExchange(ticker: string): KisExchange {
  return exchangeOverrides.get(ticker) ?? (STATIC_NYSE.has(ticker) ? 'NYS' : 'NAS')
}

type WsState = 'DISCONNECTED' | 'CONNECTING' | 'CONNECTED'

let ws: WebSocket | null = null
let approvalKey: string | null = null
let storedAppKey: string | null = null
let storedAppSecret: string | null = null
let wsState: WsState = 'DISCONNECTED'
let reconnectTimer: NodeJS.Timeout | null = null
const subscribedTickers = new Set<string>()

/**
 * 체결통보 본문 복호화용 키/IV. 구독 응답(`body.output.key`/`iv`) 으로만 받을 수 있고
 * 연결이 끊기면 무효다. 재연결 시 재구독으로 다시 받는다.
 */
let noticeAesKey: string | null = null
let noticeAesIv: string | null = null
let noticeHtsId: string | null = null
let onFillNotice: ((fill: FillNotice) => void) | null = null

export interface FillNotice {
  /** KIS 주문번호 (ODNO). */
  orderId: string
  ticker: string
  executedQty: number
  executedPrice: number | null
}

/**
 * 해외주식 실시간 체결통보(H0GSCNI0/9) 응답 필드 순서 — 공식 샘플
 * examples_llm/overseas_stock/ccnl_notice 기준. 순서가 규격이므로 인덱스로 읽는다.
 */
const NOTICE_IDX = {
  ODER_NO: 2,
  STCK_SHRN_ISCD: 7,
  CNTG_QTY: 8,
  CNTG_UNPR: 9,
  CNTG_YN: 12,
} as const

/**
 * AES-256-CBC + base64 복호화. 구독 응답의 key/iv 는 각각 32바이트 / 16바이트 문자열이다.
 */
function decryptNotice(cipherText: string): string | null {
  if (!noticeAesKey || !noticeAesIv) return null
  try {
    const decipher = createDecipheriv('aes-256-cbc', noticeAesKey, noticeAesIv)
    return Buffer.concat([
      decipher.update(Buffer.from(cipherText, 'base64')),
      decipher.final(),
    ]).toString('utf-8')
  } catch (e) {
    console.warn('[KisWS] 체결통보 복호화 실패:', e instanceof Error ? e.message : e)
    return null
  }
}

/**
 * 체결통보를 FillNotice 로 변환. 체결이 아닌 통보(주문 접수/정정/취소/거부)는 null.
 *
 * CNTG_YN: '1' = 주문·정정·취소·거부 접수 통보, '2' = 체결 통보.
 */
export function parseFillNotice(plain: string): FillNotice | null {
  const fields = plain.split('^')
  if (fields.length <= NOTICE_IDX.CNTG_YN) return null
  if (fields[NOTICE_IDX.CNTG_YN] !== '2') return null

  const orderId = (fields[NOTICE_IDX.ODER_NO] ?? '').trim()
  const ticker = (fields[NOTICE_IDX.STCK_SHRN_ISCD] ?? '').trim()
  const qty = Number(fields[NOTICE_IDX.CNTG_QTY])
  const price = Number(fields[NOTICE_IDX.CNTG_UNPR])
  if (!orderId || !Number.isFinite(qty) || qty <= 0) return null

  return {
    orderId,
    ticker,
    executedQty: qty,
    executedPrice: Number.isFinite(price) && price > 0 ? price : null,
  }
}

function pushToRenderer(channel: string, payload: unknown) {
  BrowserWindow.getAllWindows().forEach((win) => {
    if (!win.isDestroyed()) win.webContents.send(channel, payload)
  })
}

async function getApprovalKey(appKey: string, appSecret: string): Promise<string> {
  const { data } = await axios.post(
    approvalUrl(mainState.isPaperTrading),
    { grant_type: 'client_credentials', appkey: appKey, secretkey: appSecret },
    { timeout: 10_000 },
  )
  if (!data.approval_key) throw new Error('KIS WebSocket approval_key 미반환')
  return data.approval_key as string
}

function buildMessage(trKey: string, trType: '1' | '2', trId: string = TR_HDFSCNT0): string {
  return JSON.stringify({
    header: {
      approval_key: approvalKey,
      custtype: 'P',
      tr_type: trType,
      'content-type': 'utf-8',
    },
    body: { input: { tr_id: trId, tr_key: trKey } },
  })
}

/**
 * tr_key 포맷: {D|R}{exchange 3chars}{ticker}
 * exchange 는 resolveExchange() 로 결정 (override → 정적 NYSE 맵 → NASDAQ 기본).
 */
function trKeysFor(ticker: string): [string, string] {
  const ex = resolveExchange(ticker)
  return [`${NIGHT_PREFIX[ex]}${ticker}`, `${DAY_PREFIX[ex]}${ticker}`]
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

function sendNoticeSubscribe() {
  if (!ws || ws.readyState !== WebSocket.OPEN || !noticeHtsId) return
  ws.send(buildMessage(noticeHtsId, '1', noticeTrId(mainState.isPaperTrading)))
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
    // 활성 모드의 키로 연결한다. 이전에는 실전 키만 찾아서, 모의투자 사용자는
    // 체결통보는 물론 KIS 실시간 시세도 전혀 받을 수 없었다.
    const paper = mainState.isPaperTrading
    const suffix = paper ? 'paper' : 'real'
    const [appKey, appSecret, htsId] = await Promise.all([
      keytar.getPassword(KEYTAR_SERVICE, `kis-appKey-${suffix}`),
      keytar.getPassword(KEYTAR_SERVICE, `kis-appSecret-${suffix}`),
      keytar.getPassword(KEYTAR_SERVICE, `kis-htsId-${suffix}`),
    ])
    if (!appKey || !appSecret) {
      console.info(`[KisWS] ${suffix} 앱키 미등록 — KIS WebSocket 미연결`)
      return
    }
    // HTS ID 가 없으면 체결통보만 못 받고 시세 구독은 그대로 동작한다.
    noticeHtsId = htsId
    if (!htsId) {
      console.info('[KisWS] HTS ID 미등록 — 실시간 체결통보 미구독 (시세만 구독)')
    }
    await KisWebSocketService.connect(appKey, appSecret)
  },

  /**
   * 체결통보 수신 콜백 등록. 통보가 오면 그 주문의 체결을 백엔드에 반영하는 쪽에서 쓴다.
   * WebSocket 계층이 백엔드/IPC 를 직접 알지 않도록 콜백으로 뺀다.
   */
  setFillNoticeHandler(handler: ((fill: FillNotice) => void) | null): void {
    onFillNotice = handler
  },

  /** 테스트/진단용 — 체결통보 구독 상태. */
  getNoticeStatus(): { htsId: boolean; decryptable: boolean } {
    return { htsId: !!noticeHtsId, decryptable: !!(noticeAesKey && noticeAesIv) }
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

    ws = new WebSocket(wsUrl(mainState.isPaperTrading))

    ws.on('open', () => {
      wsState = 'CONNECTED'
      console.info('[KisWS] 연결됨')
      // 재연결 후 기존 ticker 재구독
      for (const ticker of subscribedTickers) {
        sendSubscribe(ticker)
      }
      // 체결통보 재구독 — AES 키/IV 는 연결마다 새로 받아야 한다.
      if (noticeHtsId) sendNoticeSubscribe()
    })

    ws.on('message', (data: Buffer) => {
      const raw = data.toString('utf-8')
      // 시스템 메시지 — JSON 형식
      if (raw.startsWith('{')) {
        try {
          const msg = JSON.parse(raw) as {
            header?: { tr_id?: string }
            body?: { output?: { key?: string; iv?: string }; msg1?: string; rt_cd?: string }
          }
          if (msg?.header?.tr_id === 'PINGPONG') {
            ws?.send(JSON.stringify({ header: { tr_id: 'PINGPONG' } }))
            return
          }
          // 체결통보 구독 응답에만 복호화 key/iv 가 실려 온다. 이걸 놓치면 이후 통보를
          // 받아도 읽을 수 없다.
          //
          // tr_id 로 범위를 좁힌다 — key/iv 가 있으면 무조건 받아들이면 다른 TR 응답이
          // 같은 필드명을 갖게 될 때 진짜 키가 조용히 덮이고, 이후 복호화가 계속
          // 실패하는데 로그 한 줄만 남아 알아채기 어렵다.
          if (msg?.header?.tr_id === noticeTrId(mainState.isPaperTrading)) {
            const key = msg?.body?.output?.key
            const iv = msg?.body?.output?.iv
            if (key && iv) {
              noticeAesKey = key
              noticeAesIv = iv
              console.info('[KisWS] 체결통보 구독 완료 — 복호화 키 수신')
            } else {
              console.warn(
                '[KisWS] 체결통보 구독 응답에 key/iv 없음:',
                msg?.body?.msg1 ?? raw.slice(0, 200),
              )
            }
          }
        } catch {
          // ignore malformed system message
        }
        return
      }

      // 데이터 프레임 — 선두 '1' 은 암호화된 체결통보, '0' 은 평문 시세
      if (raw.startsWith('1|')) {
        const parts = raw.split('|')
        if (parts.length < 4) return
        const plain = decryptNotice(parts[3])
        if (!plain) return
        const notice = parseFillNotice(plain)
        if (!notice) return
        console.info(
          `[KisWS] 체결통보 — ODNO=${notice.orderId} ${notice.ticker} ${notice.executedQty}주 @${notice.executedPrice}`,
        )
        onFillNotice?.(notice)
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
      // 키/IV 는 연결 단위로만 유효하다. 남겨두면 재연결 후 옛 키로 복호화를 시도한다.
      noticeAesKey = null
      noticeAesIv = null
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
    noticeAesKey = null
    noticeAesIv = null
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
