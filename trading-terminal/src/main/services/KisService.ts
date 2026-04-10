import axios from 'axios'
import keytar from 'keytar'
import { BrowserWindow } from 'electron'
import { mainState } from '../store/mainState'
import { IPC_CHANNELS } from '../../lib/ipcChannels'

// 모의투자 URL (실전: https://openapi.koreainvestment.com:9443)
const KIS_BASE_URL = 'https://openapivts.koreainvestment.com:29443'
const KEYTAR_SERVICE = 'EarningWhisperer'

const kisHttp = axios.create({ baseURL: KIS_BASE_URL, timeout: 10_000 })

function pushToRenderer(channel: string, payload: unknown) {
  BrowserWindow.getAllWindows().forEach((win) => {
    if (!win.isDestroyed()) win.webContents.send(channel, payload)
  })
}

// EGW00133 fallback 시 복원 토큰 최소 잔여 시간
const MIN_REMAINING_SEC_FOR_RESTORE = 600

async function saveTokenToVault(token: string, expiresIn: number): Promise<void> {
  try {
    const expiresAt = Date.now() + expiresIn * 1000
    await keytar.setPassword(KEYTAR_SERVICE, 'kis-accessToken', token)
    await keytar.setPassword(KEYTAR_SERVICE, 'kis-tokenExpiresAt', String(expiresAt))
  } catch (e) {
    console.warn('[KisService] keytar 토큰 저장 실패 (세션 중 동작에는 영향 없음):', e)
  }
}

async function loadTokenFromVault(): Promise<boolean> {
  const token = await keytar.getPassword(KEYTAR_SERVICE, 'kis-accessToken')
  const expiresAtStr = await keytar.getPassword(KEYTAR_SERVICE, 'kis-tokenExpiresAt')
  if (!token || !expiresAtStr) return false

  const expiresAt = Number(expiresAtStr)
  const remainingSec = Math.floor((expiresAt - Date.now()) / 1000)
  if (remainingSec < 60) return false // 만료됨

  mainState.setKisAccessToken(token, remainingSec)
  scheduleTokenRefresh(remainingSec)
  return true
}

async function loadTokenFromVaultForFallback(): Promise<boolean> {
  const token = await keytar.getPassword(KEYTAR_SERVICE, 'kis-accessToken')
  const expiresAtStr = await keytar.getPassword(KEYTAR_SERVICE, 'kis-tokenExpiresAt')
  if (!token || !expiresAtStr) return false

  const expiresAt = Number(expiresAtStr)
  const remainingSec = Math.floor((expiresAt - Date.now()) / 1000)
  // fallback은 잔여 시간이 충분할 때만 허용 (10분 미만이면 거부)
  if (remainingSec < MIN_REMAINING_SEC_FOR_RESTORE) {
    console.warn(`[KisService] EGW00133 fallback 거부 — 저장 토큰 잔여 ${remainingSec}초, 최소 ${MIN_REMAINING_SEC_FOR_RESTORE}초 필요`)
    return false
  }

  mainState.setKisAccessToken(token, remainingSec)
  scheduleTokenRefresh(remainingSec)
  return true
}

export interface KisBalance {
  cash: number
  holdings: { ticker: string; qty: number; avgPrice: number; currentPrice: number }[]
}

export interface KisOrderResult {
  orderId: string
  executedPrice: number | null
  executedQty: number
}

export const KisService = {
  // ── Credential 관리 ──────────────────────────────────────────

  async saveCredentials(appKey: string, appSecret: string, accountNo: string): Promise<void> {
    await keytar.setPassword(KEYTAR_SERVICE, 'kis-appKey', appKey)
    await keytar.setPassword(KEYTAR_SERVICE, 'kis-appSecret', appSecret)
    await keytar.setPassword(KEYTAR_SERVICE, 'kis-accountNo', accountNo)
  },

  async hasCredentials(): Promise<boolean> {
    const [k, s, a] = await Promise.all([
      keytar.getPassword(KEYTAR_SERVICE, 'kis-appKey'),
      keytar.getPassword(KEYTAR_SERVICE, 'kis-appSecret'),
      keytar.getPassword(KEYTAR_SERVICE, 'kis-accountNo'),
    ])
    return !!(k && s && a)
  },

  async deleteCredentials(): Promise<void> {
    await Promise.all([
      keytar.deletePassword(KEYTAR_SERVICE, 'kis-appKey'),
      keytar.deletePassword(KEYTAR_SERVICE, 'kis-appSecret'),
      keytar.deletePassword(KEYTAR_SERVICE, 'kis-accountNo'),
      keytar.deletePassword(KEYTAR_SERVICE, 'kis-accessToken'),
      keytar.deletePassword(KEYTAR_SERVICE, 'kis-tokenExpiresAt'),
    ])
  },

  async loadSavedToken(): Promise<boolean> {
    return loadTokenFromVault()
  },

  // ── OAuth 토큰 ───────────────────────────────────────────────

  async issueToken(): Promise<void> {
    const appKey = await keytar.getPassword(KEYTAR_SERVICE, 'kis-appKey')
    const appSecret = await keytar.getPassword(KEYTAR_SERVICE, 'kis-appSecret')
    if (!appKey || !appSecret) throw new Error('KIS API 키가 등록되지 않았습니다.')

    try {
      const { data } = await kisHttp.post('/oauth2/tokenP', {
        grant_type: 'client_credentials',
        appkey: appKey,
        appsecret: appSecret,
      })

      mainState.setKisAccessToken(data.access_token, data.expires_in)
      await saveTokenToVault(data.access_token, data.expires_in)
      scheduleTokenRefresh(data.expires_in)
    } catch (e: any) {
      // EGW00133: KIS 토큰 발급 rate limit 초과 (분 단위 제한) — keytar 저장 토큰으로 복원 시도
      const errorCode = e?.response?.data?.error_code
      if (errorCode === 'EGW00133') {
        const restored = await loadTokenFromVaultForFallback()
        if (restored) {
          console.info('[KisService] EGW00133 — keytar 저장 토큰으로 복원 성공')
          return
        }
      }
      throw e
    }
  },

  async ensureToken(): Promise<void> {
    if (!mainState.isKisTokenValid()) {
      await KisService.issueToken()
    }
  },

  getTokenStatus(): { isValid: boolean; expiresAt: number | null } {
    return {
      isValid: mainState.isKisTokenValid(),
      expiresAt: mainState.kisTokenExpiresAt,
    }
  },

  // ── 잔고 조회 ────────────────────────────────────────────────

  async getBalance(): Promise<KisBalance> {
    await KisService.ensureToken()

    const appKey = await keytar.getPassword(KEYTAR_SERVICE, 'kis-appKey')
    const appSecret = await keytar.getPassword(KEYTAR_SERVICE, 'kis-appSecret')
    const accountNo = await keytar.getPassword(KEYTAR_SERVICE, 'kis-accountNo')
    const cano = accountNo!.slice(0, 8)
    const acntPrdtCd = accountNo!.slice(8) || '01'

    // 1. 해외주식 잔고 (보유종목)
    const { data } = await kisHttp.get('/uapi/overseas-stock/v1/trading/inquire-balance', {
      headers: buildKisHeaders(appKey!, appSecret!, 'VTTS3012R'),
      params: {
        CANO: cano,
        ACNT_PRDT_CD: acntPrdtCd,
        OVRS_EXCG_CD: 'NASD',
        TR_CRCY_CD: 'USD',
        CTX_AREA_FK200: '',
        CTX_AREA_NK200: '',
      },
    })

    // 2. 예수금 조회 — 모의투자 통합증거금 계좌는 별도 TR_ID 필요 (추후 구현)
    const cash = 0

    const holdings = (data.output1 ?? []).map((item: Record<string, string>) => ({
      ticker: item.ovrs_pdno,
      qty: Number(item.ovrs_cblc_qty),
      avgPrice: Number(item.pchs_avg_pric),
      currentPrice: Number(item.now_pric2),
    }))

    return { cash, holdings }
  },

  // ── 주문 실행 ────────────────────────────────────────────────

  async placeOrder(
    action: 'BUY' | 'SELL',
    ticker: string,
    qty: number,
  ): Promise<KisOrderResult> {
    await KisService.ensureToken()

    const appKey = await keytar.getPassword(KEYTAR_SERVICE, 'kis-appKey')
    const appSecret = await keytar.getPassword(KEYTAR_SERVICE, 'kis-appSecret')
    const accountNo = await keytar.getPassword(KEYTAR_SERVICE, 'kis-accountNo')

    // 모의투자 TR_ID: 매수 VTTT1002U / 매도 VTTT1006U
    const trId = action === 'BUY' ? 'VTTT1002U' : 'VTTT1006U'

    const { data } = await kisHttp.post(
      '/uapi/overseas-stock/v1/trading/order',
      {
        CANO: accountNo!.slice(0, 8),
        ACNT_PRDT_CD: accountNo!.slice(8) || '01',
        OVRS_EXCG_CD: 'NASD',
        PDNO: ticker,
        ORD_DVSN: '00', // 시장가
        ORD_QTY: String(qty),
        OVRS_ORD_UNPR: '0',
        ORD_SVR_DVSN_CD: '0',
      },
      { headers: buildKisHeaders(appKey!, appSecret!, trId) },
    )

    return {
      orderId: data.output?.ODNO ?? '',
      executedPrice: null, // 시장가는 즉시 체결가 미확정
      executedQty: qty,
    }
  },
}

function buildKisHeaders(appKey: string, appSecret: string, trId: string) {
  return {
    authorization: `Bearer ${mainState.kisAccessToken}`,
    appkey: appKey,
    appsecret: appSecret,
    tr_id: trId,
    'content-type': 'application/json; charset=utf-8',
  }
}

let refreshTimer: ReturnType<typeof setTimeout> | null = null

function scheduleTokenRefresh(expiresIn: number) {
  if (refreshTimer) clearTimeout(refreshTimer)
  // 만료 1시간 전 갱신
  const delay = Math.max((expiresIn - 3600) * 1000, 60_000)
  refreshTimer = setTimeout(async () => {
    try {
      await KisService.issueToken()
      pushToRenderer(IPC_CHANNELS.KIS_TOKEN_REFRESHED, KisService.getTokenStatus())
    } catch (e) {
      console.error('[KisService] 토큰 자동 갱신 실패:', e)
    }
  }, delay)
}
