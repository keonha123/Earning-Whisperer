import axios from 'axios'
import { mainState } from '../store/mainState'

const BASE_URL = process.env.BACKEND_URL ?? 'http://localhost:8082'

const http = axios.create({ baseURL: BASE_URL, timeout: 10_000 })

http.interceptors.request.use((config) => {
  const token = mainState.backendToken
  if (token) config.headers.Authorization = `Bearer ${token}`
  return config
})

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

export interface PortfolioSyncPayload {
  total_cash: number
  holdings: { ticker: string; qty: number; avg_price: number }[]
}

export interface UserSettings {
  trading_mode: 'MANUAL' | 'SEMI_AUTO' | 'AUTO_PILOT'
  max_buy_ratio: number
  max_holding_ratio: number
  cooldown_minutes: number
}

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

  async syncPortfolio(payload: PortfolioSyncPayload): Promise<void> {
    await http.post('/api/v1/portfolio/sync', payload)
  },

  async updateSettings(settings: UserSettings): Promise<void> {
    await http.put('/api/v1/users/settings', settings)
  },

  async getTrades(page = 0, size = 20): Promise<unknown> {
    const { data } = await http.get('/api/v1/trades', { params: { page, size } })
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
}
