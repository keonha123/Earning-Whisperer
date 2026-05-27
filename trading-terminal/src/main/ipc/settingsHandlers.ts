import { BrowserWindow } from 'electron'
import keytar from 'keytar'
import { mainState } from '../store/mainState'
import { BackendClient } from '../services/BackendClient'
import { KisService } from '../services/KisService'
import { kisLimiter } from '../services/KisRateLimiter'
import * as PricePoller from '../services/PricePoller'
import { IPC_CHANNELS } from '../../lib/ipcChannels'
import { IpcError } from '../../lib/types/ipcError'
import { registerHandler } from './registerHandler'

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

interface SettingsUpdatePayload {
  tradingMode: 'MANUAL' | 'SEMI_AUTO' | 'AUTO_PILOT'
  maxBuyRatio: number
  maxHoldingRatio: number
  cooldownMinutes: number
  aiScoreThreshold: number
}

export function registerSettingsHandlers() {
  registerHandler<SettingsUpdatePayload, void>(IPC_CHANNELS.SETTINGS_UPDATE, async (_e, settings) => {
    // Main 모드 캐시 업데이트
    if (settings.tradingMode) {
      // 진행 중인 주문이 없을 때만 전환
      if (!mainState.isOrderInProgress) {
        mainState.setTradingMode(settings.tradingMode)
      }
    }
    // 백엔드 동기화 — 토큰 만료/네트워크 오류 시에도 로컬 모드 변경은 유지
    try {
      await BackendClient.updateSettings({
        trading_mode: settings.tradingMode,
        max_buy_ratio: settings.maxBuyRatio,
        max_holding_ratio: settings.maxHoldingRatio,
        cooldown_minutes: settings.cooldownMinutes,
        ai_score_threshold: settings.aiScoreThreshold,
      })
    } catch (e) {
      console.warn('[settingsHandlers] 백엔드 모드 동기화 실패 (로컬 적용 유지):', e)
    }
  })

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

      broadcast(IPC_CHANNELS.SETTINGS_PAPER_TRADING_CHANGED, { value })
      return { ok: true }
    },
  )
}
