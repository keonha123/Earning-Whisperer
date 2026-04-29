import axios from 'axios'
import keytar from 'keytar'
import { BrowserWindow } from 'electron'
import { mainState } from '../store/mainState'
import { IPC_CHANNELS } from '../../lib/ipcChannels'
import { kisLimiter } from './KisRateLimiter'

const KIS_BASE_URL_PAPER = 'https://openapivts.koreainvestment.com:29443'
const KIS_BASE_URL_REAL = 'https://openapi.koreainvestment.com:9443'
const KEYTAR_SERVICE = 'EarningWhisperer'

/** 모의(true) → 모의 URL, 실전(false) → 실전 URL */
export function getKisBaseUrl(isPaperTrading: boolean): string {
  return isPaperTrading ? KIS_BASE_URL_PAPER : KIS_BASE_URL_REAL
}

function tokenKey(isPaperTrading: boolean): string {
  return isPaperTrading ? 'kis-accessToken-paper' : 'kis-accessToken-real'
}

function expiryKey(isPaperTrading: boolean): string {
  return isPaperTrading ? 'kis-tokenExpiresAt-paper' : 'kis-tokenExpiresAt-real'
}

/**
 * KIS TR_ID 모드별 매핑.
 * 모의(paper)는 V로 시작 / 실전(real)은 T로 시작 — 첫 글자만 다르다.
 * baseURL/keytar는 분기되어 있어도 TR_ID가 모의용이면 실전 호출이 거부되므로 필수.
 */
const TR_IDS = {
  placeBuy: { paper: 'VTTT1002U', real: 'TTTT1002U' },
  placeSell: { paper: 'VTTT1006U', real: 'TTTT1006U' },
  balance: { paper: 'VTTS3012R', real: 'TTTS3012R' },
  psamount: { paper: 'VTTS3007R', real: 'TTTS3007R' },
} as const

function trId(key: keyof typeof TR_IDS): string {
  return mainState.isPaperTrading ? TR_IDS[key].paper : TR_IDS[key].real
}

const kisHttp = axios.create({
  baseURL: getKisBaseUrl(mainState.isPaperTrading),
  timeout: 10_000,
})

function pushToRenderer(channel: string, payload: unknown) {
  BrowserWindow.getAllWindows().forEach((win) => {
    if (!win.isDestroyed()) win.webContents.send(channel, payload)
  })
}

// EGW00133 fallback 시 복원 토큰 최소 잔여 시간
const MIN_REMAINING_SEC_FOR_RESTORE = 600

// 동시 호출 방지용 in-flight promise
let issueTokenInFlight: Promise<void> | null = null
let getBalanceInFlight: Promise<KisBalance> | null = null

/**
 * 모드 전환 시 in-flight axios 요청을 취소하기 위한 AbortController.
 * invalidateRuntime() 호출 시 abort + 새 controller로 교체된다.
 * issueToken은 abort 미적용 (cancel되면 후속 호출이 줄줄이 실패).
 */
let activeAbortController: AbortController = new AbortController()

function isAbortError(e: unknown): boolean {
  const code = (e as { code?: string })?.code
  const name = (e as { name?: string })?.name
  return code === 'ERR_CANCELED' || name === 'CanceledError' || name === 'AbortError'
}

async function saveTokenToVault(token: string, expiresIn: number): Promise<void> {
  try {
    const expiresAt = Date.now() + expiresIn * 1000
    const paper = mainState.isPaperTrading
    await keytar.setPassword(KEYTAR_SERVICE, tokenKey(paper), token)
    await keytar.setPassword(KEYTAR_SERVICE, expiryKey(paper), String(expiresAt))
  } catch (e) {
    console.warn('[KisService] keytar 토큰 저장 실패 (세션 중 동작에는 영향 없음):', e)
  }
}

async function loadTokenFromVault(): Promise<boolean> {
  const paper = mainState.isPaperTrading
  const token = await keytar.getPassword(KEYTAR_SERVICE, tokenKey(paper))
  const expiresAtStr = await keytar.getPassword(KEYTAR_SERVICE, expiryKey(paper))
  if (!token || !expiresAtStr) return false

  const expiresAt = Number(expiresAtStr)
  const remainingSec = Math.floor((expiresAt - Date.now()) / 1000)
  if (remainingSec < 60) return false // 만료됨

  mainState.setKisAccessToken(token, remainingSec)
  scheduleTokenRefresh(remainingSec)
  pushToRenderer(IPC_CHANNELS.KIS_TOKEN_REFRESHED, { isValid: true, expiresAt })
  return true
}

async function loadTokenFromVaultForFallback(): Promise<boolean> {
  const paper = mainState.isPaperTrading
  const token = await keytar.getPassword(KEYTAR_SERVICE, tokenKey(paper))
  const expiresAtStr = await keytar.getPassword(KEYTAR_SERVICE, expiryKey(paper))
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
  pushToRenderer(IPC_CHANNELS.KIS_TOKEN_REFRESHED, { isValid: true, expiresAt })
  return true
}

export interface KisBalance {
  orderableCash: number  // 즉시 주문가능 외화금액 (매매 판단용)
  totalCash: number      // 외화 총 보유금액 (포트폴리오 표시용, 없으면 orderableCash와 동일)
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
      // legacy 단일 키 + paper/real 양쪽 토큰 모두 정리
      keytar.deletePassword(KEYTAR_SERVICE, 'kis-accessToken'),
      keytar.deletePassword(KEYTAR_SERVICE, 'kis-tokenExpiresAt'),
      keytar.deletePassword(KEYTAR_SERVICE, 'kis-accessToken-paper'),
      keytar.deletePassword(KEYTAR_SERVICE, 'kis-tokenExpiresAt-paper'),
      keytar.deletePassword(KEYTAR_SERVICE, 'kis-accessToken-real'),
      keytar.deletePassword(KEYTAR_SERVICE, 'kis-tokenExpiresAt-real'),
    ])
  },

  async loadSavedToken(): Promise<boolean> {
    return loadTokenFromVault()
  },

  // ── OAuth 토큰 ───────────────────────────────────────────────

  async issueToken(): Promise<void> {
    // 동시 호출 방지 — in-flight 요청이 있으면 재사용
    if (issueTokenInFlight) return issueTokenInFlight

    issueTokenInFlight = (async () => {
      const appKey = await keytar.getPassword(KEYTAR_SERVICE, 'kis-appKey')
      const appSecret = await keytar.getPassword(KEYTAR_SERVICE, 'kis-appSecret')
      if (!appKey || !appSecret) throw new Error('KIS API 키가 등록되지 않았습니다.')

      try {
        const { data } = await kisHttp.post('/oauth2/tokenP', {
          grant_type: 'client_credentials',
          appkey: appKey,
          appsecret: appSecret,
        })

        console.info(`[KisService] 토큰 발급 성공 — expires_in: ${data.expires_in}초`)
        mainState.setKisAccessToken(data.access_token, data.expires_in)
        await saveTokenToVault(data.access_token, data.expires_in)
        scheduleTokenRefresh(data.expires_in)
      } catch (e: any) {
        // EGW00133: KIS 토큰 발급 1초당 1회 제한 초과
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
    })()

    try {
      await issueTokenInFlight
    } finally {
      issueTokenInFlight = null
    }
  },

  async ensureToken(): Promise<void> {
    if (!mainState.isKisTokenValid()) {
      console.info('[KisService] ensureToken — 토큰 없음/만료, 발급 시도')
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
    // 동시 호출 방지 — KIS API 초당 거래건수 초과 (EGW00201) 회피
    if (getBalanceInFlight) return getBalanceInFlight

    getBalanceInFlight = (async () => {
      return KisService._getBalanceImpl()
    })()

    try {
      return await getBalanceInFlight
    } finally {
      getBalanceInFlight = null
    }
  },

  async _getBalanceImpl(): Promise<KisBalance> {
    await KisService.ensureToken()

    const appKey = await keytar.getPassword(KEYTAR_SERVICE, 'kis-appKey')
    const appSecret = await keytar.getPassword(KEYTAR_SERVICE, 'kis-appSecret')
    const accountNo = await keytar.getPassword(KEYTAR_SERVICE, 'kis-accountNo')
    if (!appKey || !appSecret || !accountNo) throw new Error('KIS API 자격 증명이 등록되지 않았습니다.')
    const cano = accountNo.slice(0, 8)
    const acntPrdtCd = accountNo.slice(8) || '01'

    // 1. 해외주식 잔고 (보유종목)
    await kisLimiter.acquire('MEDIUM')
    const { data } = await kisHttp.get('/uapi/overseas-stock/v1/trading/inquire-balance', {
      headers: buildKisHeaders(appKey, appSecret, trId('balance')),
      signal: activeAbortController.signal,
      params: {
        CANO: cano,
        ACNT_PRDT_CD: acntPrdtCd,
        OVRS_EXCG_CD: 'NASD',
        TR_CRCY_CD: 'USD',
        CTX_AREA_FK200: '',
        CTX_AREA_NK200: '',
      },
    })

    // VTTS3012R rt_cd 실패 시 throw — holdings가 부정확하면 SELL 위험.
    if (data.rt_cd !== '0') {
      const msg = data.msg1 || data.msg_cd || '잔고 조회 실패'
      throw new Error(`KIS 잔고 조회 실패: ${msg}`)
    }

    // 2. 주문가능외화금액 조회 (VTTS3007R) — 실패 시 cash=0으로 계속 진행 (부분 fallback)
    let orderableCash = 0
    try {
      await kisLimiter.acquire('MEDIUM')
      const { data: psData } = await kisHttp.get('/uapi/overseas-stock/v1/trading/inquire-psamount', {
        headers: buildKisHeaders(appKey, appSecret, trId('psamount')),
        signal: activeAbortController.signal,
        params: {
          CANO: cano,
          ACNT_PRDT_CD: acntPrdtCd,
          OVRS_EXCG_CD: 'NASD',
          OVRS_ORD_UNPR: '0',
          ITEM_CD: 'AAPL',
          CTX_AREA_FK100: '',
          CTX_AREA_NK100: '',
        },
      })
      if (psData.rt_cd === '0') {
        orderableCash = Number(psData.output?.ord_psbl_frcr_amt ?? 0)
      } else {
        console.error('[KisService] VTTS3007R rt_cd 실패:', psData.msg1 || psData.msg_cd)
        // orderableCash는 0 유지
      }
    } catch (e: any) {
      // 모드 전환 abort는 graceful 처리 (orderableCash=0 유지)
      if (isAbortError(e)) {
        console.info('[KisService] VTTS3007R abort (모드 전환)')
      } else {
        console.error('[KisService] VTTS3007R 오류:', e?.response?.data?.message ?? e?.message)
      }
    }

    const holdings = (data.output1 ?? []).map((item: Record<string, string>) => ({
      ticker: item.ovrs_pdno,
      qty: Number(item.ovrs_cblc_qty),
      avgPrice: Number(item.pchs_avg_pric),
      currentPrice: Number(item.now_pric2),
    }))

    return { orderableCash, totalCash: orderableCash, holdings }
  },

  // ── 현재가 조회 ──────────────────────────────────────────────

  /**
   * 해외주식 현재가 조회 (HHDFS00000300). 수량 계산에 사용.
   * 실패 시 0을 반환 — 호출 측이 0 가드로 주문 진입을 막는다.
   */
  async getCurrentPrice(ticker: string): Promise<number> {
    await KisService.ensureToken()

    const appKey = await keytar.getPassword(KEYTAR_SERVICE, 'kis-appKey')
    const appSecret = await keytar.getPassword(KEYTAR_SERVICE, 'kis-appSecret')
    if (!appKey || !appSecret) throw new Error('KIS API 자격 증명이 등록되지 않았습니다.')

    try {
      await kisLimiter.acquire('LOW')
      const { data } = await kisHttp.get('/uapi/overseas-price/v1/quotations/price', {
        headers: buildKisHeaders(appKey, appSecret, 'HHDFS00000300'),
        signal: activeAbortController.signal,
        params: {
          AUTH: '',
          EXCD: 'NAS',
          SYMB: ticker,
        },
      })
      // rt_cd 실패 시 0 반환 (호출자의 0 가드와 일관)
      if (data.rt_cd !== '0') {
        console.error('[KisService] HHDFS00000300 rt_cd 실패:', data.msg1 || data.msg_cd)
        return 0
      }
      const last = Number(data.output?.last ?? 0)
      return Number.isFinite(last) && last > 0 ? last : 0
    } catch (e: any) {
      // 모드 전환 abort는 0 반환 (PricePoller 0 가드와 일관)
      if (isAbortError(e)) {
        console.info('[KisService] HHDFS00000300 abort (모드 전환)')
        return 0
      }
      console.error('[KisService] HHDFS00000300 현재가 조회 실패:', e?.response?.data?.message ?? e?.message)
      return 0
    }
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
    if (!appKey || !appSecret || !accountNo) throw new Error('KIS API 자격 증명이 등록되지 않았습니다.')

    // TR_ID는 모드별 분기 (paper: V접두, real: T접두)
    const orderTrId = trId(action === 'BUY' ? 'placeBuy' : 'placeSell')

    await kisLimiter.acquire('HIGH')
    const { data } = await kisHttp.post(
      '/uapi/overseas-stock/v1/trading/order',
      {
        CANO: accountNo.slice(0, 8),
        ACNT_PRDT_CD: accountNo.slice(8) || '01',
        OVRS_EXCG_CD: 'NASD',
        PDNO: ticker,
        ORD_DVSN: '00', // 시장가
        ORD_QTY: String(qty),
        OVRS_ORD_UNPR: '0',
        ORD_SVR_DVSN_CD: '0',
      },
      {
        headers: buildKisHeaders(appKey, appSecret, orderTrId),
        signal: activeAbortController.signal,
      },
    )

    // KIS는 HTTP 200으로 응답하면서 rt_cd='1' 등으로 비즈니스 실패를 보고한다.
    // 예: APBK0918 주문가능금액 부족, 시장 휴장, 종목 거래정지.
    // throw하면 TradeExecutor.execute의 catch에서 FAILED 콜백으로 처리된다.
    if (data.rt_cd !== '0') {
      const msg = data.msg1 || data.msg_cd || '주문 거부'
      throw new Error(`KIS 주문 거부: ${msg}`)
    }

    return {
      orderId: data.output?.ODNO ?? '',
      executedPrice: null, // 시장가는 즉시 체결가 미확정
      executedQty: qty,
    }
  },

  /**
   * 모의/실전 환경 전환 시 호출 — in-flight axios abort + 메모리 토큰 소거 +
   * 갱신 timer 취소 + axios baseURL 갱신.
   * axios instance 자체는 보존하고 defaults.baseURL만 바꿔 import 측 참조를 깨뜨리지 않는다.
   */
  invalidateRuntime(): void {
    // 옛 baseURL/토큰으로 떠 있던 in-flight 요청을 즉시 취소
    activeAbortController.abort()
    activeAbortController = new AbortController()

    mainState.setKisAccessToken(null)
    if (refreshTimer) {
      clearTimeout(refreshTimer)
      refreshTimer = null
    }
    kisHttp.defaults.baseURL = getKisBaseUrl(mainState.isPaperTrading)
  },
}

/**
 * 기존 단일 키(`kis-accessToken`, `kis-tokenExpiresAt`)에 토큰이 남아 있으면
 * paper 키로 1회 이전 후 legacy 키 삭제. 실패해도 무시.
 */
export async function migrateLegacyKeysIfNeeded(): Promise<void> {
  try {
    const legacyToken = await keytar.getPassword(KEYTAR_SERVICE, 'kis-accessToken')
    const legacyExpiry = await keytar.getPassword(KEYTAR_SERVICE, 'kis-tokenExpiresAt')
    if (!legacyToken || !legacyExpiry) return

    // 이미 paper 키가 있으면 충돌 회피 — legacy만 정리
    const existingPaperToken = await keytar.getPassword(KEYTAR_SERVICE, 'kis-accessToken-paper')
    if (!existingPaperToken) {
      await keytar.setPassword(KEYTAR_SERVICE, 'kis-accessToken-paper', legacyToken)
      await keytar.setPassword(KEYTAR_SERVICE, 'kis-tokenExpiresAt-paper', legacyExpiry)
    }
    await keytar.deletePassword(KEYTAR_SERVICE, 'kis-accessToken')
    await keytar.deletePassword(KEYTAR_SERVICE, 'kis-tokenExpiresAt')
    console.info('[KisService] legacy keytar 토큰 키 → paper 이전 완료')
  } catch (e) {
    console.warn('[KisService] legacy 키 마이그레이션 실패 (무시):', e)
  }
}

// 마이그레이션은 main/index.ts의 app.whenReady에서 await 호출 — 모듈 로드 시 자동 실행 X
// (자동 실행 시 restorePaperTradingFlag/issueToken과 race 발생)

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
      console.error('[KisService] 토큰 자동 갱신 실패:', e instanceof Error ? e.message : 'unknown error')
      scheduleTokenRefresh(360) // 6분 후 재시도
    }
  }, delay)
}
