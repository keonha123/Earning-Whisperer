import { describe, it, expect } from 'vitest'
import { resolveExchange, describeSystemReject } from '../KisWebSocketService'

describe('resolveExchange', () => {
  it('WMT 는 나스닥 이전 후라 NAS 로 조회한다', () => {
    expect(resolveExchange('WMT')).toBe('NAS')
  })

  it('목록의 NYSE 종목은 NYS, 목록 밖은 NAS', () => {
    expect(resolveExchange('JPM')).toBe('NYS')
    expect(resolveExchange('AAPL')).toBe('NAS')
  })
})

describe('describeSystemReject', () => {
  it('rt_cd 가 0 이 아니면 거부 내용을 돌려준다', () => {
    const msg = { header: {}, body: { rt_cd: '9', msg1: 'ALREADY IN USE appkey ' } }
    expect(describeSystemReject(msg)).toBe('tr_id=- rt_cd=9 msg_cd=- msg1=ALREADY IN USE appkey')
  })

  it('정상 응답이나 rt_cd 가 없는 메시지는 null', () => {
    expect(describeSystemReject({ header: { tr_id: 'H0GSCNI9' }, body: { rt_cd: '0', msg1: 'SUBSCRIBE SUCCESS' } })).toBeNull()
    expect(describeSystemReject({ header: { tr_id: 'PINGPONG' } })).toBeNull()
  })
})
