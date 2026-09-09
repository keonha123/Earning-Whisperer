import { mainState, TradingMode, AccountType } from '../store/mainState'
import { BackendClient } from '../services/BackendClient'
import { StompService } from '../services/StompService'
import { KisService } from '../services/KisService'
import { OAuthService, OAuthProvider } from '../services/OAuthService'
import { IPC_CHANNELS } from '../../lib/ipcChannels'
import { IpcError } from '../../lib/types/ipcError'
import { start as startWatchlist, stop as stopWatchlist } from './watchlistHandlers'
import { clearCache as clearStockDetailCache } from './stockDetailHandlers'
import { start as startEarnings, stop as stopEarnings } from './earningsHandlers'
import { start as startPricePoller, stop as stopPricePoller } from '../services/PricePoller'
import { KisWebSocketService } from '../services/KisWebSocketService'
import { SubscriptionManager } from '../services/SubscriptionManager'
import { registerHandler } from './registerHandler'

/**
 * 로그인 후처리 — 이메일 로그인/OAuth 로그인이 공통으로 사용한다.
 *
 * 토큰 저장 → 유저 조회(필수) → 설정/활성 계좌/KIS 토큰 복원(선택) → 폴러 시작.
 * 유저 조회가 실패하면 인증되지 않은 토큰이 남지 않도록 mainState 를 비우고 rethrow 한다.
 */
/**
 * 세션 종료 시 메인 프로세스 정리.
 *
 * 명시적 로그아웃과 "갱신 실패로 세션이 끝난 경우" 가 같은 절차를 타야 한다.
 * 예전에는 이 정리가 AUTH_LOGOUT 핸들러 안에만 있어서, 토큰이 조용히 만료되면
 * 렌더러만 /auth 로 넘어가고 메인 프로세스의 폴러·소켓은 계속 돌았다. 죽은
 * 토큰으로 5분마다 401 을 받아 내는 상태가 무한히 이어졌다.
 */
export function teardownSession(): void {
  StompService.disconnect()
  KisWebSocketService.disconnect()
  SubscriptionManager.reset()
  stopWatchlist()
  stopEarnings()
  stopPricePoller()
  // 종목 상세 캐시 클리어 — 사용자 전환 시 이전 응답 노출 방지
  clearStockDetailCache()
  // KIS refreshTimer 취소 — 로그아웃 상태에서 타이머가 keytar 를 읽어 토큰을 재발급하는 것을 막는다.
  KisService.invalidateRuntime()
  mainState.clear()
}

export async function completeLogin(token: string) {
  mainState.setBackendToken(token)

  // 유저 정보 조회 (필수)
  let user: Awaited<ReturnType<typeof BackendClient.getMe>>
  try {
    user = await BackendClient.getMe()
  } catch (e) {
    // 후처리에 실패한 토큰이 남아 있으면 이후 요청이 반쯤 로그인된 상태로 나간다.
    mainState.clear()
    throw e
  }

  // 포트폴리오 설정 조회 (선택 — 실패해도 기본값으로 로그인 진행)
  let settings: Awaited<ReturnType<typeof BackendClient.getSettings>> | null = null
  try {
    settings = await BackendClient.getSettings()
    if (settings.tradingMode) {
      mainState.setTradingMode(settings.tradingMode as TradingMode)
    }
  } catch (e) {
    console.warn('[Auth] 설정 로드 실패, 기본값 사용:', e instanceof Error ? e.message : 'unknown error')
  }

  // 활성 BrokerAccount 조회 → accountType + SELF_PAPER 잔고 초기화 (선택)
  try {
    const activeAccount = await BackendClient.getActiveBrokerAccount()
    if (activeAccount) {
      mainState.setAccountType(activeAccount.accountType as AccountType)
      if (activeAccount.accountType === 'SELF_PAPER') {
        const positions = await BackendClient.getPositions()
        mainState.setSelfPaperBalance(
          activeAccount.cashBalance,
          positions.map((p) => ({ ticker: p.ticker, qty: p.quantity })),
        )
      }
    }
  } catch (e) {
    console.warn('[Auth] BrokerAccount 조회 실패, 기본값 사용:', e instanceof Error ? e.message : 'unknown error')
  }

  // KIS 토큰 복원 (선택 — 실패해도 로그인 진행)
  try {
    await KisService.loadSavedToken()
  } catch (e) {
    console.warn('[Auth] KIS 토큰 복원 실패:', e instanceof Error ? e.message : 'unknown error')
  }

  // 관심종목 5분 폴링 시작 (이미 동작 중이면 no-op).
  startWatchlist()
  // 어닝콜 타임라인 5분 폴링 시작.
  startEarnings()
  // 시세 폴링 시작 — ticker 들은 watchlist 동기화/Renderer holdings 통보로 채워진다.
  startPricePoller()
  // KIS WebSocket 실시간 시세 연결 (실전 appKey 미등록 시 silent skip).
  void KisWebSocketService.connectWithStoredKey()

  return { user, settings, accountType: mainState.accountType }
}

export function registerAuthHandlers() {
  registerHandler<{ email: string; password: string }, { user: unknown; settings: unknown }>(
    IPC_CHANNELS.AUTH_LOGIN,
    async (_e, { email, password }) => {
      const { token } = await BackendClient.login(email, password)
      return completeLogin(token)
    },
  )

  registerHandler<undefined, void>(IPC_CHANNELS.AUTH_LOGOUT, async () => {
    // 서버측 폐기가 먼저다 — teardownSession 이 refresh token 을 지우고 나면 보낼 것이 없다.
    await BackendClient.logout()
    teardownSession()
  })

  /**
   * OAuth (Google / Kakao) 로그인 — Loopback Localhost Server 흐름.
   * Renderer 가 invoke 한 단일 Promise 가 콜백 수신/실패/타임아웃까지 대기한다.
   * 결과 형식은 AUTH_LOGIN 과 동일 ({ user, settings }) — Renderer 의 onSuccess 재사용 보장.
   */
  registerHandler<{ provider: OAuthProvider }, unknown>(
    IPC_CHANNELS.AUTH_OAUTH_START,
    async (_e, payload) => {
      if (!payload || (payload.provider !== 'google' && payload.provider !== 'kakao')) {
        throw new IpcError('VALIDATION', '지원하지 않는 OAuth provider 입니다.')
      }
      return OAuthService.start(payload.provider)
    },
  )
}
