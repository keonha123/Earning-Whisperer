import { contextBridge, ipcRenderer, type IpcRendererEvent } from 'electron'
import { deserializeIpcError } from '../lib/types/ipcError'

/**
 * contextBridge를 통해 Renderer에 최소한의 IPC API만 노출한다.
 * Node.js API는 일절 노출하지 않는다.
 *
 * invoke 결과의 reject 는 main 측 IpcError 가 인코딩된 것일 수 있다.
 * deserializeIpcError 로 추출 성공 시 IpcError instance 로 재 throw,
 * 실패 시 원본 에러 그대로 throw (renderer 가 generic Error 로 처리).
 */
contextBridge.exposeInMainWorld('terminalApi', {
  invoke: async (channel: string, payload?: unknown): Promise<unknown> => {
    try {
      return await ipcRenderer.invoke(channel, payload)
    } catch (e) {
      const ipcErr = deserializeIpcError(e)
      if (ipcErr !== null) throw ipcErr
      throw e
    }
  },

  /** Main → Renderer: 이벤트 구독. 반환값은 구독 해제 함수 */
  on: (channel: string, listener: (payload: unknown) => void): (() => void) => {
    const wrapped = (_event: IpcRendererEvent, payload: unknown) => listener(payload)
    ipcRenderer.on(channel, wrapped)
    return () => ipcRenderer.removeListener(channel, wrapped)
  },
})

declare global {
  interface Window {
    terminalApi: {
      invoke: (channel: string, payload?: unknown) => Promise<unknown>
      on: (channel: string, listener: (payload: unknown) => void) => () => void
    }
  }
}
