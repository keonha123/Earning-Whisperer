import { BrowserWindow } from 'electron'
import keytar from 'keytar'
import { mainState } from '../store/mainState'
import { KisService } from '../services/KisService'
import { kisLimiter } from '../services/KisRateLimiter'
import * as PricePoller from '../services/PricePoller'
import { IPC_CHANNELS } from '../../lib/ipcChannels'
import { IpcError } from '../../lib/types/ipcError'
import { registerHandler } from './registerHandler'
import { KisWebSocketService } from '../services/KisWebSocketService'

const KEYTAR_SERVICE = 'EarningWhisperer'
const PAPER_TRADING_KEY = 'kis-isPaperTrading'

// 모의 1.0 req/s, 실전 18 req/s — KIS 모의투자 실제 제한 1 req/s 기준.
const RATE_PAPER = 1.0
const RATE_REAL = 18

function broadcast(channel: string, payload: unknown) {
  BrowserWindow.getAllWindows().forEach((win) => {
    if (!win.isDestroyed()) win.webContents.send(channel, payload)
  })
}

export function registerSettingsHandlers() {
  registerHandler<undefined, boolean>(IPC_CHANNELS.SETTINGS_GET_PAPER_TRADING, () => {
    return mainState.isPaperTrading
  })

  registerHandler<{ value: boolean }, { ok: true; noop?: true }>(
    IPC_CHANNELS.SETTINGS_SET_PAPER_TRADING,
    async (_e, payload) => {
      // 미로그인 상태 거부 — 인증이 더 근본적이므로 다른 가드보다 먼저.
      // mainState.backendToken 이 없으면 KIS 자격증명/baseURL 전환 자체가 무의미.
      if (!mainState.backendToken) {
        throw new IpcError('AUTH_REQUIRED', '로그인이 필요합니다')
      }

      // payload value 는 strict boolean 만 허용 — 임의 truthy 값으로 모드 전환 방지
      if (typeof payload?.value !== 'boolean') {
        throw new IpcError('VALIDATION', 'paper-trading value must be boolean')
      }
      const value = payload.value

      // 주문 진행 중에는 모드 전환 거부 — 옛 baseURL/토큰으로 떠 있는 주문 보호
      if (mainState.isOrderInProgress) {
        throw new IpcError('BUSINESS_RULE', '주문 진행 중에는 모드 변경 불가')
      }

      // 동일 값 set 은 no-op — 불필요한 keytar I/O / setRate / invalidateRuntime 회피
      if (mainState.isPaperTrading === value) {
        return { ok: true, noop: true }
      }

      mainState.setPaperTrading(value)

      // 재시작 시 복원되도록 keytar에 영속화 (실패는 무시)
      try {
        await keytar.setPassword(KEYTAR_SERVICE, PAPER_TRADING_KEY, value ? '1' : '0')
      } catch (e) {
        console.warn('[settingsHandlers] paper-trading 플래그 저장 실패:', e)
      }

      // rate limit 즉시 전환 (모의 1.5 req/s ↔ 실전 18 req/s)
      kisLimiter.setRate(value ? RATE_PAPER : RATE_REAL)

      // 메모리 토큰 소거 + axios baseURL 갱신 + 자동갱신 timer 취소 + keytar 양 모드 토큰 삭제
      KisService.invalidateRuntime()

      // 옛 baseURL 로 폴링한 가격이 새 모드 화면에 잠시라도 노출되지 않도록 캐시 무효화 + 사이클 재시작
      PricePoller.clearCache()

      // WebSocket 도 함께 갈아야 한다. 자격증명(storedAppKey)은 연결 시점 모드로 고정되는데
      // 엔드포인트/TR_ID 는 호출 시점의 mainState 를 읽으므로, 끊지 않으면 재연결 때
      // 실전 키로 모의 서버에 붙는 식의 어긋난 조합이 만들어진다.
      KisWebSocketService.disconnect()
      void KisWebSocketService.connectWithStoredKey()

      broadcast(IPC_CHANNELS.SETTINGS_PAPER_TRADING_CHANGED, { value })
      return { ok: true }
    },
  )
}
