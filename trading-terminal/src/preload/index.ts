import { contextBridge, ipcRenderer, type IpcRendererEvent } from 'electron'

/**
 * contextBridge를 통해 Renderer에 최소한의 IPC API만 노출한다.
 * Node.js API는 일절 노출하지 않는다.
 */
contextBridge.exposeInMainWorld('terminalApi', {
  /** Renderer → Main: Promise 기반 요청 */
  invoke: (channel: string, payload?: unknown): Promise<unknown> =>
    ipcRenderer.invoke(channel, payload),

  /** Main → Renderer: 이벤트 구독. 반환값은 구독 해제 함수 */
  on: (channel: string, listener: (payload: unknown) => void): (() => void) => {
    const wrapped = (_event: IpcRendererEvent, payload: unknown) => listener(payload)
    ipcRenderer.on(channel, wrapped)
    return () => ipcRenderer.removeListener(channel, wrapped)
  },
})

// TypeScript 타입 선언 (Renderer에서 window.terminalApi 사용 시)
declare global {
  interface Window {
    terminalApi: {
      invoke: (channel: string, payload?: unknown) => Promise<unknown>
      on: (channel: string, listener: (payload: unknown) => void) => () => void
    }
  }
}
