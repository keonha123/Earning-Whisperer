import { ipcMain, type IpcMainInvokeEvent } from 'electron'
import { IpcError, serializeIpcError } from '../../lib/types/ipcError'

/**
 * IPC handler 등록 wrapper.
 *
 * 모든 throw 를 catch 해 IpcError 로 정규화하고 serializeIpcError 를 통해
 * preload 가 추출 가능한 형식으로 인코딩한다.
 *
 * - IpcError 직접 throw: code/message/details 보존
 * - 그 외 (axios 가 BackendClient interceptor 거치지 않은 경우, 예상 못 한 throw):
 *   UNKNOWN code 로 wrap
 *
 * Electron `ipcMain.handle` 의 throw → renderer reject 시 사용자 정의 enumerable
 * property 가 손실되는 제약을 회피하기 위함. 자세한 인코딩 형식은
 * `src/lib/types/ipcError.ts` 참고.
 */
export function registerHandler<TPayload = unknown, TResult = unknown>(
  channel: string,
  fn: (event: IpcMainInvokeEvent, payload: TPayload) => Promise<TResult> | TResult,
): void {
  ipcMain.handle(channel, async (event, payload) => {
    try {
      return await fn(event, payload as TPayload)
    } catch (err) {
      if (err instanceof IpcError) throw serializeIpcError(err)
      const wrapped = new IpcError(
        'UNKNOWN',
        err instanceof Error ? err.message : 'unknown error',
      )
      throw serializeIpcError(wrapped)
    }
  })
}
