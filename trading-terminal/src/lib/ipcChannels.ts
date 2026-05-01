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

  KIS_GET_BALANCE: 'terminal:kis:get-balance',
  KIS_PLACE_ORDER: 'terminal:kis:place-order',
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
} as const
