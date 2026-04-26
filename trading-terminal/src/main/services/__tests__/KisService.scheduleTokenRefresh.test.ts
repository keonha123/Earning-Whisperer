import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'

// 공유 axios mock + flushMicrotasks 헬퍼 — setup.ts에서 vi.mock('axios')로 등록.
import { kisHttpMock, flushMicrotasks } from '../../../test/setup'

import keytar from 'keytar'
import { KisService } from '../KisService'
import { mainState } from '../../store/mainState'
import { tokenIssueSuccessResponse } from '../../../test/fixtures/kisResponses'

const KEYTAR_SERVICE = 'EarningWhisperer'

async function seedApiKeys(): Promise<void> {
  await keytar.setPassword(KEYTAR_SERVICE, 'kis-appKey', 'app-key')
  await keytar.setPassword(KEYTAR_SERVICE, 'kis-appSecret', 'app-secret')
}

beforeEach(() => {
  mainState.clear()
  kisHttpMock.get.mockReset()
  kisHttpMock.post.mockReset()
})

afterEach(() => {
  // 자동갱신 setTimeout 누수 방지 — fake timer 큐를 먼저 비우고 real timer로 복귀
  vi.clearAllTimers()
  vi.useRealTimers()
})

/**
 * scheduleTokenRefresh는 module-private 함수이므로 issueToken 호출을 통해 간접 검증한다.
 * 토큰 발급 → 만료 1시간 전 setTimeout 등록 → 시간 진행 시 재발급 확인.
 */
describe('scheduleTokenRefresh — 만료 1시간 전 갱신', () => {
  it('expiresIn=86400 → (86400-3600)*1000ms 뒤 issueToken 재호출', async () => {
    await seedApiKeys()
    kisHttpMock.post.mockResolvedValue({ data: tokenIssueSuccessResponse })

    vi.useFakeTimers()

    await KisService.issueToken()
    expect(kisHttpMock.post).toHaveBeenCalledTimes(1)

    // (86400 - 3600) * 1000 = 82_800_000ms 직전엔 호출 안 됨
    await vi.advanceTimersByTimeAsync(82_800_000 - 1)
    expect(kisHttpMock.post).toHaveBeenCalledTimes(1)

    // 정확히 그 시각에 재호출
    await vi.advanceTimersByTimeAsync(1)
    expect(kisHttpMock.post).toHaveBeenCalledTimes(2)
  })

  it('expiresIn=100 → 최소 60_000ms 보장 후 호출', async () => {
    await seedApiKeys()
    kisHttpMock.post.mockResolvedValue({
      data: { ...tokenIssueSuccessResponse, expires_in: 100 },
    })

    vi.useFakeTimers()

    await KisService.issueToken()
    expect(kisHttpMock.post).toHaveBeenCalledTimes(1)

    // 60초 전엔 미호출
    await vi.advanceTimersByTimeAsync(59_999)
    expect(kisHttpMock.post).toHaveBeenCalledTimes(1)

    // 60초 시점에 호출
    await vi.advanceTimersByTimeAsync(1)
    expect(kisHttpMock.post).toHaveBeenCalledTimes(2)
  })

  it('갱신 1차 실패 시 360초 뒤 재시도된다 (단계 분리 검증)', async () => {
    // 토큰 발급(expiresIn=86400) → 자동갱신 시점은 (86400-3600)*1000 = 82,800,000ms
    await seedApiKeys()
    vi.useFakeTimers()

    // 1단계: 1차 발급 성공
    kisHttpMock.post.mockResolvedValueOnce({ data: tokenIssueSuccessResponse })
    // issueToken은 fake timer 환경이라도 axios mock이 동기-resolve이므로
    // 이 await만으로 in-flight가 종료되고 scheduleTokenRefresh의 setTimeout이 등록된다
    await KisService.issueToken()
    expect(kisHttpMock.post).toHaveBeenCalledTimes(1)

    // 2단계: 자동갱신 시점 도달 → 갱신 실패 (catch에서 scheduleTokenRefresh(360) 재등록)
    kisHttpMock.post.mockRejectedValueOnce(new Error('갱신 실패'))
    await vi.advanceTimersByTimeAsync(82_800_000)
    await flushMicrotasks() // catch 핸들러가 setTimeout 등록할 수 있도록 마이크로태스크 흘림
    expect(kisHttpMock.post).toHaveBeenCalledTimes(2) // 발급 + 1차 갱신

    // 3단계: 360초 후 재시도 발화 — 성공
    kisHttpMock.post.mockResolvedValueOnce({ data: tokenIssueSuccessResponse })
    await vi.advanceTimersByTimeAsync(360_000)
    await flushMicrotasks()
    expect(kisHttpMock.post).toHaveBeenCalledTimes(3) // + 재시도 성공
  })

  it('1시간 직전엔 갱신 미발생', async () => {
    await seedApiKeys()
    kisHttpMock.post.mockResolvedValue({ data: tokenIssueSuccessResponse })

    vi.useFakeTimers()

    await KisService.issueToken()
    expect(kisHttpMock.post).toHaveBeenCalledTimes(1)

    // 갱신 시점 1ms 직전까지 진행
    await vi.advanceTimersByTimeAsync(82_800_000 - 1)
    expect(kisHttpMock.post).toHaveBeenCalledTimes(1)
  })

  it('issueToken을 두 번 연속 호출하면 자동갱신 timer가 1개만 유지된다 (clearTimeout 동작)', async () => {
    // scheduleTokenRefresh 내부 `if (refreshTimer) clearTimeout(refreshTimer)` 의 회귀 보호.
    // 만약 이전 timer가 안 클리어되면 자동갱신 시점에 .post가 두 번 호출되어 4회가 된다.
    await seedApiKeys()
    vi.useFakeTimers()

    // 1차 발급(expiresIn=86400)
    kisHttpMock.post.mockResolvedValueOnce({ data: tokenIssueSuccessResponse })
    await KisService.issueToken()

    // 2차 발급(어떤 이유로 재발급, in-flight 종료 후 새 호출 — 새 timer 등록 + 기존 timer clear)
    kisHttpMock.post.mockResolvedValueOnce({ data: tokenIssueSuccessResponse })
    await KisService.issueToken()
    expect(kisHttpMock.post).toHaveBeenCalledTimes(2)

    // 자동갱신 시점 도달 — 살아있는 timer가 1개라면 .post는 1번만 추가 호출
    kisHttpMock.post.mockResolvedValueOnce({ data: tokenIssueSuccessResponse })
    await vi.advanceTimersByTimeAsync(82_800_000)
    await flushMicrotasks()

    // 발급 2회 + 자동갱신 1회 = 3회. 만약 4회면 1차 timer가 살아있던 것.
    expect(kisHttpMock.post).toHaveBeenCalledTimes(3)
  })
})
