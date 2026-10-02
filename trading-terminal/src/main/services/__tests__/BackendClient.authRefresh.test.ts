import { describe, it, expect, beforeEach, vi } from 'vitest'

import { kisHttpMock } from '../../../test/setup'
// import 자체가 모듈을 로드해 인터셉터를 등록시킨다.
import { setRefreshFailedHandler } from '../BackendClient'
import { mainState } from '../../store/mainState'

/**
 * 액세스 토큰 만료 자동 갱신.
 *
 * 백엔드는 AT 15분 + RT 7일 이원화이고 refresh_token 은 HttpOnly 쿠키로만
 * 주고받는다. Node 의 axios 에는 쿠키 저장소가 없어서 이 쿠키를 버리고 있었고,
 * 그래서 15분마다 로그인 화면으로 튕겼다. 인터셉터가 쿠키를 보관했다가 401 에서
 * 갱신하고 원 요청을 재시도한다.
 *
 * setup.ts 의 axios mock 은 interceptors.use 를 stub 으로 둔다. 등록된 핸들러를
 * 꺼내 직접 호출하는 방식으로 검증한다.
 */

// BackendClient 모듈 로드 시 등록된 인터셉터 핸들러.
const requestHandler = kisHttpMock.interceptors.request.use.mock.calls[0][0] as (
  config: Record<string, unknown>,
) => Record<string, unknown>
const [responseFulfilled, responseRejected] = kisHttpMock.interceptors.response.use.mock
  .calls[0] as [
  (r: unknown) => unknown,
  (e: unknown) => Promise<unknown>,
]

function unauthorized(url: string, extra: Record<string, unknown> = {}) {
  return { response: { status: 401 }, config: { url, headers: {}, ...extra } }
}

beforeEach(() => {
  kisHttpMock.post.mockReset()
  kisHttpMock.request.mockReset()
  mainState.setBackendToken('old-access')
  mainState.setBackendRefreshToken(null)
  setRefreshFailedHandler(null)
})

describe('refresh_token 쿠키 보관', () => {
  it('로그인 응답의 Set-Cookie 에서 refresh_token 을 꺼내 둔다', () => {
    responseFulfilled({
      headers: {
        'set-cookie': [
          'refresh_token=rt-abc; Path=/api/v1/auth; HttpOnly; SameSite=Strict; Max-Age=604800',
        ],
      },
    })

    expect(mainState.backendRefreshToken).toBe('rt-abc')
  })

  it('로그아웃 응답의 빈 값 쿠키는 보관분을 지운다', () => {
    mainState.setBackendRefreshToken('rt-abc')

    responseFulfilled({
      headers: { 'set-cookie': ['refresh_token=; Path=/api/v1/auth; Max-Age=0'] },
    })

    expect(mainState.backendRefreshToken).toBeNull()
  })

  it('다른 쿠키만 오면 보관분을 건드리지 않는다', () => {
    mainState.setBackendRefreshToken('rt-abc')

    responseFulfilled({ headers: { 'set-cookie': ['other=1; Path=/'] } })

    expect(mainState.backendRefreshToken).toBe('rt-abc')
  })
})

describe('요청에 쿠키 첨부', () => {
  it('/api/v1/auth 경로에만 붙인다 — 백엔드가 잡아 둔 쿠키 path 와 같다', () => {
    mainState.setBackendRefreshToken('rt-abc')

    const auth = requestHandler({ url: '/api/v1/auth/refresh', headers: {} })
    const other = requestHandler({ url: '/api/v1/users/me', headers: {} })

    expect((auth.headers as Record<string, string>).Cookie).toBe('refresh_token=rt-abc')
    expect((other.headers as Record<string, string>).Cookie).toBeUndefined()
  })

  it('보관한 토큰이 없으면 붙이지 않는다', () => {
    const config = requestHandler({ url: '/api/v1/auth/refresh', headers: {} })

    expect((config.headers as Record<string, string>).Cookie).toBeUndefined()
  })
})

describe('401 자동 갱신', () => {
  it('갱신 후 원 요청을 재시도하고 새 액세스 토큰을 보관한다', async () => {
    mainState.setBackendRefreshToken('rt-abc')
    kisHttpMock.post.mockResolvedValueOnce({ data: { access_token: 'new-access' }, headers: {} })
    kisHttpMock.request.mockResolvedValueOnce({ data: 'ok' })

    const result = await responseRejected(unauthorized('/api/v1/users/me'))

    expect(mainState.backendToken).toBe('new-access')
    expect(kisHttpMock.post).toHaveBeenCalledWith('/api/v1/auth/refresh', null, expect.anything())
    expect(result).toEqual({ data: 'ok' })
  })

  it('동시에 터진 401 들이 갱신을 한 번만 호출한다', async () => {
    // 각자 갱신을 부르면 백엔드의 rotation 이 재사용으로 판단해 family 전체를
    // 차단한다 — 갱신하려다 오히려 강제 로그아웃된다.
    mainState.setBackendRefreshToken('rt-abc')
    let resolveRefresh: (v: unknown) => void = () => {}
    kisHttpMock.post.mockReturnValueOnce(
      new Promise((resolve) => {
        resolveRefresh = resolve
      }),
    )
    kisHttpMock.request.mockResolvedValue({ data: 'ok' })

    const pending = [
      responseRejected(unauthorized('/api/v1/watchlist')),
      responseRejected(unauthorized('/api/v1/earnings/timeline')),
      responseRejected(unauthorized('/api/v1/users/me')),
    ]
    resolveRefresh({ data: { access_token: 'new-access' }, headers: {} })
    await Promise.all(pending)

    expect(kisHttpMock.post).toHaveBeenCalledTimes(1)
    expect(kisHttpMock.request).toHaveBeenCalledTimes(3)
  })

  it('갱신 요청 자체의 401 은 다시 갱신하지 않는다 — 무한 재귀 방지', async () => {
    mainState.setBackendRefreshToken('rt-abc')

    await expect(
      responseRejected(unauthorized('/api/v1/auth/refresh', { __isRefresh: true })),
    ).rejects.toBeDefined()

    expect(kisHttpMock.post).not.toHaveBeenCalled()
  })

  it('재시도한 요청이 또 401 이면 다시 갱신하지 않는다', async () => {
    mainState.setBackendRefreshToken('rt-abc')

    await expect(
      responseRejected(unauthorized('/api/v1/users/me', { __retried: true })),
    ).rejects.toBeDefined()

    expect(kisHttpMock.post).not.toHaveBeenCalled()
  })

  it('보관한 refresh token 이 없으면 갱신을 시도하지 않는다', async () => {
    await expect(responseRejected(unauthorized('/api/v1/users/me'))).rejects.toBeDefined()

    expect(kisHttpMock.post).not.toHaveBeenCalled()
  })

  it('네트워크 오류로 갱신이 실패하면 세션을 유지한다 — 다음 요청에서 다시 시도한다', async () => {
    // 여기서 세션을 정리해 버리면 잠깐 연결이 끊긴 것만으로 강제 로그아웃된다.
    // 세션을 끝내는 것은 RT 가 무효라는 확실한 신호(401)뿐이다.
    mainState.setBackendRefreshToken('rt-abc')
    kisHttpMock.post.mockRejectedValueOnce(new Error('ECONNRESET'))
    const onFailed = vi.fn()
    setRefreshFailedHandler(onFailed)

    await expect(responseRejected(unauthorized('/api/v1/users/me'))).rejects.toBeDefined()

    expect(onFailed).not.toHaveBeenCalled()
    expect(mainState.backendRefreshToken).toBe('rt-abc')
  })
})

describe('실패 구분 — 리뷰 지적 반영', () => {
  it('갱신은 성공했는데 재시도가 실패하면 세션을 정리하지 않는다', async () => {
    // 백엔드 순간 장애나 터널 재연결이 곧바로 강제 로그아웃이 되어서는 안 된다.
    mainState.setBackendRefreshToken('rt-abc')
    kisHttpMock.post.mockImplementationOnce(async () => {
      mainState.setBackendRefreshToken('rt-rotated')
      return { data: { access_token: 'new-access' }, headers: {} }
    })
    kisHttpMock.request.mockRejectedValueOnce({ response: { status: 500 } })
    const onFailed = vi.fn()
    setRefreshFailedHandler(onFailed)

    await expect(responseRejected(unauthorized('/api/v1/users/me'))).rejects.toBeDefined()

    expect(onFailed).not.toHaveBeenCalled()
    expect(mainState.backendRefreshToken).toBe('rt-rotated')
    expect(mainState.backendToken).toBe('new-access')
  })

  it('429(동시 갱신 경합)는 일시적 실패로 보고 세션을 유지한다', async () => {
    mainState.setBackendRefreshToken('rt-abc')
    kisHttpMock.post.mockRejectedValueOnce({ response: { status: 429 } })
    const onFailed = vi.fn()
    setRefreshFailedHandler(onFailed)

    await expect(responseRejected(unauthorized('/api/v1/users/me'))).rejects.toBeDefined()

    expect(onFailed).not.toHaveBeenCalled()
    expect(mainState.backendRefreshToken).toBe('rt-abc')
  })

  it('401 은 최종 실패로 보고 세션을 정리한다', async () => {
    mainState.setBackendRefreshToken('rt-abc')
    kisHttpMock.post.mockRejectedValueOnce({ response: { status: 401 } })
    const onFailed = vi.fn()
    setRefreshFailedHandler(onFailed)

    await expect(responseRejected(unauthorized('/api/v1/users/me'))).rejects.toBeDefined()

    expect(onFailed).toHaveBeenCalledTimes(1)
    expect(mainState.backendRefreshToken).toBeNull()
  })

  it('갱신 응답에 새 쿠키가 없으면 세션을 끝낸다 — 사용된 토큰 재전송 방지', async () => {
    // 회전된 쿠키를 못 받았다면 보관 중인 값은 이미 사용된 토큰이다. 그대로 두면
    // 다음 갱신에서 재사용으로 판정되어 family 전체가 차단된다.
    mainState.setBackendRefreshToken('rt-abc')
    kisHttpMock.post.mockResolvedValueOnce({ data: { access_token: 'new-access' }, headers: {} })
    const onFailed = vi.fn()
    setRefreshFailedHandler(onFailed)

    // 서버가 Set-Cookie 를 안 보낸 상황을 모사 — 보관분을 미리 비운다.
    mainState.setBackendRefreshToken(null)
    await expect(responseRejected(unauthorized('/api/v1/users/me'))).rejects.toBeDefined()

    expect(kisHttpMock.post).not.toHaveBeenCalled()
  })

  it('동시에 갱신이 실패해도 세션 정리는 한 번만 돈다', async () => {
    mainState.setBackendRefreshToken('rt-abc')
    kisHttpMock.post.mockRejectedValue({ response: { status: 401 } })
    const onFailed = vi.fn()
    setRefreshFailedHandler(onFailed)

    await Promise.all([
      responseRejected(unauthorized('/api/v1/watchlist')).catch(() => {}),
      responseRejected(unauthorized('/api/v1/earnings/timeline')).catch(() => {}),
      responseRejected(unauthorized('/api/v1/users/me')).catch(() => {}),
    ])

    expect(onFailed).toHaveBeenCalledTimes(1)
  })
})

describe('쿠키 취급', () => {
  it('Max-Age=0 으로 지우는 형식도 삭제로 본다', () => {
    mainState.setBackendRefreshToken('rt-abc')

    responseFulfilled({
      headers: { 'set-cookie': ['refresh_token=deleted; Path=/api/v1/auth; Max-Age=0'] },
    })

    expect(mainState.backendRefreshToken).toBeNull()
  })

  it('/api/v1/authorize 같은 유사 경로에는 쿠키를 붙이지 않는다', () => {
    mainState.setBackendRefreshToken('rt-abc')

    const similar = requestHandler({ url: '/api/v1/authorize', headers: {} })

    expect((similar.headers as Record<string, string>).Cookie).toBeUndefined()
  })

  it('경로를 벗어나면 이전에 박힌 Cookie 헤더를 지운다', () => {
    // 재시도되는 config 는 같은 객체다. 남겨 두면 폐기된 토큰이 다시 전송된다.
    mainState.setBackendRefreshToken(null)

    const reused = requestHandler({
      url: '/api/v1/users/me',
      headers: { Cookie: 'refresh_token=stale' },
    })

    expect((reused.headers as Record<string, string>).Cookie).toBeUndefined()
  })
})
