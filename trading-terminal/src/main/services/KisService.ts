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
 * KIS API 자격증명도 토큰과 동일한 모드별 slot 패턴 (`kis-{key}-{mode}`).
 * 모의/실전 환경에서 발급받은 키는 별도 키쌍이며 섞이면 안 된다 — paper 키로 실전 호출
 * 시 KIS 가 거부하고, 그 반대도 마찬가지. 사용자 입장에서는 양 환경 모두 등록 후
 * SettingsPage 의 모드 토글로 자유롭게 전환할 수 있어야 한다.
 */
function appKeySlot(isPaperTrading: boolean): string {
  return isPaperTrading ? 'kis-appKey-paper' : 'kis-appKey-real'
}

function appSecretSlot(isPaperTrading: boolean): string {
  return isPaperTrading ? 'kis-appSecret-paper' : 'kis-appSecret-real'
}

function accountNoSlot(isPaperTrading: boolean): string {
  return isPaperTrading ? 'kis-accountNo-paper' : 'kis-accountNo-real'
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
  inquireCcnl: { paper: 'VTTS3035R', real: 'TTTS3035R' }, // 미국주식 주문체결내역 조회
} as const

/**
 * 시장가 주문 후 체결조회 전 대기시간 — KIS 시스템에 즉시 체결이 반영되는 시간.
 * 테스트 환경에서는 0 으로 단축 (vitest 의 NODE_ENV='test') — fake timer 도입 회피.
 */
const ORDER_FILL_INQUIRE_WAIT_MS = process.env.NODE_ENV === 'test' ? 0 : 500

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

  /**
   * 모드별 slot 에 KIS API 키 저장.
   * isPaperTrading 인자는 저장 대상 모드(현재 입력 폼이 paper 키인지 real 키인지) 를 명시한다.
   * 호출 시점의 활성 모드와 저장 대상 모드가 일치할 때만 토큰 발급을 시도하고,
   * 다른 모드 키 등록 시는 token 발급을 건너뛴다 — 활성 모드와 무관한 백그라운드 등록을 허용.
   *
   * 옛 토큰 명시 무효화 (review hotfix #1):
   *   키가 "수정"되면 옛 appKey 로 발급된 keytar 의 access token 은 더 이상 유효하지 않다.
   *   EGW00133 (1초 1회 발급 제한) 시 loadTokenFromVaultForFallback 이 옛 토큰을 부활시키면
   *   새 키와 옛 토큰이 결합되어 KIS 가 거부 (정합성 깨짐).
   *   따라서 saveCredentials 는 항상 해당 모드의 token slot 을 정리.
   *   활성 모드와 일치하면 메모리/timer/in-flight 도 함께 reset.
   */
  async saveCredentials(
    appKey: string,
    appSecret: string,
    accountNo: string,
    isPaperTrading: boolean,
  ): Promise<void> {
    await keytar.setPassword(KEYTAR_SERVICE, appKeySlot(isPaperTrading), appKey)
    await keytar.setPassword(KEYTAR_SERVICE, appSecretSlot(isPaperTrading), appSecret)
    await keytar.setPassword(KEYTAR_SERVICE, accountNoSlot(isPaperTrading), accountNo)

    // 옛 키 기준의 access token 은 새 키와 결합 시 정합성이 깨지므로 항상 해당 모드 slot 정리.
    // 비활성 모드여도 다음 활성화 시 재발급되도록 (옛 토큰 부활 차단).
    await keytar.deletePassword(KEYTAR_SERVICE, tokenKey(isPaperTrading))
    await keytar.deletePassword(KEYTAR_SERVICE, expiryKey(isPaperTrading))

    // 활성 모드와 일치할 때만 메모리/timer/in-flight 를 reset — 비활성 모드 운영 영향 없음.
    if (isPaperTrading === mainState.isPaperTrading) {
      mainState.setKisAccessToken(null)
      if (refreshTimer) {
        clearTimeout(refreshTimer)
        refreshTimer = null
      }
      tokenRefreshAttempts = 0
      issueTokenInFlight = null
      getBalanceInFlight = null
    }
  },

  /**
   * 모드별 마스킹된 자격증명 조회 (A3).
   * UI 카드에 등록 여부 + 일부 식별 가능한 일부 prefix/suffix 만 표시하기 위함.
   *
   * 보안:
   *   - **appSecret 은 절대 응답에 포함하지 않는다.** 사용자가 다시 보고 싶다면 재등록(수정) 흐름으로만.
   *   - appKey/accountNo 도 평문이 아니라 마스킹 형식으로 노출 (prefix + 마스크 + suffix).
   *
   * 마스킹 규칙:
   *   - appKey: 16자 이상 → `prefix4 + **** + suffix4`, 그 외(8자 미만 포함) → `****` (전체 마스킹)
   *   - accountNo: 8자 이상 → `prefix4 + **** + suffix2`, 그 외 → `****` (전체 마스킹)
   *
   * 모드별 키 미등록(appKey/accountNo 어느 하나라도 누락)이면 해당 모드는 `null` 반환.
   * (appSecret 등록 여부는 반환에 영향 없음 — 표시 페이로드에 포함되지 않으므로.)
   */
  async getMaskedCredentials(): Promise<{
    paper: { appKeyMasked: string; accountNoMasked: string } | null
    real: { appKeyMasked: string; accountNoMasked: string } | null
  }> {
    const [pk, pa, rk, ra] = await Promise.all([
      keytar.getPassword(KEYTAR_SERVICE, appKeySlot(true)),
      keytar.getPassword(KEYTAR_SERVICE, accountNoSlot(true)),
      keytar.getPassword(KEYTAR_SERVICE, appKeySlot(false)),
      keytar.getPassword(KEYTAR_SERVICE, accountNoSlot(false)),
    ])
    return {
      paper:
        pk && pa
          ? { appKeyMasked: maskAppKey(pk), accountNoMasked: maskAccountNo(pa) }
          : null,
      real:
        rk && ra
          ? { appKeyMasked: maskAppKey(rk), accountNoMasked: maskAccountNo(ra) }
          : null,
    }
  },

  /**
   * 두 모드 각각의 자격증명 등록 여부 반환.
   * UI 가 paper/real 카드를 분리해 표시하려면 boolean 단일 값으로는 부족하므로
   * 객체 응답으로 전환 — A3 의 카드 분리 UI 에 필요.
   */
  async hasCredentials(): Promise<{ paper: boolean; real: boolean }> {
    const [pk, ps, pa, rk, rs, ra] = await Promise.all([
      keytar.getPassword(KEYTAR_SERVICE, appKeySlot(true)),
      keytar.getPassword(KEYTAR_SERVICE, appSecretSlot(true)),
      keytar.getPassword(KEYTAR_SERVICE, accountNoSlot(true)),
      keytar.getPassword(KEYTAR_SERVICE, appKeySlot(false)),
      keytar.getPassword(KEYTAR_SERVICE, appSecretSlot(false)),
      keytar.getPassword(KEYTAR_SERVICE, accountNoSlot(false)),
    ])
    return {
      paper: !!(pk && ps && pa),
      real: !!(rk && rs && ra),
    }
  },

  /**
   * 특정 모드의 자격증명 + 토큰 slot 일괄 삭제.
   * 다른 모드의 키/토큰은 보존 — 사용자가 한쪽만 삭제하고 다른 쪽은 계속 사용 가능.
   *
   * 활성 모드 (= mainState.isPaperTrading 과 일치하는 모드) 키 삭제 시:
   *  - 메모리 access token clear (재사용 차단)
   *  - 자동 갱신 timer cancel (지운 키로 갱신 시도 방지)
   *  - in-flight Promise reset (옛 흐름이 새 요청에 재사용되지 않도록)
   *
   * 비활성 모드 키 삭제 시: 메모리/timer/in-flight 손대지 않음 — 활성 모드 운영에 영향 없음.
   */
  async deleteCredentials(isPaperTrading: boolean): Promise<void> {
    await Promise.all([
      keytar.deletePassword(KEYTAR_SERVICE, appKeySlot(isPaperTrading)),
      keytar.deletePassword(KEYTAR_SERVICE, appSecretSlot(isPaperTrading)),
      keytar.deletePassword(KEYTAR_SERVICE, accountNoSlot(isPaperTrading)),
      keytar.deletePassword(KEYTAR_SERVICE, tokenKey(isPaperTrading)),
      keytar.deletePassword(KEYTAR_SERVICE, expiryKey(isPaperTrading)),
    ])

    if (isPaperTrading === mainState.isPaperTrading) {
      mainState.setKisAccessToken(null)
      if (refreshTimer) {
        clearTimeout(refreshTimer)
        refreshTimer = null
      }
      tokenRefreshAttempts = 0
      issueTokenInFlight = null
      getBalanceInFlight = null
    }
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
      const appKey = await keytar.getPassword(KEYTAR_SERVICE, appKeySlot(issuedFor))
      const appSecret = await keytar.getPassword(KEYTAR_SERVICE, appSecretSlot(issuedFor))
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

    const paper = mainState.isPaperTrading
    const appKey = await keytar.getPassword(KEYTAR_SERVICE, appKeySlot(paper))
    const appSecret = await keytar.getPassword(KEYTAR_SERVICE, appSecretSlot(paper))
    const accountNo = await keytar.getPassword(KEYTAR_SERVICE, accountNoSlot(paper))
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

    const paper = mainState.isPaperTrading
    const appKey = await keytar.getPassword(KEYTAR_SERVICE, appKeySlot(paper))
    const appSecret = await keytar.getPassword(KEYTAR_SERVICE, appSecretSlot(paper))
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

    const paper = mainState.isPaperTrading
    const appKey = await keytar.getPassword(KEYTAR_SERVICE, appKeySlot(paper))
    const appSecret = await keytar.getPassword(KEYTAR_SERVICE, appSecretSlot(paper))
    const accountNo = await keytar.getPassword(KEYTAR_SERVICE, accountNoSlot(paper))
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

    const orderId = data.output?.ODNO ?? ''

    // 시장가 주문 후 짧은 대기 → 체결조회로 실제 executedQty/executedPrice 채움.
    // 체결조회 실패 시 fallback: executedQty=qty 가정(기존 동작) — 정확성은 떨어지지만 회귀는 없음.
    // 후속 portfolio sync 가 KIS 잔고 재조회로 보정한다.
    if (!orderId) {
      console.warn('[KisService] ODNO 미반환 — 체결조회 skip, fallback 사용')
      return { orderId: '', executedPrice: null, executedQty: qty }
    }

    await sleep(ORDER_FILL_INQUIRE_WAIT_MS)
    const fill = await inquireOrderFill(appKey, appSecret, accountNo, ticker, orderId)
    if (fill === null) {
      console.warn(`[KisService] 체결조회 실패 — fallback (qty=${qty} 가정) orderId=${orderId}`)
      return { orderId, executedPrice: null, executedQty: qty }
    }
    return {
      orderId,
      executedPrice: fill.executedQty > 0 ? fill.avgPrice : null,
      executedQty: fill.executedQty,
    }
  },

  /**
   * 모의/실전 환경 전환 시 호출 — in-flight axios abort + 메모리 토큰 소거 +
   * 갱신 timer 취소 + axios baseURL 갱신 + in-flight reset.
   *
   * keytar 토큰은 보존한다 — 옛 모드 토큰을 다음 모드 활성화 시 재사용 가능하도록.
   * 모드 불일치 fallback 부활 위험은 PR3 의 mode-snapshot 가드 (`modeChangedSince`) 가 차단한다:
   * 옛 모드 axios resolve 가 새 모드 mainState 에 박히지 않으며, EGW00133 fallback 도
   * 새 모드 활성화 후엔 옛 모드 vault 토큰을 거부한다. 따라서 토큰을 keytar 에서 지울 필요가 없다.
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
  },
}

/**
 * 단일 slot 키(legacy)를 모드별 slot 으로 이전.
 * 1) 토큰 (kis-accessToken / kis-tokenExpiresAt) → paper slot (legacy 가 모의 모드에서만 사용됐던 시점)
 * 2) 자격증명 (kis-appKey / kis-appSecret / kis-accountNo) → 현재 영속화된 모드 slot
 *
 * idempotent — 모드별 slot 에 이미 값이 있으면 충돌 회피하고 legacy 키만 정리.
 * 실패해도 무시 (앱 동작에는 영향 없음, 로그만 남김).
 *
 * 자격증명 이전 시 모드 결정: kis-isPaperTrading flag 가 '0'(real) 이면 real, 그 외(미지정/'1') 는 paper.
 * (legacy 단일 키 사용 시기에는 paper 가 디폴트였고, 사용자가 실전 전환했다면 flag 도 함께 설정됨.)
 */
export async function migrateLegacyKeysIfNeeded(): Promise<void> {
  try {
    // 토큰 이전 — legacy 시기 토큰은 페이퍼 모드 사용분으로 간주
    const legacyToken = await keytar.getPassword(KEYTAR_SERVICE, 'kis-accessToken')
    const legacyExpiry = await keytar.getPassword(KEYTAR_SERVICE, 'kis-tokenExpiresAt')
    if (legacyToken && legacyExpiry) {
      const existingPaperToken = await keytar.getPassword(KEYTAR_SERVICE, 'kis-accessToken-paper')
      if (!existingPaperToken) {
        await keytar.setPassword(KEYTAR_SERVICE, 'kis-accessToken-paper', legacyToken)
        await keytar.setPassword(KEYTAR_SERVICE, 'kis-tokenExpiresAt-paper', legacyExpiry)
      }
      await keytar.deletePassword(KEYTAR_SERVICE, 'kis-accessToken')
      await keytar.deletePassword(KEYTAR_SERVICE, 'kis-tokenExpiresAt')
      console.info('[KisService] legacy keytar 토큰 키 → paper 이전 완료')
    }

    // 자격증명 이전 — legacy 단일 slot 의 키는 영속화된 paper/real flag 에 따라 적절한 모드 slot 으로
    const legacyAppKey = await keytar.getPassword(KEYTAR_SERVICE, 'kis-appKey')
    const legacyAppSecret = await keytar.getPassword(KEYTAR_SERVICE, 'kis-appSecret')
    const legacyAccountNo = await keytar.getPassword(KEYTAR_SERVICE, 'kis-accountNo')
    if (legacyAppKey || legacyAppSecret || legacyAccountNo) {
      const paperFlag = await keytar.getPassword(KEYTAR_SERVICE, 'kis-isPaperTrading')
      // '0' → real, 그 외(미지정 포함) → paper (legacy 디폴트)
      const targetIsPaper = paperFlag !== '0'

      // 모드별 slot 에 이미 값이 있으면 그대로 두고 legacy 만 정리 (idempotent)
      const existingAppKey = await keytar.getPassword(KEYTAR_SERVICE, appKeySlot(targetIsPaper))
      const existingAppSecret = await keytar.getPassword(KEYTAR_SERVICE, appSecretSlot(targetIsPaper))
      const existingAccountNo = await keytar.getPassword(KEYTAR_SERVICE, accountNoSlot(targetIsPaper))

      if (legacyAppKey && !existingAppKey) {
        await keytar.setPassword(KEYTAR_SERVICE, appKeySlot(targetIsPaper), legacyAppKey)
      }
      if (legacyAppSecret && !existingAppSecret) {
        await keytar.setPassword(KEYTAR_SERVICE, appSecretSlot(targetIsPaper), legacyAppSecret)
      }
      if (legacyAccountNo && !existingAccountNo) {
        await keytar.setPassword(KEYTAR_SERVICE, accountNoSlot(targetIsPaper), legacyAccountNo)
      }

      await keytar.deletePassword(KEYTAR_SERVICE, 'kis-appKey')
      await keytar.deletePassword(KEYTAR_SERVICE, 'kis-appSecret')
      await keytar.deletePassword(KEYTAR_SERVICE, 'kis-accountNo')
      console.info(
        `[KisService] legacy keytar 자격증명 키 → ${targetIsPaper ? 'paper' : 'real'} 이전 완료`,
      )
    }
  } catch (e) {
    console.warn('[KisService] legacy 키 마이그레이션 실패 (무시):', e)
  }
}

// 마이그레이션은 main/index.ts의 app.whenReady에서 await 호출 — 모듈 로드 시 자동 실행 X
// (자동 실행 시 restorePaperTradingFlag/issueToken과 race 발생)

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms))
}

/**
 * AppKey 마스킹.
 * 16자 이상이면 prefix 4 + suffix 4 노출 (예: `PSDK****ABCD`).
 * 그 외(8자 미만 포함, 8~15자도 prefix/suffix 가 겹쳐 정보 노출 — 보수적으로 전체 마스킹)
 *
 * 호출 측은 keytar 에서 키를 읽은 직후 이 함수를 통해서만 노출한다 — 평문이
 * IPC 페이로드/렌더러 메모리에 박히는 것을 차단.
 */
export function maskAppKey(appKey: string): string {
  if (appKey.length >= 16) {
    return `${appKey.slice(0, 4)}****${appKey.slice(-4)}`
  }
  return '****'
}

/**
 * 계좌번호 마스킹.
 * 8자 이상이면 prefix 4 + suffix 2 노출 (예: `5012****34`), 그 외는 전체 마스킹.
 */
export function maskAccountNo(accountNo: string): string {
  if (accountNo.length >= 8) {
    return `${accountNo.slice(0, 4)}****${accountNo.slice(-2)}`
  }
  return '****'
}

/**
 * KIS 미국주식 주문체결내역 조회 (TR_ID inquireCcnl).
 * placeOrder 직후 호출하여 ODNO 매칭 row 의 실제 체결수량/평균가를 가져온다.
 *
 * 반환값:
 *   - { executedQty, avgPrice }: 정상 조회 (미체결이면 executedQty=0)
 *   - null: 조회 실패 (rt_cd 비정상, 네트워크 오류, ODNO 매칭 row 없음 등) → 호출 측 fallback
 *
 * 응답 필드명은 KIS 명세에 따라 다를 수 있으며 (실제 운영 시 검증 필요),
 * 일반적인 KIS 컨벤션 (`output1` 배열 + `odno`/`tot_ccld_qty`/`avg_prvs`) 을 가정한다.
 */
async function inquireOrderFill(
  appKey: string,
  appSecret: string,
  accountNo: string,
  ticker: string,
  orderId: string,
): Promise<{ executedQty: number; avgPrice: number | null } | null> {
  try {
    const today = new Date()
    const yyyy = today.getUTCFullYear()
    const mm = String(today.getUTCMonth() + 1).padStart(2, '0')
    const dd = String(today.getUTCDate()).padStart(2, '0')
    const yyyymmdd = `${yyyy}${mm}${dd}`

    await kisLimiter.acquire('HIGH')
    const { data } = await kisHttp.get(
      '/uapi/overseas-stock/v1/trading/inquire-ccnl',
      {
        headers: buildKisHeaders(appKey, appSecret, trId('inquireCcnl')),
        signal: activeAbortController.signal,
        params: {
          CANO: accountNo.slice(0, 8),
          ACNT_PRDT_CD: accountNo.slice(8) || '01',
          PDNO: ticker,
          ORD_STRT_DT: yyyymmdd,
          ORD_END_DT: yyyymmdd,
          SLL_BUY_DVSN: '00',     // 전체
          CCLD_NCCS_DVSN: '00',   // 전체
          OVRS_EXCG_CD: 'NASD',
          SORT_SQN: 'DS',
          ORD_DT: '',
          ORD_GNO_BRNO: '',
          ODNO: orderId,
          CTX_AREA_NK200: '',
          CTX_AREA_FK200: '',
        },
      },
    )

    if (data.rt_cd !== '0') {
      console.warn('[KisService] inquireCcnl rt_cd 실패:', data.msg1 || data.msg_cd)
      return null
    }

    const rows: Array<Record<string, string>> = Array.isArray(data.output) ? data.output
      : Array.isArray(data.output1) ? data.output1
      : []
    const row = rows.find((r) => r.odno === orderId || r.ODNO === orderId)
    if (!row) {
      console.warn(`[KisService] inquireCcnl 응답에 ODNO=${orderId} 매칭 row 없음`)
      return null
    }

    const executedQty = Number(row.tot_ccld_qty ?? row.ft_ccld_qty ?? 0)
    const avgPriceRaw = Number(row.avg_prvs ?? row.ft_ccld_unpr3 ?? 0)
    if (!Number.isFinite(executedQty) || executedQty < 0) return null

    return {
      executedQty,
      avgPrice: avgPriceRaw > 0 ? avgPriceRaw : null,
    }
  } catch (e: unknown) {
    if (isAbortError(e)) {
      console.info('[KisService] inquireCcnl abort (모드 전환)')
      return null
    }
    const msg = e instanceof Error ? e.message : 'unknown'
    console.warn('[KisService] inquireCcnl 호출 실패:', msg)
    return null
  }
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
