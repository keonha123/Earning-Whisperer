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

  WS_CONNECT: 'terminal:ws:connect',
  WS_DISCONNECT: 'terminal:ws:disconnect',

  TRADES_GET: 'terminal:trades:get',
  TRADE_CANCEL: 'terminal:trade:cancel',

  /**
   * 글로벌 시장 지수 5종 (SPX/NDX/VIX/DXY/10Y) 초기 스냅샷 조회.
   * Backend Contract 7.7: GET /api/v1/market/indices, 인증 불필요, 빈 캐시 시 200 [].
   */
  MARKET_INDICES_GET: 'terminal:market:indices-get',

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
} as const
