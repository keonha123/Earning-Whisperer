import { vi, beforeEach } from 'vitest'

/**
 * 공유 axios mock 인스턴스.
 * 모든 KisService/BackendClient 테스트에서 axios.create()의 반환값으로 사용되어
 * 실제 KIS/백엔드 서버에 네트워크 호출이 가는 것을 차단한다.
 *
 * interceptors는 BackendClient의 request interceptor 등록을 통과시키기 위한 stub.
 *
 * 사용 예:
 *   import { kisHttpMock } from '../../../test/setup'
 *   kisHttpMock.post.mockResolvedValueOnce({ data: ... })
 */
export const kisHttpMock = {
  get: vi.fn(),
  post: vi.fn(),
  put: vi.fn(),
  delete: vi.fn(),
  request: vi.fn(),
  interceptors: {
    request: { use: vi.fn(), eject: vi.fn() },
    response: { use: vi.fn(), eject: vi.fn() },
  },
}

/**
 * axios mock — axios.create()는 항상 공유 kisHttpMock 인스턴스를 반환한다.
 * 어떤 테스트 파일이라도 axios를 import하면 자동으로 mock이 적용된다 (네트워크 차단 보장).
 */
vi.mock('axios', () => {
  return {
    default: {
      create: vi.fn(() => kisHttpMock),
    },
    create: vi.fn(() => kisHttpMock),
  }
})

/**
 * 마이크로태스크 큐를 강제로 비우기 위한 헬퍼.
 * fake timer 환경에서 setTimeout 콜백 안의 await가 마이크로태스크로 등록될 때,
 * 다음 setTimeout 등록까지 진행시키려면 마이크로태스크를 여러 번 흘려보내야 한다.
 */
export const flushMicrotasks = async (): Promise<void> => {
  for (let i = 0; i < 5; i++) await Promise.resolve()
}

/**
 * Electron 모듈 mock — main 프로세스 코드가 BrowserWindow.getAllWindows() 등을 호출해도
 * 단위 테스트 환경에서 안전하게 빈 배열/no-op로 동작하도록 한다.
 */
vi.mock('electron', () => {
  return {
    BrowserWindow: {
      getAllWindows: vi.fn(() => []),
    },
    Notification: class FakeNotification {
      static isSupported(): boolean {
        return false
      }
      show(): void {
        /* no-op */
      }
    },
    app: {
      getPath: vi.fn(() => '/tmp'),
      on: vi.fn(),
      quit: vi.fn(),
    },
    ipcMain: {
      handle: vi.fn(),
      on: vi.fn(),
    },
  }
})

/**
 * keytar mock — 메모리 기반 fake.
 * 각 테스트에서 keytar를 import해 직접 setPassword로 시드를 넣을 수 있도록
 * 실제 keytar 모듈 모양과 동일한 함수를 제공한다.
 */
type KeytarKey = `${string}::${string}`
const keytarStore = new Map<KeytarKey, string>()

export function _resetKeytarStore(): void {
  keytarStore.clear()
}

vi.mock('keytar', () => {
  const buildKey = (service: string, account: string): KeytarKey =>
    `${service}::${account}` as KeytarKey

  return {
    default: {
      getPassword: vi.fn(async (service: string, account: string) => {
        return keytarStore.get(buildKey(service, account)) ?? null
      }),
      setPassword: vi.fn(async (service: string, account: string, password: string) => {
        keytarStore.set(buildKey(service, account), password)
      }),
      deletePassword: vi.fn(async (service: string, account: string) => {
        return keytarStore.delete(buildKey(service, account))
      }),
      findPassword: vi.fn(async () => null),
      findCredentials: vi.fn(async () => []),
    },
    getPassword: vi.fn(async (service: string, account: string) => {
      return keytarStore.get(buildKey(service, account)) ?? null
    }),
    setPassword: vi.fn(async (service: string, account: string, password: string) => {
      keytarStore.set(buildKey(service, account), password)
    }),
    deletePassword: vi.fn(async (service: string, account: string) => {
      return keytarStore.delete(buildKey(service, account))
    }),
    findPassword: vi.fn(async () => null),
    findCredentials: vi.fn(async () => []),
  }
})

beforeEach(() => {
  // 각 테스트마다 keytar 메모리 초기화 — 이전 테스트의 자격증명이 새지 않도록.
  keytarStore.clear()
  // 공유 axios mock도 매 테스트마다 reset (다른 테스트의 응답 누수 방지)
  kisHttpMock.get.mockReset()
  kisHttpMock.post.mockReset()
})
