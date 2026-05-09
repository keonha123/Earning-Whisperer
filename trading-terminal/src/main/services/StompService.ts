import { Client, type IMessage, type StompSubscription } from '@stomp/stompjs'
import WebSocket from 'ws'
import { BrowserWindow } from 'electron'
import { mainState } from '../store/mainState'
import { IPC_CHANNELS } from '../../lib/ipcChannels'
import { TradeExecutor, type TradeSignal } from './TradeExecutor'
import { BackendClient } from './BackendClient'
import { NotificationService } from './NotificationService'
import { markStompCovered, clearStompCovered } from './PricePoller'

const WS_URL = (process.env.BACKEND_URL ?? 'http://localhost:8082')
  .replace(/^http/, 'ws') + '/ws-native'

type WsStatus = 'DISCONNECTED' | 'CONNECTING' | 'CONNECTED' | 'RECONNECTING'

let client: Client | null = null
let retryCount = 0
let hasConnectedOnce = false
const RETRY_DELAYS = [2000, 4000, 8000, 16000, 30000]

/**
 * 활성 트랜스크립트 구독 핸들 — ticker 별 1개.
 * 재연결 시 onConnect 에서 동일 ticker 들을 자동 재구독한다.
 *  - 키: ticker (예: "NVDA")
 *  - 값: STOMP subscription handle (활성), 또는 undefined (미연결 상태에서 sub 요청만 기록)
 */
const transcriptSubscriptions = new Map<string, StompSubscription | undefined>()

function getRetryDelay(): number {
  return RETRY_DELAYS[Math.min(retryCount, RETRY_DELAYS.length - 1)]
}

function pushToRenderer(channel: string, payload: unknown) {
  BrowserWindow.getAllWindows().forEach((win) => {
    if (!win.isDestroyed()) win.webContents.send(channel, payload)
  })
}

/**
 * STOMP /user/queue/signals 단건 처리. Renderer 통보 + AUTO_PILOT 자동 실행을 한 곳에서 관리.
 * 콜백 멱등성(PR1)에 의해 STOMP+fetch 중복 도착도 안전.
 */
function dispatchTradeSignal(signal: TradeSignal) {
  pushToRenderer(IPC_CHANNELS.SIGNAL_RECEIVED, signal)
  if (mainState.tradingMode === 'AUTO_PILOT') {
    TradeExecutor.execute(signal).catch((e) => {
      console.error('[StompService] AUTO_PILOT 실행 실패:', e)
    })
  }
}

/**
 * fetch 로 복원된 N 개 명령을 직렬로 실행.
 * TradeExecutor 가 mainState.isOrderInProgress 락을 즉시 set 하므로 await 없이 병렬 호출하면
 * 첫 명령만 실행되고 나머지는 silent FAILED 가 된다. 직렬 실행으로 모든 명령을 처리한다.
 */
async function dispatchPendingBatch(signals: TradeSignal[]): Promise<void> {
  for (const signal of signals) {
    pushToRenderer(IPC_CHANNELS.SIGNAL_RECEIVED, signal)
    if (mainState.tradingMode === 'AUTO_PILOT') {
      try {
        await TradeExecutor.execute(signal)
      } catch (e) {
        console.error('[StompService] AUTO_PILOT 실행 실패 (PENDING 복구):', e)
      }
    }
  }
}

function onStatusChange(status: WsStatus) {
  pushToRenderer(IPC_CHANNELS.WS_STATUS_CHANGED, { status })

  if (status === 'DISCONNECTED' || status === 'RECONNECTING') {
    // Fallback: 강제 MANUAL 전환
    if (mainState.tradingMode !== 'MANUAL') {
      mainState.setTradingMode('MANUAL')
      pushToRenderer(IPC_CHANNELS.MODE_FORCED_MANUAL, {
        reason: '백엔드 WebSocket 연결이 끊겼습니다.',
      })
      NotificationService.notifyWsDisconnected()
    }
  } else if (status === 'CONNECTED') {
    if (hasConnectedOnce) NotificationService.notifyWsReconnected()
    hasConnectedOnce = true
  }
}

export const StompService = {
  connect() {
    if (client?.connected) return

    const token = mainState.backendToken
    console.log('[StompService] connect() called — WS_URL:', WS_URL, '| token:', token ? '있음' : '없음(null)')
    if (!token) return

    onStatusChange('CONNECTING')

    client = new Client({
      webSocketFactory: () => new WebSocket(WS_URL) as unknown as globalThis.WebSocket,
      connectHeaders: { Authorization: `Bearer ${token}` },
      heartbeatIncoming: 10000,
      heartbeatOutgoing: 10000,
      reconnectDelay: 0, // 직접 관리

      onConnect: () => {
        retryCount = 0
        onStatusChange('CONNECTED')

        // Private 채널 구독
        client!.subscribe(
          `/user/queue/signals`,
          (message: IMessage) => {
            try {
              const signal = JSON.parse(message.body) as TradeSignal
              dispatchTradeSignal(signal)
            } catch (e) {
              console.error('[StompService] 신호 파싱 실패:', e)
            }
          },
        )

        /*
         * 미접속 중에 STOMP convertAndSendToUser 가 silent drop 한 명령을 REST 로 복구한다.
         * 첫 connect / 재연결 양쪽 모두에서 실행. 백엔드 TTL(기본 30초) 내 PENDING 만 반환되며,
         * STOMP 와 중복 도착해도 PR1 콜백 멱등성으로 안전.
         */
        BackendClient.fetchPendingTrades()
          .then(async (pending) => {
            if (pending.length > 0) {
              console.log(`[StompService] PENDING ${pending.length}건 복구 fetch`)
            }
            await dispatchPendingBatch(pending)
          })
          .catch((e) => {
            console.error('[StompService] PENDING fetch 실패:', e)
          })

        /*
         * Public 시장 지수 채널 구독 (Contract 4.4).
         * 인증 불필요 토픽이지만 동일 STOMP 세션을 재사용해 추가 구독으로 처리한다.
         * 5종 단건 메시지 (배열 X) — renderer 의 store 가 symbol 로 upsert.
         */
        client!.subscribe(
          `/topic/market/indices`,
          (message: IMessage) => {
            try {
              const payload = JSON.parse(message.body)
              pushToRenderer(IPC_CHANNELS.MARKET_INDICES_UPDATE, payload)
            } catch (e) {
              console.error('[StompService] 시장 지수 파싱 실패:', e)
            }
          },
        )

        /*
         * Finnhub 실시간 주가 relay 구독 — 1초 배치.
         * 백엔드 StockPricePublisher 가 변경된 티커만 배열로 발행.
         * STOMP 커버 종목은 KIS REST 폴링 skip, 끊김 시 KIS fallback.
         */
        client!.subscribe(
          `/topic/prices`,
          (message: IMessage) => {
            try {
              const updates = JSON.parse(message.body) as Array<{
                ticker: string
                currentPrice: number
                previousClose: number
                changePercent: number
                updatedAt: number
              }>
              if (!Array.isArray(updates) || updates.length === 0) return
              const batch = updates.map((u) => ({
                ticker: u.ticker,
                currentPrice: u.currentPrice,
                previousClose: u.previousClose,
                lastUpdated: u.updatedAt,
              }))
              markStompCovered(batch.map((u) => u.ticker))
              pushToRenderer(IPC_CHANNELS.PRICES_UPDATE, batch)
            } catch (e) {
              console.error('[StompService] 주가 업데이트 파싱 실패:', e)
            }
          },
        )

        /*
         * 재연결 시 활성 트랜스크립트 ticker 자동 재구독 (Contract 4.5).
         * Renderer 가 보고 있던 ticker 의 segment 가 끊김 없이 이어지도록 한다.
         * 새로 발급되는 subscription handle 로 Map 값을 갱신한다.
         */
        for (const ticker of transcriptSubscriptions.keys()) {
          const sub = client!.subscribe(
            `/topic/transcript/${ticker}`,
            transcriptMessageHandler,
          )
          transcriptSubscriptions.set(ticker, sub)
        }
      },

      onDisconnect: () => {
        clearStompCovered()
        onStatusChange('DISCONNECTED')
        scheduleReconnect()
      },

      onStompError: (frame) => {
        console.error('[StompService] STOMP 에러:', frame)
        clearStompCovered()
        onStatusChange('DISCONNECTED')
        scheduleReconnect()
      },

      onWebSocketError: (event) => {
        console.error('[StompService] WebSocket 연결 오류:', event)
        onStatusChange('RECONNECTING')
        scheduleReconnect()
      },
    })

    client.activate()
  },

  disconnect() {
    client?.deactivate()
    client = null
    retryCount = 0
    // 트랜스크립트 핸들도 함께 정리 — disconnect 후 dangling sub 방지.
    transcriptSubscriptions.clear()
    onStatusChange('DISCONNECTED')
  },

  isConnected(): boolean {
    return client?.connected ?? false
  },

  /**
   * 동적 트랜스크립트 토픽 구독 (Contract 4.5).
   * - connected 상태면 즉시 subscribe 후 핸들 저장.
   * - 미연결 상태면 ticker 만 Map 에 기록 → 다음 onConnect 에서 자동 재구독.
   * - 동일 ticker 중복 호출은 idempotent (이미 활성 sub 있으면 no-op).
   */
  subscribeTranscript(ticker: string) {
    if (!ticker) return
    const existing = transcriptSubscriptions.get(ticker)
    if (existing) return // 이미 활성 sub.

    if (client?.connected) {
      const sub = client.subscribe(
        `/topic/transcript/${ticker}`,
        transcriptMessageHandler,
      )
      transcriptSubscriptions.set(ticker, sub)
    } else {
      // 미연결 상태 — ticker 만 등록. onConnect 시점에 client.subscribe 가 호출된다.
      transcriptSubscriptions.set(ticker, undefined)
    }
  },

  /**
   * 동적 트랜스크립트 토픽 구독 해제.
   * - 활성 sub 이면 unsubscribe 호출 후 Map 제거.
   * - 미연결 상태에서 등록만 되어있던 ticker 도 Map 에서 제거.
   */
  unsubscribeTranscript(ticker: string) {
    if (!ticker) return
    const sub = transcriptSubscriptions.get(ticker)
    if (sub) {
      try {
        sub.unsubscribe()
      } catch (e) {
        console.error('[StompService] 트랜스크립트 unsubscribe 실패:', e)
      }
    }
    transcriptSubscriptions.delete(ticker)
  },
}

/**
 * 트랜스크립트 STOMP 메시지 핸들러 — 모든 ticker 가 공유.
 * 재구독 시 동일 함수 reference 를 재사용하기 위해 module-level 로 분리.
 */
function transcriptMessageHandler(message: IMessage) {
  try {
    const payload = JSON.parse(message.body)
    pushToRenderer(IPC_CHANNELS.TRANSCRIPT_SEGMENT_RECEIVED, payload)
  } catch (e) {
    console.error('[StompService] 트랜스크립트 파싱 실패:', e)
  }
}

function scheduleReconnect() {
  const delay = getRetryDelay()
  retryCount++
  onStatusChange('RECONNECTING')

  setTimeout(() => {
    if (mainState.backendToken) {
      StompService.connect()
    }
  }, delay)
}
