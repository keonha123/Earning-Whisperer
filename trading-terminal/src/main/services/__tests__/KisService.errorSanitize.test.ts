import { describe, it, expect, beforeAll } from 'vitest'

// 공유 axios mock — setup.ts에서 vi.mock('axios')로 등록되어 있다.
import { kisHttpMock } from '../../../test/setup'

/**
 * kisHttp 에 등록된 response interceptor 의 reject 핸들러를 캡처한다.
 *
 * setup.ts 의 `interceptors.response.use` 는 no-op vi.fn() 이고, vitest 설정의
 * `clearMocks: true` 가 매 테스트 전에 mock.calls 를 비우기 때문에 모듈 import 시점의
 * 등록 인자는 mock.calls 로 읽을 수 없다. 그래서 KisService 를 동적 import 하기 직전에
 * use 구현을 갈아끼워 등록 인자를 로컬 배열에 보관한다 (setup.ts 는 손대지 않는다).
 */
const registeredResponseInterceptors: unknown[][] = []

beforeAll(async () => {
  kisHttpMock.interceptors.response.use.mockImplementation((...args: unknown[]) => {
    registeredResponseInterceptors.push(args)
    return 0
  })
  // import 시점에 kisHttp 생성 + response interceptor 등록이 일어난다
  await import('../KisService')
})

function getResponseRejectHandler(): (err: unknown) => unknown {
  expect(registeredResponseInterceptors.length).toBeGreaterThan(0)
  const handler = registeredResponseInterceptors[0][1]
  expect(typeof handler).toBe('function')
  return handler as (err: unknown) => unknown
}

describe('kisHttp response interceptor — 자격증명 로그 유출 차단', () => {
  it('reject 되는 AxiosError 에서 config(헤더 포함) 를 제거한다', async () => {
    const reject = getResponseRejectHandler()

    const axiosError = new Error('Request failed with status code 403') as Error & {
      config?: unknown
      response?: unknown
    }
    axiosError.config = {
      url: '/uapi/overseas-stock/v1/trading/order',
      headers: {
        appkey: 'PSxxxxxxxxxxxxxxxxxx',
        appsecret: 'SECRETxxxxxxxxxxxxxx',
        authorization: 'Bearer token.value',
      },
    }
    axiosError.response = { status: 403, data: { msg1: '거부' } }

    const returned = (await Promise.resolve(reject(axiosError)).catch((e) => e)) as typeof axiosError

    expect(returned.config).toBeUndefined()
    // 직렬화해도 자격증명이 남지 않아야 한다
    const serialized = JSON.stringify(returned, Object.getOwnPropertyNames(returned))
    expect(serialized).not.toContain('PSxxxxxxxxxxxxxxxxxx')
    expect(serialized).not.toContain('SECRETxxxxxxxxxxxxxx')
    expect(serialized).not.toContain('Bearer token.value')
    // response.data 는 진단에 필요하므로 보존
    expect(returned.response).toEqual({ status: 403, data: { msg1: '거부' } })
  })

  it('config 가 없는 에러도 그대로 reject 한다', async () => {
    const reject = getResponseRejectHandler()
    const plain = new Error('네트워크 오류')
    const returned = await Promise.resolve(reject(plain)).catch((e) => e)
    expect(returned).toBe(plain)
  })
})
