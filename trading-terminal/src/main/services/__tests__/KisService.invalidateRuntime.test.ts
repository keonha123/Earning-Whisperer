import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'

// 공유 axios mock — setup.ts 에서 vi.mock('axios') 등록.
import { kisHttpMock, flushMicrotasks } from '../../../test/setup'

import keytar from 'keytar'
import { KisService } from '../KisService'
import { mainState } from '../../store/mainState'
import { tokenIssueSuccessResponse } from '../../../test/fixtures/kisResponses'

const KEYTAR_SERVICE = 'EarningWhisperer'

async function seedApiKeys(): Promise<void> {
  // 디폴트 paper 모드 기준 slot 에 시드
  await keytar.setPassword(KEYTAR_SERVICE, 'kis-appKey-paper', 'app-key')
  await keytar.setPassword(KEYTAR_SERVICE, 'kis-appSecret-paper', 'app-secret')
}

beforeEach(() => {
  mainState.clear()
  mainState.setPaperTrading(true) // 디폴트 명시
  kisHttpMock.get.mockReset()
  kisHttpMock.post.mockReset()
  // baseURL은 test setup에서 공유 mock — 실제 axios.defaults가 아니므로
  // invalidateRuntime이 만지는 kisHttp.defaults.baseURL은 mock의 defaults에 누적된다.
  ;(kisHttpMock as any).defaults = { baseURL: '' }
})

afterEach(() => {
  vi.clearAllTimers()
  vi.useRealTimers()
})

describe('KisService.invalidateRuntime — 환경 전환 시 런타임 무효화', () => {
  it('호출 후 mainState.kisAccessToken이 null', () => {
    mainState.setKisAccessToken('valid-token', 86400)
    expect(mainState.kisAccessToken).toBe('valid-token')

    KisService.invalidateRuntime()

    expect(mainState.kisAccessToken).toBeNull()
    expect(mainState.kisTokenExpiresAt).toBeNull()
  })

  it('isPaperTrading=false 상태에서 호출 시 baseURL이 실전 URL로 변경', () => {
    mainState.setPaperTrading(false)

    KisService.invalidateRuntime()

    expect((kisHttpMock as any).defaults.baseURL).toBe('https://openapi.koreainvestment.com:9443')
  })

  it('isPaperTrading=true 상태에서 호출 시 baseURL이 모의 URL로 변경', () => {
    mainState.setPaperTrading(true)

    KisService.invalidateRuntime()

    expect((kisHttpMock as any).defaults.baseURL).toBe('https://openapivts.koreainvestment.com:29443')
  })

  it('자동갱신 timer가 cancel되어 만료 시점에 재발급 호출이 발생하지 않는다', async () => {
    await seedApiKeys()
    vi.useFakeTimers()

    // 1차 발급 → scheduleTokenRefresh가 setTimeout 등록 (82_800_000ms 뒤 갱신)
    kisHttpMock.post.mockResolvedValueOnce({ data: tokenIssueSuccessResponse })
    await KisService.issueToken()
    expect(kisHttpMock.post).toHaveBeenCalledTimes(1)

    // invalidateRuntime → refreshTimer cancel 기대
    KisService.invalidateRuntime()

    // 갱신 시점 도달해도 추가 .post 호출이 없어야 함
    await vi.advanceTimersByTimeAsync(82_800_000 + 1000)
    await flushMicrotasks()

    expect(kisHttpMock.post).toHaveBeenCalledTimes(1) // 1차 발급만, 자동갱신 없음
  })

  it('주문 진행 중 호출 시 무시한다 (axios abort 로 인한 콜백 누락 방지)', () => {
    mainState.setOrderInProgress(true)
    mainState.setKisAccessToken('valid-token', 86400)

    KisService.invalidateRuntime()

    // 토큰/타이머 그대로 유지되어야 함
    expect(mainState.kisAccessToken).toBe('valid-token')
    mainState.setOrderInProgress(false)
  })

  it('keytar 양 모드 토큰을 보존한다 (옛 모드 활성화 시 재사용 가능)', async () => {
    // A2: invalidateRuntime 은 메모리 토큰/timer/in-flight 만 reset, keytar 토큰은 보존.
    // 옛 모드 axios resolve 가 새 모드 mainState 에 박히는 race 는 modeChangedSince 가드가 차단하므로
    // keytar 까지 지울 필요 없음 — 사용자가 다시 옛 모드로 돌아왔을 때 그 토큰 재사용 가능.
    await keytar.setPassword(KEYTAR_SERVICE, 'kis-accessToken-paper', 'paper-token')
    await keytar.setPassword(KEYTAR_SERVICE, 'kis-tokenExpiresAt-paper', String(Date.now() + 86400_000))
    await keytar.setPassword(KEYTAR_SERVICE, 'kis-accessToken-real', 'real-token')
    await keytar.setPassword(KEYTAR_SERVICE, 'kis-tokenExpiresAt-real', String(Date.now() + 86400_000))

    KisService.invalidateRuntime()
    await flushMicrotasks()

    // 양 모드 토큰 모두 그대로 보존되어야 함
    expect(await keytar.getPassword(KEYTAR_SERVICE, 'kis-accessToken-paper')).toBe('paper-token')
    expect(await keytar.getPassword(KEYTAR_SERVICE, 'kis-accessToken-real')).toBe('real-token')
  })
})
