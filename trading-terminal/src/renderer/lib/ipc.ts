import { IPC_CHANNELS } from '../../lib/ipcChannels'

// 브라우저 개발 미리보기용 mock (Electron 컨텍스트 외부)
const api: typeof window.terminalApi | undefined =
  typeof window !== 'undefined' ? (window as any).terminalApi : undefined

const mockApi = {
  invoke: (_channel: string, _payload?: unknown) => Promise.resolve(null),
  on: (_channel: string, _listener: (payload: unknown) => void) => () => {},
}

/** window.terminalApi.invoke 타입 안전 래퍼 */
export const ipc = {
  invoke: <T = unknown>(channel: string, payload?: unknown): Promise<T> =>
    (api ?? mockApi).invoke(channel, payload) as Promise<T>,

  on: (channel: string, listener: (payload: unknown) => void): (() => void) =>
    (api ?? mockApi).on(channel, listener),
}

export { IPC_CHANNELS }
