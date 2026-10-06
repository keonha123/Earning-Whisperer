import { Client, type IMessage, type StompSubscription } from '@stomp/stompjs'
import WebSocket from 'ws'
import { BrowserWindow } from 'electron'
import { mainState } from '../store/mainState'
import { IPC_CHANNELS } from '../../lib/ipcChannels'
import { BackendClient } from './BackendClient'
import { NotificationService } from './NotificationService'
import { markStompCovered, clearStompCovered } from './PricePoller'

const WS_URL = (process.env.BACKEND_URL ?? 'http://localhost:8082')
  .replace(/^http/, 'ws') + '/ws-native'

type WsStatus = 'DISCONNECTED' | 'CONNECTING' | 'CONNECTED' | 'RECONNECTING'

let client: Client | null = null
let retryCount = 0
let hasConnectedOnce = false
/** 예약된 재연결 타이머 핸들 — 동시 장애 콜백이 타이머를 중첩 예약하는 것을 막는다. */
let reconnectTimer: ReturnType<typeof setTimeout> | null = null
/** disconnect() 로 의도적으로 끊은 상태 — 이때 오는 소켓 종료 콜백은 재연결 대상이 아니다. */
let intentionalDisconnect = false
const RETRY_DELAYS = [2000, 4000, 8000, 16000, 30000]

/**
 * 활성 트랜스크립트 구독 핸들 — ticker 별 1개.
 * 재연결 시 onConnect 에서 동일 ticker 들을 자동 재구독한다.
 *  - 키: ticker (예: "NVDA")
 *  - 값: STOMP subscription handle (활성), 또는 undefined (미연결 상태에서 sub 요청만 기록)
 */
const transcriptSubscriptions = new Map<string, StompSubscription | undefined>()
const factCheckSubscriptions = new Map<string, StompSubscription | undefined>()

/** 종합 판단 구독 핸들 (Contract 4.7). 위 두 Map 과 동일한 규약. */
const evaluationSubscriptions = new Map<string, StompSubscription | undefined>()

/** 직전 콜 대조 구독 핸들. 위 Map 들과 동일한 규약. */
const transcriptDiffSubscriptions = new Map<string, StompSubscription | undefined>()

/** 자막 번역 구독 핸들 (Contract 4.8). 위 Map 들과 동일한 규약. */
const transcriptTranslationSubscriptions = new Map<string, StompSubscription | undefined>()

function getRetryDelay(): number {
  return RETRY_DELAYS[Math.min(retryCount, RETRY_DELAYS.length - 1)]
}

/**
 * 백엔드가 인증 실패로 연결을 거부할 때 ERROR 프레임에 싣는 문구.
 * `StompJwtChannelInterceptor` 가 던지는 메시지와 같아야 한다.
 */
const STOMP_AUTH_ERROR = 'STOMP 인증 실패'

/**
 * 이번 인증 실패에 대해 토큰을 이미 갱신했는지. 연결에 성공하면 되돌린다.
 *
 * 갱신에 성공했다는 것은 refresh token 이 멀쩡하다는 뜻일 뿐, 새 액세스 토큰이 통과한다는
 * 보장이 아니다. 서버의 JWT 비밀키가 바뀌었거나 시계가 어긋나 있으면 갱신한 토큰도 거부된다.
 * 그때 다시 갱신하면 지연 없는 재연결이 계속 돌아 자기 백엔드를 두드리게 되고, refresh token
 * 이 매번 회전하다 재사용 탐지로 강제 로그아웃되는 것 말고는 멈출 방법이 없다.
 */
let refreshedForAuthFailure = false

/**
 * 액세스 토큰을 갱신한 뒤 재연결한다.
 *
 * 갱신이 최종 실패하면(refresh token 무효) `BackendClient` 가 세션 정리 절차를 태우고
 * `mainState.backendToken` 이 비워진다. 그러면 `scheduleReconnect` 의 타이머가 깨어나도
 * 연결을 시도하지 않으므로 루프가 멈춘다. 일시적 실패라면 다음 주기에 다시 시도한다.
 */
function reconnectWithRefreshedToken(): void {
  BackendClient.refreshSession()
    .then(() => {
      // 갱신 도중 사용자가 로그아웃했으면 다시 붙지 않는다
      if (intentionalDisconnect) return
      // 갱신에 성공했으니 지연 없이 바로 붙는다. retryCount 는 onConnect 에서 되돌린다
      StompService.connect()
    })
    .catch((e) => {
      console.error('[StompService] 인증 실패 후 토큰 갱신 실패:', e)
      /*
       * 갱신이 최종 실패하면 BackendClient 가 세션을 정리해 backendToken 을 비운다.
       * 그 상태에서 RECONNECTING 을 띄우면 다시는 붙지 않는데 화면만 재연결 중으로 남는다.
       */
      if (!mainState.backendToken) {
        onStatusChange('DISCONNECTED')
        return
      }
      scheduleReconnect()
    })
}

function pushToRenderer(channel: string, payload: unknown) {
  BrowserWindow.getAllWindows().forEach((win) => {
    if (!win.isDestroyed()) win.webContents.send(channel, payload)
  })
}

function onStatusChange(status: WsStatus) {
  pushToRenderer(IPC_CHANNELS.WS_STATUS_CHANGED, { status })

  if (status === 'CONNECTED') {
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

    intentionalDisconnect = false
    if (reconnectTimer) {
      clearTimeout(reconnectTimer)
      reconnectTimer = null
    }

    /*
     * CONNECTING 상태로 남아있는 옛 client 를 정리한 뒤 교체한다.
     * 정리하지 않으면 뒤늦게 연결된 옛 client 가 동일 토픽을 이중 구독해
     * 같은 신호가 2회 dispatch 된다.
     */
    if (client) {
      const stale = client
      client = null
      try {
        stale.deactivate()
      } catch (e) {
        console.error('[StompService] 이전 client deactivate 실패:', e)
      }
    }

    onStatusChange('CONNECTING')

    /*
     * 생성한 인스턴스를 로컬로 잡아둔다. 교체된 옛 client 의 소켓이 뒤늦게 닫히면
     * 라이브러리가 그 client 의 콜백을 그대로 호출하므로, 모든 콜백 첫 줄에서
     * "내가 현재 client 인가" 를 확인해 유령 이벤트를 무시한다.
     */
    const created: Client = new Client({
      webSocketFactory: () => new WebSocket(WS_URL) as unknown as globalThis.WebSocket,
      connectHeaders: { Authorization: `Bearer ${token}` },
      heartbeatIncoming: 10000,
      heartbeatOutgoing: 10000,
      reconnectDelay: 0, // 직접 관리

      onConnect: () => {
        if (client !== created) return
        retryCount = 0
        refreshedForAuthFailure = false
        onStatusChange('CONNECTED')

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
              const priceUpdate: Record<string, number> = {}
              for (const u of batch) priceUpdate[u.ticker] = u.currentPrice
              mainState.updatePricesCache(priceUpdate)
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
        for (const ticker of factCheckSubscriptions.keys()) {
          const sub = client!.subscribe(
            `/topic/factcheck/${ticker}`,
            factCheckMessageHandler,
          )
          factCheckSubscriptions.set(ticker, sub)
        }
        for (const ticker of evaluationSubscriptions.keys()) {
          const sub = client!.subscribe(
            `/topic/evaluation/${ticker}`,
            evaluationMessageHandler,
          )
          evaluationSubscriptions.set(ticker, sub)
        }
        for (const ticker of transcriptDiffSubscriptions.keys()) {
          const sub = client!.subscribe(
            `/topic/transcript-diff/${ticker}`,
            transcriptDiffMessageHandler,
          )
          transcriptDiffSubscriptions.set(ticker, sub)
        }
        for (const ticker of transcriptTranslationSubscriptions.keys()) {
          const sub = client!.subscribe(
            `/topic/transcript-translation/${ticker}`,
            transcriptTranslationMessageHandler,
          )
          transcriptTranslationSubscriptions.set(ticker, sub)
        }
      },

      onDisconnect: () => {
        if (client !== created) return
        clearStompCovered()
        onStatusChange('DISCONNECTED')
        scheduleReconnect()
      },

      onStompError: (frame) => {
        if (client !== created) return
        // frame 전체를 찍으면 헤더의 인증 토큰이 로그에 남는다 — 메시지만 남긴다
        const reason = frame.headers?.message
        console.error('[StompService] STOMP 에러:', reason)
        clearStompCovered()
        onStatusChange('DISCONNECTED')

        /*
         * 서버가 인증 실패로 끊은 경우, 같은 토큰으로 다시 붙어 봐야 똑같이 거부당한다.
         * 액세스 토큰 수명이 15분이라 그대로 두면 30초 간격으로 영원히 실패한다.
         * REST 쪽 401 재시도 경로는 STOMP ERROR 프레임을 보지 못하므로 여기서 직접 갱신한다.
         */
        if (reason === STOMP_AUTH_ERROR) {
          if (refreshedForAuthFailure) {
            // 갱신한 토큰으로도 거부당했다 — 토큰 문제가 아니므로 갱신을 반복하지 않는다
            console.error('[StompService] 토큰을 갱신해도 인증이 거부된다 — 백오프로 전환한다')
            scheduleReconnect()
            return
          }
          refreshedForAuthFailure = true
          reconnectWithRefreshedToken()
          return
        }

        scheduleReconnect()
      },

      onWebSocketError: (event) => {
        if (client !== created) return
        console.error('[StompService] WebSocket 연결 오류:', event)
        onStatusChange('RECONNECTING')
        scheduleReconnect()
      },

      /*
       * 서버가 소켓을 닫은 경우(백엔드 재배포, heartbeat timeout 등)는 onDisconnect 가
       * 아니라 onWebSocketClose 로만 통보된다. 이를 처리하지 않으면 UI 가 CONNECTED 로
       * 남은 채 재연결도 되지 않는다.
       */
      onWebSocketClose: (event) => {
        if (client !== created) return
        console.warn('[StompService] WebSocket 종료:', event?.code, event?.reason)
        clearStompCovered()
        onStatusChange('DISCONNECTED')
        scheduleReconnect()
      },
    })

    client = created
    created.activate()
  },

  disconnect() {
    intentionalDisconnect = true
    if (reconnectTimer) {
      clearTimeout(reconnectTimer)
      reconnectTimer = null
    }
    client?.deactivate()
    client = null
    retryCount = 0
    // 트랜스크립트 핸들도 함께 정리 — disconnect 후 dangling sub 방지.
    transcriptSubscriptions.clear()
    factCheckSubscriptions.clear()
    transcriptDiffSubscriptions.clear()
    transcriptTranslationSubscriptions.clear()
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

  /**
   * 동적 팩트체크 토픽 구독 (Contract 4.6).
   * subscribeTranscript 와 동일한 규약 — 미연결 시 ticker 만 기록해 두고
   * 다음 onConnect 에서 자동 재구독한다.
   */
  subscribeFactCheck(ticker: string) {
    if (!ticker) return
    if (factCheckSubscriptions.get(ticker)) return

    if (client?.connected) {
      const sub = client.subscribe(`/topic/factcheck/${ticker}`, factCheckMessageHandler)
      factCheckSubscriptions.set(ticker, sub)
    } else {
      factCheckSubscriptions.set(ticker, undefined)
    }
  },

  unsubscribeFactCheck(ticker: string) {
    if (!ticker) return
    const sub = factCheckSubscriptions.get(ticker)
    if (sub) {
      try {
        sub.unsubscribe()
      } catch (e) {
        console.error('[StompService] 팩트체크 unsubscribe 실패:', e)
      }
    }
    factCheckSubscriptions.delete(ticker)
  },

  /**
   * 동적 직전 콜 대조 토픽 구독.
   * subscribeFactCheck 와 동일한 규약 — 미연결 시 ticker 만 기록해 두고
   * 다음 onConnect 에서 자동 재구독한다.
   */
  subscribeTranscriptDiff(ticker: string) {
    if (!ticker) return
    if (transcriptDiffSubscriptions.get(ticker)) return

    if (client?.connected) {
      const sub = client.subscribe(`/topic/transcript-diff/${ticker}`, transcriptDiffMessageHandler)
      transcriptDiffSubscriptions.set(ticker, sub)
    } else {
      transcriptDiffSubscriptions.set(ticker, undefined)
    }
  },

  unsubscribeTranscriptDiff(ticker: string) {
    if (!ticker) return
    const sub = transcriptDiffSubscriptions.get(ticker)
    if (sub) {
      try {
        sub.unsubscribe()
      } catch (e) {
        console.error('[StompService] 직전 콜 대조 unsubscribe 실패:', e)
      }
    }
    transcriptDiffSubscriptions.delete(ticker)
  },

  /**
   * 동적 자막 번역 토픽 구독 (Contract 4.8).
   * subscribeTranscriptDiff 와 동일한 규약 — 미연결 시 ticker 만 기록해 두고
   * 다음 onConnect 에서 자동 재구독한다.
   */
  subscribeTranscriptTranslation(ticker: string) {
    if (!ticker) return
    if (transcriptTranslationSubscriptions.get(ticker)) return

    if (client?.connected) {
      const sub = client.subscribe(
        `/topic/transcript-translation/${ticker}`,
        transcriptTranslationMessageHandler,
      )
      transcriptTranslationSubscriptions.set(ticker, sub)
    } else {
      transcriptTranslationSubscriptions.set(ticker, undefined)
    }
  },

  unsubscribeTranscriptTranslation(ticker: string) {
    if (!ticker) return
    const sub = transcriptTranslationSubscriptions.get(ticker)
    if (sub) {
      try {
        sub.unsubscribe()
      } catch (e) {
        console.error('[StompService] 자막 번역 unsubscribe 실패:', e)
      }
    }
    transcriptTranslationSubscriptions.delete(ticker)
  },

  /**
   * 동적 종합 판단 토픽 구독 (Contract 4.7).
   * subscribeFactCheck 와 동일한 규약 — 미연결 시 ticker 만 기록해 두고
   * 다음 onConnect 에서 자동 재구독한다.
   *
   * 이 토픽은 어닝콜 회차당 1건만 흐른다. 그래서 구독이 늦으면 그 1건을 통째로
   * 놓친다 — 재생 시작 버튼을 누르기 전에 이미 구독되어 있어야 한다.
   */
  subscribeEvaluation(ticker: string) {
    if (!ticker) return
    if (evaluationSubscriptions.get(ticker)) return

    if (client?.connected) {
      const sub = client.subscribe(`/topic/evaluation/${ticker}`, evaluationMessageHandler)
      evaluationSubscriptions.set(ticker, sub)
    } else {
      evaluationSubscriptions.set(ticker, undefined)
    }
  },

  unsubscribeEvaluation(ticker: string) {
    if (!ticker) return
    const sub = evaluationSubscriptions.get(ticker)
    if (sub) {
      try {
        sub.unsubscribe()
      } catch (e) {
        console.error('[StompService] 종합 판단 unsubscribe 실패:', e)
      }
    }
    evaluationSubscriptions.delete(ticker)
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

/**
 * 팩트체크 STOMP 메시지 핸들러 — 모든 ticker 가 공유.
 * transcriptMessageHandler 와 동일한 이유로 module-level 에 둔다(재구독 시 동일 reference).
 */
function factCheckMessageHandler(message: IMessage) {
  try {
    const payload = JSON.parse(message.body)
    pushToRenderer(IPC_CHANNELS.FACTCHECK_BATCH_RECEIVED, payload)
  } catch (e) {
    console.error('[StompService] 팩트체크 파싱 실패:', e)
  }
}

/** 직전 콜 대조 STOMP 메시지 핸들러 — 위와 동일한 이유로 module-level 에 둔다. */
function transcriptDiffMessageHandler(message: IMessage) {
  try {
    const payload = JSON.parse(message.body)
    pushToRenderer(IPC_CHANNELS.TRANSCRIPT_DIFF_RECEIVED, payload)
  } catch (e) {
    console.error('[StompService] 직전 콜 대조 파싱 실패:', e)
  }
}

/** 자막 번역 STOMP 메시지 핸들러 — 위와 동일한 이유로 module-level 에 둔다. */
function transcriptTranslationMessageHandler(message: IMessage) {
  try {
    const payload = JSON.parse(message.body)
    pushToRenderer(IPC_CHANNELS.TRANSCRIPT_TRANSLATION_RECEIVED, payload)
  } catch (e) {
    console.error('[StompService] 자막 번역 파싱 실패:', e)
  }
}

/** 종합 판단 STOMP 메시지 핸들러 — 위 둘과 동일한 이유로 module-level 에 둔다. */
function evaluationMessageHandler(message: IMessage) {
  try {
    const payload = JSON.parse(message.body)
    pushToRenderer(IPC_CHANNELS.EVALUATION_RECEIVED, payload)
  } catch (e) {
    console.error('[StompService] 종합 판단 파싱 실패:', e)
  }
}

/**
 * 재연결 예약 — 타이머 핸들 1개만 유지한다.
 * 같은 장애로 onStompError / onWebSocketError / onWebSocketClose 가 연달아 호출돼도
 * 타이머가 중첩되지 않아 client 가 2개 생성되는 이중 구독을 막는다.
 */
function scheduleReconnect() {
  if (intentionalDisconnect) return
  if (reconnectTimer) return

  const delay = getRetryDelay()
  retryCount++
  onStatusChange('RECONNECTING')

  reconnectTimer = setTimeout(() => {
    reconnectTimer = null
    if (mainState.backendToken) {
      StompService.connect()
    }
  }, delay)
}
