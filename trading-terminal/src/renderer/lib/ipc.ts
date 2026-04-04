import { IPC_CHANNELS } from '../../lib/ipcChannels'

/** window.terminalApi.invoke 타입 안전 래퍼 */
export const ipc = {
  invoke: <T = unknown>(channel: string, payload?: unknown): Promise<T> =>
    window.terminalApi.invoke(channel, payload) as Promise<T>,

  on: (channel: string, listener: (payload: unknown) => void): (() => void) =>
    window.terminalApi.on(channel, listener),
}

export { IPC_CHANNELS }
