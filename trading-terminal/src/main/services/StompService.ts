import { Client, type IMessage } from '@stomp/stompjs'
import WebSocket from 'ws'
import { BrowserWindow } from 'electron'
import { mainState } from '../store/mainState'
import { IPC_CHANNELS } from '../../lib/ipcChannels'
import { TradeExecutor } from './TradeExecutor'
import { NotificationService } from './NotificationService'

const WS_URL = (process.env.BACKEND_URL ?? 'http://localhost:8082')
  .replace(/^http/, 'ws') + '/ws-native'

type WsStatus = 'DISCONNECTED' | 'CONNECTING' | 'CONNECTED' | 'RECONNECTING'

let client: Client | null = null
let retryCount = 0
let hasConnectedOnce = false
const RETRY_DELAYS = [2000, 4000, 8000, 16000, 30000]

function getRetryDelay(): number {
  return RETRY_DELAYS[Math.min(retryCount, RETRY_DELAYS.length - 1)]
}

function pushToRenderer(channel: string, payload: unknown) {
  BrowserWindow.getAllWindows().forEach((win) => {
    if (!win.isDestroyed()) win.webContents.send(channel, payload)
  })
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
              const signal = JSON.parse(message.body)
              pushToRenderer(IPC_CHANNELS.SIGNAL_RECEIVED, signal)

              // AUTO_PILOT: 신호 수신 즉시 자동 실행
              if (mainState.tradingMode === 'AUTO_PILOT') {
                TradeExecutor.execute(signal).catch((e) => {
                  console.error('[StompService] AUTO_PILOT 실행 실패:', e)
                })
              }
            } catch (e) {
              console.error('[StompService] 신호 파싱 실패:', e)
            }
          },
        )
      },

      onDisconnect: () => {
        onStatusChange('DISCONNECTED')
        scheduleReconnect()
      },

      onStompError: (frame) => {
        console.error('[StompService] STOMP 에러:', frame)
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
    onStatusChange('DISCONNECTED')
  },

  isConnected(): boolean {
    return client?.connected ?? false
  },
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
