import { expect } from 'vitest'
import { deserializeIpcError, type IpcErrorCode } from '../lib/types/ipcError'

/**
 * IPC handler 의 reject 결과가 인코딩된 IpcError 인지 검증.
 *
 * registerHandler 가 throw 한 IpcError 는 message 안에 JSON 으로 인코딩되어 있으므로,
 * 단순히 message 문자열을 비교하기보다 deserialize 후 code 를 검증하는 것이 정확하다.
 *
 * 사용 예:
 *   await expectIpcError(handler({} as never, undefined), 'VALIDATION', /invalid ticker/)
 */
export async function expectIpcError(
  promise: Promise<unknown>,
  code: IpcErrorCode,
  messagePattern?: RegExp | string,
): Promise<void> {
  let caught: unknown
  try {
    await promise
  } catch (e) {
    caught = e
  }

  expect(caught, 'expected promise to reject').toBeDefined()
  const ipcErr = deserializeIpcError(caught)
  expect(
    ipcErr,
    `expected IpcError(${code}), got: ${caught instanceof Error ? caught.message : String(caught)}`,
  ).not.toBeNull()
  expect(ipcErr!.code).toBe(code)
  if (messagePattern instanceof RegExp) {
    expect(ipcErr!.message).toMatch(messagePattern)
  } else if (typeof messagePattern === 'string') {
    expect(ipcErr!.message).toContain(messagePattern)
  }
}
