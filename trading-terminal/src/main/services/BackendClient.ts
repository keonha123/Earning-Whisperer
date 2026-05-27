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

http.interceptors.request.use((config) => {
  const token = mainState.backendToken
  if (token) config.headers.Authorization = `Bearer ${token}`
  return config
})

// 모든 axios error 를 IpcError 로 변환해 호출 측 (IPC handler) 가 일관된 형식으로 받도록 한다.
// BackendClient 외 axios 인스턴스 (KisService 등) 는 적용 대상 외.
http.interceptors.response.use(
  (response) => response,
  (error: unknown) => Promise.reject(axiosErrorToIpcError(error)),
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

export const BackendClient = {
  async login(email: string, password: string): Promise<{ token: string; user: unknown }> {
    const { data } = await http.post('/api/v1/auth/login', { email, password })
    return { token: data.access_token, user: data }
  },

  /**
   * OAuth (Google / Kakao) 콜백 교환.
   * 백엔드: POST /api/v1/auth/oauth/callback — body { code, redirect_uri (snake_case), provider }
   *   응답 body: { access_token, refresh_token } + Set-Cookie(refresh_token; HttpOnly).
   * Electron 은 access_token 만 mainState 에 메모리 저장. refresh_token 쿠키는 axios session 이 자동 보관.
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
