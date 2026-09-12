import axios from 'axios'
import { mainState } from '../store/mainState'
import type { StockDetailResponsePayload } from '../../lib/types/stockDetail'
import type { Sp500Stock, StockPriceEntry } from '../../lib/types/stockList'
import type { TradeSignal } from './TradeExecutor'
import { axiosErrorToIpcError } from '../../lib/types/ipcError'

// Phase 5: StockDetailResponsePayload 정의를 src/lib/types/stockDetail.ts 로 이동.
// 본 모듈의 외부 import 호환을 위해 type re-export.
export type { StockDetailResponsePayload }

const BASE_URL = process.env.BACKEND_URL ?? 'http://localhost:8082'

const http = axios.create({ baseURL: BASE_URL, timeout: 10_000 })

const REFRESH_PATH = '/api/v1/auth/refresh'
const AUTH_PATH_PREFIX = '/api/v1/auth'
const REFRESH_COOKIE_NAME = 'refresh_token'

/**
 * 응답의 Set-Cookie 에서 refresh_token 을 꺼내 보관한다.
 *
 * 백엔드는 이 토큰을 HttpOnly + SameSite=Strict 쿠키로만 주고받는다 (보안 검토
 * 결정). Node 의 axios 는 쿠키 저장소가 없어서 지금까지 이 쿠키를 그냥 버렸고,
 * 그래서 액세스 토큰이 15분 뒤 만료되면 갱신할 방법이 없어 로그인 화면으로
 * 튕겼다. 여기서 브라우저가 할 일을 대신한다 — 계약은 그대로 둔다.
 *
 * 쿠키가 하나(refresh_token)뿐이고 경로도 하나(/api/v1/auth)뿐이라 완전한
 * 쿠키 저장소는 필요 없다. 값만 꺼내 두고 갱신 요청에 다시 실어 보낸다.
 */
function captureRefreshCookie(headers: unknown): boolean {
  const setCookie = (headers as { 'set-cookie'?: string[] } | undefined)?.['set-cookie']
  if (!Array.isArray(setCookie)) return false
  for (const raw of setCookie) {
    const [pair, ...attrs] = raw.split(';')
    const eq = pair.indexOf('=')
    if (eq < 0) continue
    if (pair.slice(0, eq).trim() !== REFRESH_COOKIE_NAME) continue

    const value = pair.slice(eq + 1).trim()
    const lowered = attrs.map((a) => a.trim().toLowerCase())
    // 브라우저와 같은 규칙: Secure 쿠키는 보안 채널에서만 저장·전송한다. 이걸 무시하면
    // 7일짜리 자격증명이 평문 HTTP 로 반복해서 나간다.
    if (lowered.includes('secure') && !isSecureBaseUrl()) {
      console.warn('[Backend] Secure refresh 쿠키를 비보안 연결에서 받아 보관하지 않는다.')
      return false
    }
    // 서버가 쿠키를 지우는 방식: 빈 값 또는 Max-Age=0 / 과거 Expires.
    // 값만 보고 판단하면 `refresh_token=deleted; Max-Age=0` 같은 형식을 저장해 버린다.
    const expired =
      value === '' ||
      lowered.some((a) => a === 'max-age=0' || a.startsWith('max-age=-'))
    mainState.setBackendRefreshToken(expired ? null : value)
    return !expired
  }
  return false
}

/** BACKEND_URL 이 보안 채널인지. 로컬 개발(localhost)은 평문이어도 위험하지 않다. */
function isSecureBaseUrl(): boolean {
  try {
    const url = new URL(BASE_URL)
    return url.protocol === 'https:' || url.hostname === 'localhost' || url.hostname === '127.0.0.1'
  } catch {
    return false
  }
}

http.interceptors.request.use((config) => {
  const token = mainState.backendToken
  if (token) config.headers.Authorization = `Bearer ${token}`
  // 백엔드가 쿠키 path 를 /api/v1/auth 로 잡아 두었다. 그 경로에만 실어 보낸다 —
  // 다른 API 요청에까지 붙이면 브라우저가 하지 않을 일을 하는 것이 된다.
  // startsWith 만 쓰면 /api/v1/authorize 같은 경로에도 붙는다 (RFC 6265 path-match 는
  // 다음 문자가 '/' 여야 한다).
  const url = config.url ?? ''
  const onAuthPath = url === AUTH_PATH_PREFIX || url.startsWith(`${AUTH_PATH_PREFIX}/`)
  const refreshToken = mainState.backendRefreshToken
  if (refreshToken && onAuthPath) {
    config.headers.Cookie = `${REFRESH_COOKIE_NAME}=${refreshToken}`
  } else {
    // 재시도되는 config 는 같은 객체다. 지우지 않으면 이미 폐기된 토큰이 그대로 남아
    // 다시 전송되고, 서버는 그것을 재사용으로 판단해 family 전체를 차단한다.
    delete config.headers.Cookie
  }
  return config
})

/**
 * 진행 중인 갱신 요청. 만료 순간 폴러 여러 개가 동시에 401 을 받는데, 각자
 * 갱신을 부르면 백엔드의 refresh token rotation 이 재사용으로 판단해 family
 * 전체를 차단한다 — 갱신하려다 오히려 강제 로그아웃된다. 하나로 묶는다.
 */
let refreshInFlight: Promise<void> | null = null

/** 갱신이 최종 실패했을 때 호출된다 (세션 정리 담당자가 등록). */
let onRefreshFailed: (() => void) | null = null

export function setRefreshFailedHandler(handler: (() => void) | null): void {
  onRefreshFailed = handler
  sessionEnded = false
}

/**
 * 동시에 터진 401 들이 함께 갱신에 실패하면 각자 이 경로로 들어온다. 정리를 여러 번
 * 태우면 렌더러에도 로그아웃 이벤트가 중복으로 나간다. 한 번만 돌게 한다.
 */
let sessionEnded = false

function endSession(): void {
  mainState.setBackendRefreshToken(null)
  mainState.setBackendToken(null)
  if (sessionEnded) return
  sessionEnded = true
  onRefreshFailed?.()
}

/** 갱신이 최종 실패했다는 뜻 — 세션을 정리해야 한다. 일시적 실패와 구분한다. */
class SessionEndedError extends Error {}

async function refreshAccessToken(): Promise<void> {
  if (refreshInFlight) return refreshInFlight
  refreshInFlight = (async () => {
    try {
      const response = await http.post(REFRESH_PATH, null, { __isRefresh: true } as never)
      const token = (response.data as { access_token?: string } | undefined)?.access_token
      if (!token) throw new SessionEndedError('갱신 응답에 access_token 이 없습니다.')
      // 서버는 갱신할 때마다 refresh token 을 회전시킨다. 새 쿠키를 못 받았다면
      // (프록시가 헤더를 떨궜거나 응답 경로가 바뀐 경우) 보관 중인 값은 이미 사용된
      // 토큰이다. 그대로 두면 다음 갱신에서 재사용으로 판정되어 family 전체가 차단된다.
      // 여기서 버리고 재로그인을 요구하는 편이 낫다.
      if (!mainState.backendRefreshToken) {
        throw new SessionEndedError('갱신 응답에서 새 refresh 쿠키를 받지 못했습니다.')
      }
      mainState.setBackendToken(token)
    } finally {
      refreshInFlight = null
    }
  })()
  return refreshInFlight
}

/**
 * 갱신 실패가 "세션이 끝났다" 인지 "잠깐 안 됐다" 인지 가른다.
 *
 * 401 은 RT 가 무효라는 뜻이니 최종 실패다. 429 는 같은 family 가 동시에 갱신을
 * 시도했다는 뜻이라 재시도하면 되는 일시적 상태이고, 5xx·네트워크 오류도 마찬가지다.
 * 전부 최종 실패로 묶으면 백엔드가 잠깐 흔들릴 때마다 강제 로그아웃된다.
 */
function isSessionEnded(error: unknown): boolean {
  if (error instanceof SessionEndedError) return true
  const status = (error as { response?: { status?: number } })?.response?.status
  return status === 401
}

// 모든 axios error 를 IpcError 로 변환해 호출 측 (IPC handler) 가 일관된 형식으로 받도록 한다.
// BackendClient 외 axios 인스턴스 (KisService 등) 는 적용 대상 외.
http.interceptors.response.use(
  (response) => {
    captureRefreshCookie(response.headers)
    return response
  },
  async (error: unknown) => {
    const err = error as {
      response?: { status?: number }
      config?: { url?: string; __isRefresh?: boolean; __retried?: boolean }
    }
    const config = err.config

    // 401 이면 액세스 토큰을 한 번 갱신하고 원래 요청을 재시도한다.
    // 갱신 요청 자체와 이미 재시도한 요청은 제외한다 — 아니면 무한 재귀가 된다.
    // 보관한 refresh token 이 없으면 (로그인 전) 갱신할 것도 없다.
    if (
      err.response?.status === 401 &&
      config &&
      !config.__isRefresh &&
      !config.__retried &&
      mainState.backendRefreshToken
    ) {
      let refreshed = false
      try {
        await refreshAccessToken()
        refreshed = true
      } catch (refreshError) {
        // 세션이 정말 끝났을 때만(RT 무효) 정리한다. 토큰을 버리고 등록된 절차를
        // 태우지 않으면 메인 프로세스의 폴러들이 계속 돌며 끝없이 401 을 만들어 낸다.
        // 반대로 일시적 실패까지 여기로 묶으면 백엔드가 잠깐 흔들릴 때마다 로그아웃된다.
        if (isSessionEnded(refreshError)) {
          endSession()
        }
      }

      if (refreshed) {
        // 재시도는 try 밖에서 한다. 안에 두면 재시도가 500 이나 네트워크 오류로 실패했을
        // 때 그것을 "갱신 실패" 로 오인해, 멀쩡한 refresh token 을 버리고 로그아웃시킨다.
        config.__retried = true
        return await http.request(config)
      }
    }
    return Promise.reject(axiosErrorToIpcError(error))
  },
)

/**
 * Backend Contract 7.7 의 시장 지수 응답 (snake_case).
 * 5종 (SPX/NDX/VIX/DXY/10Y) 배열, 빈 캐시 시 200 [].
 */
export interface MarketIndexPayload {
  symbol: string
  price: number
  change_percent: number
  trend: 'up' | 'down' | 'neutral'
  format: 'index' | 'percent'
  timestamp: number
}

export interface CallbackPayload {
  status: 'EXECUTED' | 'FAILED'
  broker_order_id: string | null
  executed_price: number | null
  executed_qty: number
  error_message: string | null
}

export interface ManualTradePayload {
  ticker: string
  side: 'BUY' | 'SELL'
  order_type: 'MARKET' | 'LIMIT'
  order_qty: number
  price: number
  executed_qty: number
  executed_price: number | null
  broker_order_id: string | null
  status: 'EXECUTED' | 'PENDING' | 'FAILED'
  error_message: string | null
}

export interface PortfolioSyncPayload {
  cash_balance: number
  positions: { ticker: string; quantity: number; avg_price: number }[]
}

export interface UserSettings {
  trading_mode: 'MANUAL' | 'SEMI_AUTO' | 'AUTO_PILOT'
  max_buy_ratio: number
  max_holding_ratio: number
  cooldown_minutes: number
  ai_score_threshold: number
}

/**
 * 관심종목 응답 — 백엔드 record `WatchlistItemResponse(ticker, companyName, sector)`.
 * Spring 기본 직렬화는 camelCase 이므로 Electron 측 타입도 camelCase 그대로 사용.
 */
export interface WatchlistItem {
  ticker: string
  companyName: string
  sector: string
}

// StockDetailResponsePayload 는 src/lib/types/stockDetail.ts 단일 정의 — 위에서 re-export.

/** 시연 재생 시작 결과. 409(이미 재생 중)를 예외가 아니라 값으로 전달한다. */
/** 콜 참가자 명부 1건. renderer 의 SpeakerProfile 과 동일 shape. */
export interface SpeakerProfilePayload {
  matchKey: string
  name: string
  title: string
  affiliation: string
  kind: 'MANAGEMENT' | 'ANALYST'
}

export type DemoStartResult =
  | {
      ok: true
      callId: string
      segmentCount: number
      intervalMs: number
      /**
       * 근거 저장소가 비었을 때만 채워진다. 재생은 그대로 시작된다.
       * 이게 없으면 근거를 안 넣은 채 시연해도 화면에는 "근거 부족" 만 뜨고,
       * 시연 중에 그것이 정상 판정인지 설정 실수인지 알 방법이 없다.
       */
      evidenceWarning?: string
    }
  | { ok: false; reason: 'ALREADY_RUNNING' | 'FAILED'; message: string }

export const BackendClient = {
  async login(email: string, password: string): Promise<{ token: string; user: unknown }> {
    const { data } = await http.post('/api/v1/auth/login', { email, password })
    return { token: data.access_token, user: data }
  },

  /**
   * OAuth (Google / Kakao) 콜백 교환.
   * 백엔드: POST /api/v1/auth/oauth/callback — body { code, redirect_uri (snake_case), provider }
   *   응답 body: { access_token, refresh_token } + Set-Cookie(refresh_token; HttpOnly).
   * Electron 은 access_token 을 mainState 에 두고, Set-Cookie 의 refresh_token 은 응답
   * 인터셉터(captureRefreshCookie)가 꺼내 메모리에 보관한다. Node 의 axios 에는 쿠키
   * 저장소가 없어서 그냥 두면 버려진다.
   * codeVerifier 는 PKCE 표준 필드로 함께 전달 (백엔드가 확장 시 활용, 미사용이면 무시).
   */
  async oauthCallback(params: {
    provider: 'google' | 'kakao'
    code: string
    redirectUri: string
    codeVerifier?: string
  }): Promise<{ token: string; user: unknown }> {
    const { data } = await http.post('/api/v1/auth/oauth/callback', {
      provider: params.provider.toUpperCase(),
      code: params.code,
      redirect_uri: params.redirectUri,
      ...(params.codeVerifier ? { code_verifier: params.codeVerifier } : {}),
    })
    return { token: data.access_token, user: data }
  },

  /**
   * 서버측 refresh token 폐기.
   *
   * 이제 터미널이 refresh token 을 실제로 보유하므로, 로그아웃할 때 서버에서도 지워야
   * 한다. 메모리만 비우면 그 토큰은 Redis 에서 최대 7일 살아 있고, 어디선가 새어 나간
   * 값이 로그아웃 뒤에도 계속 유효하다.
   *
   * 실패해도 로그아웃 자체는 진행한다 — 네트워크가 끊긴 상태에서 로그아웃을 막을 이유가 없다.
   */
  async logout(): Promise<void> {
    try {
      await http.post('/api/v1/auth/logout')
    } catch (e) {
      console.warn('[Backend] 서버측 로그아웃 실패 — 로컬 세션은 정리한다:', e)
    }
  },

  async getMe(): Promise<{ id: number; email: string; nickname: string; role: string }> {
    const { data } = await http.get('/api/v1/users/me')
    return data
  },

  async sendCallback(tradeId: string, payload: CallbackPayload): Promise<void> {
    await http.post(`/api/v1/trades/${tradeId}/callback`, payload)
  },

  async recordManualTrade(payload: ManualTradePayload): Promise<void> {
    await http.post('/api/v1/trades/manual', payload)
  },

  /**
   * Terminal 재접속 시점에 호출. 백엔드 STOMP convertAndSendToUser 가 미접속 사용자에게
   * silent drop 되므로, TTL 내 미만료 PENDING 명령을 REST 로 fetch 해 복구한다.
   * 응답 형식은 STOMP /user/queue/signals 메시지와 동일 (TradeCommandMessage 직렬화 결과).
   * 실패 시 throw — 호출 측이 catch 해 graceful 처리.
   */
  async fetchPendingTrades(): Promise<TradeSignal[]> {
    const { data } = await http.get<TradeSignal[]>('/api/v1/trades/pending')
    return Array.isArray(data) ? data : []
  },

  /**
   * 어닝콜 시연 재생 시작 (Contract 7.8).
   * 202 = 시작, 409 = 이미 재생 중, 500 = 스크립트 결함.
   * 409 는 정상 흐름(중복 클릭)이므로 예외 대신 결과로 구분해 돌려준다.
   */
  async startEarningsDemo(ticker: string): Promise<DemoStartResult> {
    try {
      const { data } = await http.post('/api/v1/demo/earnings-call/start', { ticker })
      return {
        ok: true,
        callId: String(data?.call_id ?? ''),
        segmentCount: Number(data?.segment_count ?? 0),
        intervalMs: Number(data?.interval_ms ?? 0),
        evidenceWarning:
          typeof data?.evidence_warning === 'string' ? data.evidence_warning : undefined,
      }
    } catch (e) {
      const status = (e as { response?: { status?: number } })?.response?.status
      const message =
        (e as { response?: { data?: { error?: string } } })?.response?.data?.error ??
        '시연을 시작하지 못했습니다.'
      return { ok: false, reason: status === 409 ? 'ALREADY_RUNNING' : 'FAILED', message }
    }
  },

  /**
   * 콜 참가자 명부 조회.
   * 백엔드는 사실 항목만 (이름/직책/소속/애널리스트 여부) 돌려준다. 실패하면 빈 배열 —
   * 명부는 부가 정보라서, 못 가져왔다고 트레이딩 룸 진입을 막을 이유가 없다.
   */
  async getEarningsSpeakers(): Promise<SpeakerProfilePayload[]> {
    try {
      const { data } = await http.get('/api/v1/demo/earnings-call/speakers')
      if (!Array.isArray(data)) return []
      const seen = new Set<string>()
      return data.flatMap((raw) => {
        const name = typeof raw?.name === 'string' ? raw.name.trim() : ''
        if (!name) return []
        // match_key 는 세그먼트 speaker 문자열과 정확히 같은 값이다. 백엔드가 채워 주므로
        // 클라이언트가 "이름이 라벨에 들어 있나" 를 추측할 필요가 없다 — 그 추측은
        // 동명이인이나 중간 이니셜에서 조용히 틀린다.
        const rawKey = typeof raw?.match_key === 'string' ? raw.match_key.trim() : ''
        const matchKey = (rawKey || name).toLowerCase()
        // 같은 키가 두 번 오면 발언량이 한쪽으로 덮이고 탭의 React key 도 충돌한다.
        if (seen.has(matchKey)) return []
        seen.add(matchKey)
        return [{
          matchKey,
          name,
          title: typeof raw?.title === 'string' ? raw.title : '',
          affiliation: typeof raw?.affiliation === 'string' ? raw.affiliation : '',
          kind: raw?.analyst === true ? ('ANALYST' as const) : ('MANAGEMENT' as const),
        }]
      })
    } catch {
      return []
    }
  },

  /** 어닝콜 시연 재생 중지. 진행 중인 재생이 없으면(404) false. */
  async stopEarningsDemo(ticker: string): Promise<boolean> {
    try {
      await http.post('/api/v1/demo/earnings-call/stop', { ticker })
      return true
    } catch {
      return false
    }
  },

  async syncPortfolio(payload: PortfolioSyncPayload): Promise<void> {
    await http.post('/api/v1/portfolio/sync', payload)
  },

  async updateSettings(settings: UserSettings): Promise<void> {
    await http.put('/api/v1/users/settings', settings)
  },

  async getTrades(page = 0, size = 20, startDate?: string): Promise<unknown> {
    const params: Record<string, unknown> = { page, size }
    if (startDate) params.startDate = startDate
    const { data } = await http.get('/api/v1/trades', { params })
    return data
  },

  async getSettings(): Promise<{
    buyAmountRatio: number
    maxPositionRatio: number
    cooldownMinutes: number
    aiScoreThreshold: number
    tradingMode: 'MANUAL' | 'SEMI_AUTO' | 'AUTO_PILOT'
  }> {
    const { data } = await http.get('/api/v1/portfolio/settings')
    return data
  },

  /**
   * 글로벌 시장 지수 5종 초기 스냅샷.
   * Backend Contract 7.7 — 인증 불필요, 빈 캐시 시 200 [].
   * 호출 실패 시 IPC handler 가 빈 배열로 graceful fallback.
   */
  async getMarketIndices(): Promise<MarketIndexPayload[]> {
    const { data } = await http.get<MarketIndexPayload[]>('/api/v1/market/indices')
    return Array.isArray(data) ? data : []
  },

  /**
   * 관심종목 ticker 목록 조회.
   * GET /api/v1/watchlist — JWT 인증 (interceptor 가 mainState.backendToken 자동 첨부).
   * 실패 시 throw — 호출 측(watchlistHandlers)이 catch 해 캐시 유지 + 빈 배열 fallback.
   */
  async getWatchlist(): Promise<WatchlistItem[]> {
    const { data } = await http.get<WatchlistItem[]>('/api/v1/watchlist')
    return Array.isArray(data) ? data : []
  },

  /**
   * 관심종목 추가 — POST /api/v1/watchlist body { ticker }.
   * 응답: WatchlistItem (백엔드가 ticker → companyName/sector 채워서 돌려줌).
   * 4xx/5xx 시 axios 가 throw → handler 가 그대로 IPC reject 로 propagate.
   */
  async addWatchlist(ticker: string): Promise<WatchlistItem> {
    const { data } = await http.post<WatchlistItem>('/api/v1/watchlist', { ticker })
    return data
  },

  /**
   * 관심종목 제거 — DELETE /api/v1/watchlist/{ticker}.
   * 응답 본문 없음 (void). 4xx/5xx 시 throw.
   */
  async removeWatchlist(ticker: string): Promise<void> {
    await http.delete(`/api/v1/watchlist/${encodeURIComponent(ticker)}`)
  },

  /**
   * 종목 상세 — GET /api/v1/stocks/{ticker}/detail (JWT 필수).
   * 응답: StockDetailResponsePayload (Phase 3 백엔드 record 직렬화 결과).
   * 4xx/5xx 시 axios 가 throw → handler 가 IPC reject 로 propagate.
   */
  async getStockDetail(ticker: string): Promise<StockDetailResponsePayload> {
    const { data } = await http.get<StockDetailResponsePayload>(
      `/api/v1/stocks/${encodeURIComponent(ticker)}/detail`,
    )
    return data
  },

  /**
   * Trading Terminal용 어닝콜 타임라인 — S&P 500 전체 종목 flat list.
   * GET /api/v1/earnings-calendar/terminal-timeline?days={days}
   * 그룹핑은 호출 측(earningsHandlers)에서 수행한다.
   */
  async getSp500List(): Promise<Sp500Stock[]> {
    const { data } = await http.get<Sp500Stock[]>('/api/v1/stocks/sp500')
    return Array.isArray(data) ? data : []
  },

  async getStockPricesSnapshot(): Promise<StockPriceEntry[]> {
    const { data } = await http.get<StockPriceEntry[]>('/api/v1/stocks/prices')
    return Array.isArray(data) ? data : []
  },

  async getEarningsTimeline(days = 7): Promise<EarningsTimelineItem[]> {
    const { data } = await http.get<EarningsTimelineItem[]>(
      '/api/v1/earnings-calendar/terminal-timeline',
      { params: { days } },
    )
    return Array.isArray(data) ? data : []
  },

  async getAssetHistory(days: number): Promise<AssetHistoryPoint[]> {
    const { data } = await http.get<AssetHistoryPoint[]>('/api/v1/portfolio/asset-history', {
      params: { days },
    })
    return Array.isArray(data) ? data : []
  },

  /**
   * 사용자의 BrokerAccount 목록 중 active 계정을 반환. 없으면 null.
   * 로그인 후 accountType 및 SELF_PAPER 잔고 초기화에 사용.
   */
  async getActiveBrokerAccount(): Promise<{ id: number; accountType: string; alias: string; cashBalance: number | null; active: boolean } | null> {
    const { data } = await http.get<Array<{ id: number; accountType: string; alias: string; cashBalance: number | null; active: boolean }>>('/api/v1/portfolio/broker-accounts')
    return Array.isArray(data) ? (data.find((a) => a.active) ?? null) : null
  },

  /**
   * 활성 BrokerAccount 의 보유종목 목록 조회.
   * SELF_PAPER 모드의 mainState 잔고 초기화에 사용.
   */
  async getPositions(): Promise<{ ticker: string; quantity: number; avgPrice: number }[]> {
    const { data } = await http.get<{ ticker: string; quantity: number; avgPrice: number }[]>('/api/v1/portfolio/positions')
    return Array.isArray(data) ? data : []
  },
}

export interface AssetHistoryPoint {
  date: string
  totalAssetUsd: number
}

export interface EarningsTimelineItem {
  ticker: string
  companyName: string
  /** epoch seconds UTC */
  scheduledAt: number
  confirmed: boolean
  /** Finnhub hour 필드: "bmo"(장전) | "amc"(장후) | "dmh"(장중) | null */
  marketSession: string | null
}
