import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'

// 공유 axios mock — setup.ts에서 vi.mock('axios')로 등록되어 있다.
// 이 import는 vi.hoisted()와 동일한 호이스팅 효과를 가진다 (top-level vi.mock이 setup.ts에 있음).
import { kisHttpMock } from '../../../test/setup'

import keytar from 'keytar'
import { KisService } from '../KisService'
import { mainState } from '../../store/mainState'
import {
  tokenIssueSuccessResponse,
  tokenIssueRateLimitErrorResponse,
  buildAxiosError,
} from '../../../test/fixtures/kisResponses'

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
  // scheduleTokenRefresh가 setTimeout을 남길 수 있으므로 정리.
  // clearAllTimers를 useRealTimers 이전에 호출해 fake timer 큐의 핸들도 같이 비운다.
  vi.clearAllTimers()
  vi.useRealTimers()
})

describe('KisService.issueToken — 정상 흐름', () => {
  it('정상: mainState.setKisAccessToken 호출 + keytar 저장', async () => {
    await seedApiKeys()
    kisHttpMock.post.mockResolvedValueOnce({ data: tokenIssueSuccessResponse })

    // scheduleTokenRefresh가 즉시 실행되지 않도록 fake timer 사용
    vi.useFakeTimers()

    await KisService.issueToken()

    expect(mainState.kisAccessToken).toBe('mocked.access.token')
    expect(mainState.isKisTokenValid()).toBe(true)

    // keytar에 저장됐는지 확인 — 디폴트 모의 환경 → paper 키
    const stored = await keytar.getPassword(KEYTAR_SERVICE, 'kis-accessToken-paper')
    expect(stored).toBe('mocked.access.token')

    const expiresAtStr = await keytar.getPassword(KEYTAR_SERVICE, 'kis-tokenExpiresAt-paper')
    expect(expiresAtStr).not.toBeNull()
    expect(Number(expiresAtStr)).toBeGreaterThan(Date.now())
  })

  it('API 키 미등록 시 throw', async () => {
    // appKey/appSecret 없음
    await expect(KisService.issueToken()).rejects.toThrow(/KIS API 키가 등록되지 않았/)
  })
})

describe('KisService.issueToken — EGW00133 fallback', () => {
  it('EGW00133 + 저장 토큰 잔여 ≥ 600초 → fallback 성공 (throw 안 함)', async () => {
    await seedApiKeys()

    // keytar에 잔여 1시간짜리 토큰 미리 저장
    const futureExpire = Date.now() + 3600 * 1000
    await keytar.setPassword(KEYTAR_SERVICE, 'kis-accessToken-paper', 'restored-token')
    await keytar.setPassword(KEYTAR_SERVICE, 'kis-tokenExpiresAt-paper', String(futureExpire))

    kisHttpMock.post.mockRejectedValueOnce(buildAxiosError(tokenIssueRateLimitErrorResponse))

    vi.useFakeTimers()

    // throw 안 해야 함
    await expect(KisService.issueToken()).resolves.toBeUndefined()

    expect(mainState.kisAccessToken).toBe('restored-token')
    expect(mainState.isKisTokenValid()).toBe(true)
  })

  it('EGW00133 + 저장 토큰 잔여 < 600초 → fallback 거부, 원본 에러 throw', async () => {
    await seedApiKeys()

    // 잔여 5분짜리 토큰 (300초)
    const expireSoon = Date.now() + 300 * 1000
    await keytar.setPassword(KEYTAR_SERVICE, 'kis-accessToken-paper', 'expiring-token')
    await keytar.setPassword(KEYTAR_SERVICE, 'kis-tokenExpiresAt-paper', String(expireSoon))

    kisHttpMock.post.mockRejectedValueOnce(buildAxiosError(tokenIssueRateLimitErrorResponse))

    await expect(KisService.issueToken()).rejects.toThrow()
    // mainState는 갱신되지 않아야 함
    expect(mainState.kisAccessToken).toBeNull()
  })

  it('EGW00133 + 저장 토큰 없음 → 원본 에러 throw', async () => {
    await seedApiKeys()
    // keytar에 토큰 없음
    kisHttpMock.post.mockRejectedValueOnce(buildAxiosError(tokenIssueRateLimitErrorResponse))

    await expect(KisService.issueToken()).rejects.toThrow()
    expect(mainState.kisAccessToken).toBeNull()
  })
})

describe('KisService.issueToken — 동시 호출 차단', () => {
  it('동시 issueToken 두 번 → axios.post는 1번만', async () => {
    await seedApiKeys()

    // 첫 호출은 실제로 보류 → 두 번째 호출이 in-flight를 잡는지 검증
    let resolveTokenIssue: (v: { data: typeof tokenIssueSuccessResponse }) => void = () => {}
    kisHttpMock.post.mockImplementationOnce(
      () =>
        new Promise<{ data: typeof tokenIssueSuccessResponse }>((resolve) => {
          resolveTokenIssue = resolve
        }),
    )

    // real timer 유지 (마이크로태스크 큐 정상 동작)
    const p1 = KisService.issueToken()
    const p2 = KisService.issueToken()

    // axios.post 호출이 등록될 때까지 마이크로태스크 한 번 흘려보냄
    await Promise.resolve()
    await Promise.resolve()

    resolveTokenIssue({ data: tokenIssueSuccessResponse })
    await Promise.all([p1, p2])

    expect(kisHttpMock.post).toHaveBeenCalledTimes(1)
  })
})

describe('KisService.loadSavedToken (loadTokenFromVault)', () => {
  it('잔여 60초 미만 → false 반환, mainState 미갱신', async () => {
    // 30초만 남은 토큰
    const expireSoon = Date.now() + 30 * 1000
    await keytar.setPassword(KEYTAR_SERVICE, 'kis-accessToken-paper', 'about-to-expire')
    await keytar.setPassword(KEYTAR_SERVICE, 'kis-tokenExpiresAt-paper', String(expireSoon))

    const ok = await KisService.loadSavedToken()

    expect(ok).toBe(false)
    expect(mainState.kisAccessToken).toBeNull()
  })

  it('정상 잔여 → true + mainState 갱신', async () => {
    const futureExpire = Date.now() + 3600 * 1000
    await keytar.setPassword(KEYTAR_SERVICE, 'kis-accessToken-paper', 'good-token')
    await keytar.setPassword(KEYTAR_SERVICE, 'kis-tokenExpiresAt-paper', String(futureExpire))

    vi.useFakeTimers()

    const ok = await KisService.loadSavedToken()

    expect(ok).toBe(true)
    expect(mainState.kisAccessToken).toBe('good-token')
    expect(mainState.isKisTokenValid()).toBe(true)
  })

  it('keytar에 토큰 없음 → false', async () => {
    const ok = await KisService.loadSavedToken()
    expect(ok).toBe(false)
  })
})

describe('KisService.getTokenStatus', () => {
  it('토큰 유효 시 isValid=true', () => {
    mainState.setKisAccessToken('x', 86400)
    const status = KisService.getTokenStatus()
    expect(status.isValid).toBe(true)
    expect(status.expiresAt).toBeGreaterThan(Date.now())
  })

  it('토큰 없음 → isValid=false, expiresAt=null', () => {
    mainState.clear()
    const status = KisService.getTokenStatus()
    expect(status.isValid).toBe(false)
    expect(status.expiresAt).toBeNull()
  })
})

/**
 * loadTokenFromVault 분기는 `if (remainingSec < 60) return false`.
 * Math.floor((expiresAt - Date.now()) / 1000) 결과가 정확히 60이면 통과(true).
 * milliseconds → seconds floor 변환의 부동소수 함정 박제.
 */
describe('KisService.loadSavedToken — 잔여시간 경계 (60초 보더)', () => {
  // fake timer로 시간 고정 — Date.now()를 실시간 측정하면 ms 단위 race로
  // floor 결과가 흔들려 경계값 검증이 불안정해진다.
  it('잔여 정확히 60초 → true (>= 60)', async () => {
    vi.useFakeTimers()
    const fixedNow = vi.getMockedSystemTime()?.valueOf() ?? Date.now()
    // expiresAt = now + 60_000 → remainingSec = floor((expiresAt - now)/1000) = 60 (>= 60)
    const expiresAt = fixedNow + 60_000
    await keytar.setPassword(KEYTAR_SERVICE, 'kis-accessToken-paper', 'edge-60s')
    await keytar.setPassword(KEYTAR_SERVICE, 'kis-tokenExpiresAt-paper', String(expiresAt))

    const ok = await KisService.loadSavedToken()

    expect(ok).toBe(true)
    expect(mainState.kisAccessToken).toBe('edge-60s')
  })

  it('잔여 59초(=59_000ms) → false (< 60)', async () => {
    vi.useFakeTimers()
    const fixedNow = vi.getMockedSystemTime()?.valueOf() ?? Date.now()
    // remainingSec = floor(59000/1000) = 59 < 60 → 만료 판정
    const expiresAt = fixedNow + 59_000
    await keytar.setPassword(KEYTAR_SERVICE, 'kis-accessToken-paper', 'edge-59s')
    await keytar.setPassword(KEYTAR_SERVICE, 'kis-tokenExpiresAt-paper', String(expiresAt))

    const ok = await KisService.loadSavedToken()

    expect(ok).toBe(false)
    expect(mainState.kisAccessToken).toBeNull()
  })
})

/**
 * loadTokenFromVaultForFallback (EGW00133 경로) 잔여시간 경계.
 * `if (remainingSec < 600) return false` — 정확히 600초는 통과(true).
 */
describe('KisService.issueToken — EGW00133 fallback 잔여시간 경계 (600초)', () => {
  it('잔여 정확히 600초 → fallback 성공 (>= MIN_REMAINING_SEC_FOR_RESTORE)', async () => {
    await seedApiKeys()
    vi.useFakeTimers() // 시간 고정으로 floor 결과 안정화
    const fixedNow = vi.getMockedSystemTime()?.valueOf() ?? Date.now()
    const expiresAt = fixedNow + 600_000
    await keytar.setPassword(KEYTAR_SERVICE, 'kis-accessToken-paper', 'edge-600s')
    await keytar.setPassword(KEYTAR_SERVICE, 'kis-tokenExpiresAt-paper', String(expiresAt))

    kisHttpMock.post.mockRejectedValueOnce(buildAxiosError(tokenIssueRateLimitErrorResponse))

    await expect(KisService.issueToken()).resolves.toBeUndefined()

    expect(mainState.kisAccessToken).toBe('edge-600s')
  })

  it('잔여 599초 → fallback 거부, 원본 에러 throw', async () => {
    await seedApiKeys()
    vi.useFakeTimers()
    const fixedNow = vi.getMockedSystemTime()?.valueOf() ?? Date.now()
    // remainingSec = floor(599000/1000) = 599 < 600
    const expiresAt = fixedNow + 599_000
    await keytar.setPassword(KEYTAR_SERVICE, 'kis-accessToken-paper', 'edge-599s')
    await keytar.setPassword(KEYTAR_SERVICE, 'kis-tokenExpiresAt-paper', String(expiresAt))

    kisHttpMock.post.mockRejectedValueOnce(buildAxiosError(tokenIssueRateLimitErrorResponse))

    await expect(KisService.issueToken()).rejects.toThrow()
    // fallback 거부됐으므로 mainState는 갱신되지 않음
    expect(mainState.kisAccessToken).toBeNull()
  })
})

/**
 * mainState.isKisTokenValid: `Date.now() < expiresAt - 60_000` (1분 여유).
 * setKisAccessToken('x', N)는 expiresAt = Date.now() + N*1000 이므로
 * N=60이면 expiresAt - 60_000 == 호출 시점의 Date.now() → 등호 성립으로 false.
 */
describe('mainState.isKisTokenValid — 1분 여유 경계', () => {
  // fake timer로 Date.now() 고정 — 60_000ms 이하 차이는 ms 단위 race로 흔들린다.
  it('만료까지 60초 정확히 남음 → false (< 가 아니라 == 이므로)', () => {
    vi.useFakeTimers()
    // setKisAccessToken('x', 60) → expiresAt = now + 60_000
    // isKisTokenValid: Date.now() < (now + 60_000) - 60_000 → now < now → false
    mainState.clear()
    mainState.setKisAccessToken('x', 60)
    expect(mainState.isKisTokenValid()).toBe(false)
  })

  it('만료까지 61초 남음 → true', () => {
    vi.useFakeTimers()
    mainState.clear()
    mainState.setKisAccessToken('x', 61)
    // Date.now() < (now + 61_000) - 60_000 → now < now + 1_000 → true
    expect(mainState.isKisTokenValid()).toBe(true)
  })
})

/**
 * Sanity check — axios mock이 모든 테스트 파일에 자동 적용되는지 확인.
 * 한 군데에서 실패하면 다른 파일들도 의심해야 함.
 */
describe('test infrastructure — axios network call 차단', () => {
  it('sanity: axios.create는 mock 인스턴스를 반환한다 (실제 네트워크 호출 차단 보장)', async () => {
    const axios = (await import('axios')).default
    // setup.ts에서 vi.mock('axios')로 등록한 mock이 보이는지 확인
    expect(vi.isMockFunction(axios.create)).toBe(true)
    // 호출 시 우리가 export한 kisHttpMock과 동일한 객체를 반환
    const instance = axios.create()
    expect(instance).toBe(kisHttpMock)
  })
})
