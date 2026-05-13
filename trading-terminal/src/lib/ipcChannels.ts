/**
 * IPC 채널명 상수.
 * Main ↔ Renderer 양쪽에서 동일한 파일을 참조하여 오타를 방지한다.
 */
export const IPC_CHANNELS = {
  // Renderer → Main (invoke/handle)
  AUTH_LOGIN: 'terminal:auth:login',
  AUTH_LOGOUT: 'terminal:auth:logout',
  AUTH_OAUTH_START: 'terminal:auth:oauth:start',

  VAULT_SAVE: 'terminal:vault:save-credentials',
  VAULT_HAS: 'terminal:vault:has-credentials',
  VAULT_DELETE: 'terminal:vault:delete-credentials',
  /**
   * 모드별 마스킹된 자격증명 조회 (A3).
   * 응답: MaskedCredentialsResponse — appSecret 은 절대 포함되지 않는다.
   * SettingsPage 의 카드 표시 / TopHeader 의 식별 표시 등 "어떤 키가 등록되어 있는가" 를
   * 사용자가 인지하기 위한 최소 정보만 노출.
   */
  VAULT_GET_MASKED: 'terminal:vault:get-masked-credentials',

  KIS_GET_BALANCE: 'terminal:kis:get-balance',
  KIS_PLACE_ORDER: 'terminal:kis:place-order',
  /** 사용자가 OrderBar 에서 직접 입력한 수동 주문. payload: ManualOrderRequest */
  KIS_PLACE_MANUAL_ORDER: 'terminal:kis:place-manual-order',
  KIS_GET_TOKEN_STATUS: 'terminal:kis:get-token-status',
  KIS_ISSUE_TOKEN: 'terminal:kis:issue-token',

  SETTINGS_UPDATE: 'terminal:settings:update',

  /**
   * 모의/실전 환경 토글 — Renderer 마운트 시 현재 값 조회.
   * 응답: boolean (true=모의, false=실전).
   */
  SETTINGS_GET_PAPER_TRADING: 'terminal:settings:get-paper-trading',
  /**
   * 모의/실전 환경 토글 — Renderer가 새 값으로 변경 요청.
   * payload: { value: boolean }, 응답: { ok: true }.
   */
  SETTINGS_SET_PAPER_TRADING: 'terminal:settings:set-paper-trading',
  /**
   * 환경 변경 broadcast — main이 setPaperTrading 처리 후 모든 렌더러에 push.
   * payload: { value: boolean }.
   */
  SETTINGS_PAPER_TRADING_CHANGED: 'terminal:settings:paper-trading-changed',

  WS_CONNECT: 'terminal:ws:connect',
  WS_DISCONNECT: 'terminal:ws:disconnect',

  TRADES_GET: 'terminal:trades:get',
  TRADE_CANCEL: 'terminal:trade:cancel',
  /** TradingRoom 진입 시 세션 시작. payload: { ticker: string } */
  TRADE_SESSION_START: 'terminal:trade-session:start',
  /** TradingRoom 명시적 나가기 시 세션 종료. */
  TRADE_SESSION_END: 'terminal:trade-session:end',

  /**
   * 글로벌 시장 지수 5종 (SPX/NDX/VIX/DXY/10Y) 초기 스냅샷 조회.
   * Backend Contract 7.7: GET /api/v1/market/indices, 인증 불필요, 빈 캐시 시 200 [].
   */
  MARKET_INDICES_GET: 'terminal:market:indices-get',

  /**
   * 관심종목 ticker 목록 — main 캐시 반환 (없으면 빈 배열).
   * Backend GET /api/v1/watchlist (JWT 인증) 응답을 main 이 5분 주기로 캐싱.
   */
  WATCHLIST_GET: 'terminal:watchlist:get',
  /**
   * 관심종목 강제 재조회 — main 이 백엔드 즉시 호출 → 캐시 갱신 → broadcast.
   * 호출자에게도 갱신된 배열 반환.
   */
  WATCHLIST_REFRESH: 'terminal:watchlist:refresh',
  /**
   * 관심종목 추가 — POST /api/v1/watchlist body { ticker }.
   * payload: { ticker } / 응답: WatchlistItem (camelCase: ticker/companyName/sector).
   * 성공 시 캐시 갱신 + WATCHLIST_UPDATE broadcast + PricePoller setWatchlist 통보.
   */
  WATCHLIST_ADD: 'terminal:watchlist:add',
  /**
   * 관심종목 제거 — DELETE /api/v1/watchlist/{ticker}.
   * payload: { ticker } / 응답: void. 성공 시 캐시 갱신 + WATCHLIST_UPDATE broadcast.
   */
  WATCHLIST_REMOVE: 'terminal:watchlist:remove',

  /**
   * 종목 상세 — GET /api/v1/stocks/{ticker}/detail (JWT).
   * payload: { ticker } / 응답: StockDetailResponsePayload.
   * Main 이 ticker별 30s TTL 캐시 보유 (drawer 단기 재오픈 시 백엔드 호출 절감).
   */
  STOCK_GET_DETAIL: 'terminal:stock:get-detail',

  /**
   * 시세 폴링 캐시 조회 — Renderer 마운트 시 초기 로드용.
   * 응답: Record<string, { currentPrice: number; lastUpdated: number }>.
   */
  PRICES_GET: 'terminal:prices:get',

  /**
   * 보유종목 ticker 갱신 통보 — Renderer 가 KIS_GET_BALANCE 응답 처리 후
   * Main 의 PricePoller 에 ticker 변경을 알림.
   * payload: { tickers: string[] }.
   */
  HOLDINGS_TICKERS_UPDATE: 'terminal:holdings:tickers-update',

  // Main → Renderer (send)
  SIGNAL_RECEIVED: 'terminal:signal:received',
  TRADE_EXECUTED: 'terminal:trade:executed',
  TRADE_FAILED: 'terminal:trade:failed',
  WS_STATUS_CHANGED: 'terminal:ws:status-changed',
  MODE_FORCED_MANUAL: 'terminal:mode:forced-manual',
  KIS_TOKEN_REFRESHED: 'terminal:kis:token-refreshed',
  /**
   * KIS 토큰 자동 갱신이 최대 재시도까지 실패한 경우 발신.
   * Renderer 는 사용자에게 재로그인/수동 재발급 안내 toast 를 띄운다.
   * payload: { attempts: number }
   */
  KIS_TOKEN_REFRESH_FAILED: 'terminal:kis:token-refresh-failed',

  /**
   * 글로벌 시장 지수 1분 단위 push.
   * Backend Contract 4.4: STOMP /topic/market/indices, 인증 불필요, 5종 단건 메시지.
   * payload: { symbol, price, change_percent, trend, format, timestamp } (snake_case)
   */
  MARKET_INDICES_UPDATE: 'terminal:market:indices-update',

  /**
   * 관심종목 캐시 갱신 broadcast — main 의 5분 폴링 또는 강제 refresh 시 발신.
   * payload: WatchlistItem[] (camelCase: ticker/companyName/sector)
   */
  WATCHLIST_UPDATE: 'terminal:watchlist:update',

  /**
   * 시세 batch push — PricePoller 사이클당 1회, 갱신된 ticker 들만 묶어서 전송.
   * payload: { ticker: string; currentPrice: number; lastUpdated: number }[].
   */
  PRICES_UPDATE: 'terminal:prices:update',

  /**
   * 실시간 어닝콜 트랜스크립트 동적 구독.
   * Backend Contract 4.5: STOMP /topic/transcript/{ticker}, 기존 STOMP 세션 JWT 사용.
   * Renderer → Main: 사용자가 보는 어닝콜 ticker 변경 시 SUBSCRIBE/UNSUBSCRIBE 호출.
   * payload: { ticker } (Renderer→Main)
   */
  TRANSCRIPT_SUBSCRIBE: 'terminal:transcript:subscribe',
  TRANSCRIPT_UNSUBSCRIBE: 'terminal:transcript:unsubscribe',

  /**
   * STOMP 트랜스크립트 segment push (Main → Renderer).
   * payload (snake_case): {
   *   ticker, call_id, sequence, start_ms, end_ms,
   *   text, speaker?, timestamp, is_session_end?
   * }
   * snake_case → camelCase 변환은 store 의 upsertSegment 에서 수행.
   */
  TRANSCRIPT_SEGMENT_RECEIVED: 'terminal:transcript:segment-received',

  /**
   * 어닝콜 타임라인 조회 (Renderer → Main, invoke).
   * S&P 500 전체 종목 대상. main process 에서 그룹핑 후 EarningsTimelineData 반환.
   * 응답: EarningsTimelineData { live, groups }
   */
  EARNINGS_TIMELINE_GET: 'terminal:earnings:timeline-get',

  /**
   * 어닝콜 타임라인 5분 폴링 push (Main → Renderer).
   * 로그인 후 5분 간격으로 갱신된 EarningsTimelineData 를 전송한다.
   * payload: EarningsTimelineData
   */
  EARNINGS_TIMELINE_UPDATE: 'terminal:earnings:timeline-update',

  /**
   * S&P 500 종목 리스트 조회 (Renderer → Main, invoke).
   * GET /api/v1/stocks/sp500 — JWT 불필요, 시가총액순 정렬.
   * 응답: Sp500Stock[]
   */
  STOCKS_SP500_GET: 'terminal:stocks:sp500-get',

  /**
   * 전체 주가 스냅샷 초기 로딩 (Renderer → Main, invoke).
   * GET /api/v1/stocks/prices — JWT 불필요.
   * 응답: StockPriceEntry[] (ticker, currentPrice, previousClose, changePercent, updatedAt)
   */
  STOCK_PRICES_SNAPSHOT_GET: 'terminal:stocks:prices-snapshot-get',
} as const

/**
 * VAULT_GET_MASKED 응답 타입 — 모드별 마스킹된 자격증명.
 *
 * 각 모드 키:
 *   - 등록되지 않음 (appKey 또는 accountNo 누락) → `null`
 *   - 등록됨 → `{ appKeyMasked, accountNoMasked }` (prefix + 마스크 + suffix)
 *
 * appSecret 은 응답에 포함되지 않는다 — 사용자가 다시 보고 싶다면 재등록(수정) 흐름으로만.
 * Renderer 는 이 응답을 렌더 후 보존하지 말고 (예: zustand 에 박지 말고) drawer/카드 닫힐 때 폐기.
 */
export interface MaskedCredentialsResponse {
  paper: { appKeyMasked: string; accountNoMasked: string } | null
  real: { appKeyMasked: string; accountNoMasked: string } | null
}
