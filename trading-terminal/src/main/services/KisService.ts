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

async function saveTokenToVault(token: string, expiresIn: number, issuedFor: boolean): Promise<void> {
  try {
    if (modeChangedSince(issuedFor)) return // 옛 모드 토큰을 새 모드 vault 키에 저장하지 않도록 차단
    const expiresAt = Date.now() + expiresIn * 1000
    await keytar.setPassword(KEYTAR_SERVICE, tokenKey(issuedFor), token)
    await keytar.setPassword(KEYTAR_SERVICE, expiryKey(issuedFor), String(expiresAt))
  } catch (e) {
    console.warn('[KisService] keytar 토큰 저장 실패 (세션 중 동작에는 영향 없음):', e)
  }
}

/**
 * 비동기 await 사이에 모드 전환이 발생했는지 검사.
 * 캡처된 모드와 현재 모드가 다르면 이 흐름의 결과가 새 모드 mainState 에 박히지 않도록 차단.
 */
function modeChangedSince(captured: boolean): boolean {
  return captured !== mainState.isPaperTrading
}

async function loadTokenFromVault(): Promise<boolean> {
  const paper = mainState.isPaperTrading
  const token = await keytar.getPassword(KEYTAR_SERVICE, tokenKey(paper))
  const expiresAtStr = await keytar.getPassword(KEYTAR_SERVICE, expiryKey(paper))
  if (!token || !expiresAtStr) return false
  if (modeChangedSince(paper)) return false

  const expiresAt = Number(expiresAtStr)
  const remainingSec = Math.floor((expiresAt - Date.now()) / 1000)
  if (remainingSec < 60) return false // 만료됨

  mainState.setKisAccessToken(token, remainingSec)
  scheduleTokenRefresh(remainingSec)
  pushToRenderer(IPC_CHANNELS.KIS_TOKEN_REFRESHED, { isValid: true, expiresAt })
  return true
}

/**
 * EGW00133 fallback 진입점. issueToken IIFE 가 시작 시 캡처한 모드를 인자로 받아
 * axios resolve 사이에 발생한 모드 전환에서도 옛 모드 토큰이 부활하지 않도록 한다.
 */
async function loadTokenFromVaultForFallback(issuedFor: boolean): Promise<boolean> {
  if (modeChangedSince(issuedFor)) {
    console.info('[KisService] EGW00133 fallback 거부 — 이슈 시작 후 모드가 전환됨')
    return false
  }
  const token = await keytar.getPassword(KEYTAR_SERVICE, tokenKey(issuedFor))
  const expiresAtStr = await keytar.getPassword(KEYTAR_SERVICE, expiryKey(issuedFor))
  if (!token || !expiresAtStr) return false
  if (modeChangedSince(issuedFor)) return false

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

    // IIFE 진입 시 모드 캡처. axios resolve 까지 이어지는 모든 await 사이에 invalidateRuntime 으로
     // 모드가 바뀌면 결과 mainState/vault 반영을 차단해 옛 모드 토큰이 새 모드에 박히는 사고 방지.
    const issuedFor = mainState.isPaperTrading
    issueTokenInFlight = (async () => {
      const appKey = await keytar.getPassword(KEYTAR_SERVICE, 'kis-appKey')
      const appSecret = await keytar.getPassword(KEYTAR_SERVICE, 'kis-appSecret')
      if (!appKey || !appSecret) throw new Error('KIS API 키가 등록되지 않았습니다.')
      if (modeChangedSince(issuedFor)) {
        console.info('[KisService] issueToken 중단 — 모드 전환 감지')
        return
      }

      try {
        const { data } = await kisHttp.post('/oauth2/tokenP', {
          grant_type: 'client_credentials',
          appkey: appKey,
          appsecret: appSecret,
        })

        if (modeChangedSince(issuedFor)) {
          console.info('[KisService] 토큰 발급 결과 폐기 — resolve 사이 모드 전환')
          return
        }

        console.info(`[KisService] 토큰 발급 성공 — expires_in: ${data.expires_in}초`)
        mainState.setKisAccessToken(data.access_token, data.expires_in)
        await saveTokenToVault(data.access_token, data.expires_in, issuedFor)
        scheduleTokenRefresh(data.expires_in)
      } catch (e: any) {
        // EGW00133: KIS 토큰 발급 1초당 1회 제한 초과
        const errorCode = e?.response?.data?.error_code
        if (errorCode === 'EGW00133') {
          const restored = await loadTokenFromVaultForFallback(issuedFor)
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
   * 갱신 timer 취소 + axios baseURL 갱신 + keytar 양 모드 토큰 삭제 + in-flight reset.
   *
   * keytar 양 모드 토큰을 삭제하는 이유: EGW00133 fallback 이 옛 모드 토큰을 부활시켜
   * 새 모드의 baseURL/TR_ID 와 모드 불일치 토큰으로 호출되는 사고를 차단한다.
   * (다음 호출에서 재발급되므로 운영 영향 없음.)
   *
   * in-flight Promise reset: 옛 모드의 issueToken/getBalance Promise 가 새 모드 호출자에게
   * 재사용되지 않도록 명시 null. 옛 await 자체는 abort signal 또는 mode-snapshot 가드로 종결.
   *
   * tokenRefreshAttempts reset: 새 모드에서 갱신은 처음부터 재시도되도록.
   *
   * ⚠️ 주문 진행 중 호출 금지 — KIS 측에 주문이 들어간 상태에서 axios 가 abort 되면
   * 응답을 받지 못해 콜백 누락이 발생한다. 호출자(settingsHandlers 등) 가
   * mainState.isOrderInProgress 를 사전 체크해야 하며, 본 함수는 방어선으로 한 번 더 검사한다.
   */
  invalidateRuntime(): void {
    if (mainState.isOrderInProgress) {
      console.warn('[KisService] invalidateRuntime 호출 무시 — 주문 진행 중')
      return
    }
    // 옛 baseURL/토큰으로 떠 있던 in-flight 요청을 즉시 취소
    activeAbortController.abort()
    activeAbortController = new AbortController()

    mainState.setKisAccessToken(null)
    if (refreshTimer) {
      clearTimeout(refreshTimer)
      refreshTimer = null
    }
    tokenRefreshAttempts = 0
    issueTokenInFlight = null
    getBalanceInFlight = null
    kisHttp.defaults.baseURL = getKisBaseUrl(mainState.isPaperTrading)

    // keytar 양 모드 토큰 삭제 — 옛 모드 fallback 부활 차단. 실패는 무시.
    void Promise.all([
      keytar.deletePassword(KEYTAR_SERVICE, tokenKey(true)),
      keytar.deletePassword(KEYTAR_SERVICE, expiryKey(true)),
      keytar.deletePassword(KEYTAR_SERVICE, tokenKey(false)),
      keytar.deletePassword(KEYTAR_SERVICE, expiryKey(false)),
    ]).catch((e) => {
      console.warn('[KisService] invalidateRuntime — keytar 토큰 삭제 실패 (무시):', e)
    })
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
let tokenRefreshAttempts = 0

/** 갱신 실패 시 백오프 지연(초) — 6m, 12m, 24m. */
const REFRESH_RETRY_DELAYS_SEC = [360, 720, 1440] as const
const MAX_REFRESH_RETRIES = REFRESH_RETRY_DELAYS_SEC.length

/**
 * 자동 갱신 1회 실행. 성공 시 카운터 reset, 실패 시 백오프 재시도 또는 포기.
 * scheduleTokenRefresh 와 분리해 재시도 delay 가 정상 갱신 delay 계산
 * (expiresIn - 1h, 최소 60s) 에 휘둘리지 않도록 한다.
 */
async function runRefreshOnce(): Promise<void> {
  try {
    await KisService.issueToken()
    tokenRefreshAttempts = 0
    pushToRenderer(IPC_CHANNELS.KIS_TOKEN_REFRESHED, KisService.getTokenStatus())
  } catch (e) {
    console.error('[KisService] 토큰 자동 갱신 실패:', e instanceof Error ? e.message : 'unknown error')
    tokenRefreshAttempts++
    if (tokenRefreshAttempts >= MAX_REFRESH_RETRIES) {
      console.error(`[KisService] 토큰 자동 갱신 ${MAX_REFRESH_RETRIES}회 연속 실패 — 자동 갱신 포기`)
      pushToRenderer(IPC_CHANNELS.KIS_TOKEN_REFRESH_FAILED, { attempts: tokenRefreshAttempts })
      tokenRefreshAttempts = 0
      return
    }
    const retrySec = REFRESH_RETRY_DELAYS_SEC[tokenRefreshAttempts - 1]
    console.info(`[KisService] 토큰 자동 갱신 재시도 ${tokenRefreshAttempts}/${MAX_REFRESH_RETRIES} — ${retrySec}초 후`)
    if (refreshTimer) clearTimeout(refreshTimer)
    refreshTimer = setTimeout(() => { void runRefreshOnce() }, retrySec * 1000)
  }
}

function scheduleTokenRefresh(expiresIn: number) {
  if (refreshTimer) clearTimeout(refreshTimer)
  // 만료 1시간 전 갱신, 최소 60s
  const delay = Math.max((expiresIn - 3600) * 1000, 60_000)
  refreshTimer = setTimeout(() => { void runRefreshOnce() }, delay)
}
