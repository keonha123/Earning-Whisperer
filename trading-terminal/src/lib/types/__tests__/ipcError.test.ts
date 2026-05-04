import { describe, it, expect } from 'vitest'
import {
  IpcError,
  axiosErrorToIpcError,
  deserializeIpcError,
  isIpcError,
  sanitizeAxiosErrorDetails,
  serializeIpcError,
} from '../ipcError'

describe('IpcError — 기본', () => {
  it('생성자 — code/message/details 보존 + Error 상속', () => {
    const err = new IpcError('VALIDATION', 'invalid ticker', { field: 'ticker' })

    expect(err).toBeInstanceOf(Error)
    expect(err.name).toBe('IpcError')
    expect(err.code).toBe('VALIDATION')
    expect(err.message).toBe('invalid ticker')
    expect(err.details).toEqual({ field: 'ticker' })
  })

  it('isIpcError — IpcError instance 만 true', () => {
    expect(isIpcError(new IpcError('UNKNOWN', 'x'))).toBe(true)
    expect(isIpcError(new Error('x'))).toBe(false)
    expect(isIpcError({ code: 'VALIDATION', message: 'x' })).toBe(false)
    expect(isIpcError(null)).toBe(false)
    expect(isIpcError('string')).toBe(false)
  })

  it('toPayload / fromPayload round-trip', () => {
    const err = new IpcError('BACKEND_5XX', 'server down', { status: 503 })
    const payload = err.toPayload()

    expect(payload.__ipcError).toBe(true)
    expect(payload.code).toBe('BACKEND_5XX')
    expect(payload.message).toBe('server down')
    expect(payload.details).toEqual({ status: 503 })

    const restored = IpcError.fromPayload(payload)
    expect(restored.code).toBe(err.code)
    expect(restored.message).toBe(err.message)
    expect(restored.details).toEqual(err.details)
  })

  it('details 가 undefined 면 payload 에 details key 자체가 없음', () => {
    const payload = new IpcError('VALIDATION', 'x').toPayload()
    expect('details' in payload).toBe(false)
  })
})

describe('serializeIpcError / deserializeIpcError', () => {
  it('round-trip — code/message/details 모두 보존', () => {
    const original = new IpcError('AUTH_EXPIRED', '인증 만료', { status: 401 })
    const serialized = serializeIpcError(original)
    const restored = deserializeIpcError(serialized)

    expect(restored).not.toBeNull()
    expect(restored!.code).toBe('AUTH_EXPIRED')
    expect(restored!.message).toBe('인증 만료')
    expect(restored!.details).toEqual({ status: 401 })
  })

  it('Electron prefix 가 message 앞에 붙어도 deserialize 성공', () => {
    const original = new IpcError('VALIDATION', 'invalid ticker')
    const serialized = serializeIpcError(original)
    // Electron 이 실제로 throw 시 message 를 wrap 하는 형식 시뮬레이션.
    const wrapped = new Error(
      `Error invoking remote method 'terminal:stock:get-detail': Error: ${serialized.message}`,
    )

    const restored = deserializeIpcError(wrapped)
    expect(restored).not.toBeNull()
    expect(restored!.code).toBe('VALIDATION')
    expect(restored!.message).toBe('invalid ticker')
  })

  it('인코딩 sentinel 없는 일반 Error → null', () => {
    expect(deserializeIpcError(new Error('plain error'))).toBeNull()
  })

  it('payload 가 sentinel 안에 있지만 JSON 깨진 경우 → null', () => {
    const broken = new Error('IPC_ERROR::not-a-json::IPC_ERROR_END')
    expect(deserializeIpcError(broken)).toBeNull()
  })

  it('payload 의 code 가 알 수 없는 값이면 null (validation)', () => {
    const fake = new Error('IPC_ERROR::{"__ipcError":true,"code":"BOGUS","message":"x"}::IPC_ERROR_END')
    expect(deserializeIpcError(fake)).toBeNull()
  })

  it('payload 의 __ipcError 마커 없으면 null', () => {
    const fake = new Error('IPC_ERROR::{"code":"VALIDATION","message":"x"}::IPC_ERROR_END')
    expect(deserializeIpcError(fake)).toBeNull()
  })

  it('null / undefined / 비 Error 입력 → null', () => {
    expect(deserializeIpcError(null)).toBeNull()
    expect(deserializeIpcError(undefined)).toBeNull()
    expect(deserializeIpcError(123)).toBeNull()
    expect(deserializeIpcError({})).toBeNull()
  })

  it('string 입력도 처리 — message 만 따로 들어오는 경우', () => {
    const original = new IpcError('NETWORK', 'connection refused')
    const restored = deserializeIpcError(serializeIpcError(original).message)
    expect(restored).not.toBeNull()
    expect(restored!.code).toBe('NETWORK')
  })
})

describe('axiosErrorToIpcError — status 별 분류', () => {
  function makeAxiosError(status: number, data?: unknown) {
    return {
      isAxiosError: true,
      response: { status, data },
      message: `Request failed with status code ${status}`,
    }
  }

  it('401 → AUTH_EXPIRED', () => {
    const err = axiosErrorToIpcError(makeAxiosError(401))
    expect(err.code).toBe('AUTH_EXPIRED')
    expect(err.message).toMatch(/인증/)
  })

  it('419 → AUTH_EXPIRED (세션 만료)', () => {
    const err = axiosErrorToIpcError(makeAxiosError(419))
    expect(err.code).toBe('AUTH_EXPIRED')
  })

  it('403 → AUTH_REQUIRED', () => {
    const err = axiosErrorToIpcError(makeAxiosError(403))
    expect(err.code).toBe('AUTH_REQUIRED')
  })

  it('404 → VALIDATION', () => {
    const err = axiosErrorToIpcError(makeAxiosError(404))
    expect(err.code).toBe('VALIDATION')
  })

  it('400 + 백엔드 message 본문 → VALIDATION + 본문 메시지 보존', () => {
    const err = axiosErrorToIpcError(
      makeAxiosError(400, { message: 'ticker must be uppercase' }),
    )
    expect(err.code).toBe('VALIDATION')
    expect(err.message).toBe('ticker must be uppercase')
  })

  it('500 → BACKEND_5XX', () => {
    const err = axiosErrorToIpcError(makeAxiosError(500))
    expect(err.code).toBe('BACKEND_5XX')
  })

  it('503 + 백엔드 error 본문 → BACKEND_5XX + 본문 메시지', () => {
    const err = axiosErrorToIpcError(makeAxiosError(503, { error: 'service unavailable' }))
    expect(err.code).toBe('BACKEND_5XX')
    expect(err.message).toBe('service unavailable')
  })

  it('response 없고 request 만 있음 → NETWORK', () => {
    const err = axiosErrorToIpcError({
      isAxiosError: true,
      request: {},
      code: 'ECONNREFUSED',
      message: 'connect ECONNREFUSED',
    })
    expect(err.code).toBe('NETWORK')
  })

  it('axios error 아닌 일반 Error → UNKNOWN', () => {
    const err = axiosErrorToIpcError(new Error('boom'))
    expect(err.code).toBe('UNKNOWN')
    expect(err.message).toBe('boom')
  })

  it('null/undefined → UNKNOWN', () => {
    expect(axiosErrorToIpcError(null).code).toBe('UNKNOWN')
    expect(axiosErrorToIpcError(undefined).code).toBe('UNKNOWN')
  })

  it('details 에 status 와 data 보존', () => {
    const err = axiosErrorToIpcError(
      makeAxiosError(500, { trace: 'NullPointerException at ...' }),
    )
    expect(err.details?.status).toBe(500)
    expect(err.details?.data).toEqual({ trace: 'NullPointerException at ...' })
  })

  it('보안: details 에 config.headers / request / stack 등 자격증명 source 가 포함되지 않음', () => {
    // 실제 AxiosError 가 보유하는 위험 필드 시뮬레이션 — Bearer/appkey/appsecret 등.
    const dangerous = {
      isAxiosError: true,
      response: { status: 500, data: { error: 'server' } },
      config: {
        headers: {
          authorization: 'Bearer eyJhbGc...',
          appkey: 'KIS-APPKEY-PLAINTEXT',
          appsecret: 'KIS-SECRET-PLAINTEXT',
        },
        baseURL: 'https://openapi.koreainvestment.com:9443',
      },
      request: { _header: 'GET ... authorization: Bearer ...' },
      stack: 'Error: ...',
      message: 'Request failed',
    }

    const err = axiosErrorToIpcError(dangerous)
    const serialized = JSON.stringify(err.details)

    expect(serialized).not.toContain('Bearer')
    expect(serialized).not.toContain('APPKEY')
    expect(serialized).not.toContain('SECRET')
    expect(serialized).not.toContain('koreainvestment')
    expect(err.details).toEqual({
      status: 500,
      data: { error: 'server' },
      code: undefined,
    })
  })
})

describe('sanitizeAxiosErrorDetails', () => {
  it('axios error 에서 status/data/code 만 추출, headers/config 제외', () => {
    const result = sanitizeAxiosErrorDetails({
      isAxiosError: true,
      response: { status: 401, data: { message: 'unauthorized' } },
      code: 'ERR_BAD_REQUEST',
      config: { headers: { authorization: 'Bearer secret' } },
    })

    expect(result).toEqual({
      status: 401,
      data: { message: 'unauthorized' },
      code: 'ERR_BAD_REQUEST',
    })
    expect(JSON.stringify(result)).not.toContain('Bearer')
  })

  it('axios error 가 아니면 undefined 반환 (raw error 누출 방지)', () => {
    expect(sanitizeAxiosErrorDetails(new Error('plain'))).toBeUndefined()
    expect(sanitizeAxiosErrorDetails({ random: 'object' })).toBeUndefined()
    expect(sanitizeAxiosErrorDetails(null)).toBeUndefined()
    expect(sanitizeAxiosErrorDetails('string')).toBeUndefined()
  })
})
