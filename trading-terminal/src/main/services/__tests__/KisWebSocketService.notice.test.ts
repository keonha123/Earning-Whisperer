import { describe, it, expect } from 'vitest'
import { parseFillNotice } from '../KisWebSocketService'

/**
 * 해외주식 실시간 체결통보(H0GSCNI0/9) 필드 순서 — 공식 샘플
 * examples_llm/overseas_stock/ccnl_notice 의 columns 정의 기준.
 *
 * CUST_ID^ACNT_NO^ODER_NO^OODER_NO^SELN_BYOV_CLS^RCTF_CLS^ODER_KIND2^
 * STCK_SHRN_ISCD^CNTG_QTY^CNTG_UNPR^STCK_CNTG_HOUR^RFUS_YN^CNTG_YN^...
 */
function notice(over: Partial<Record<string, string>> = {}): string {
  const f = [
    over.CUST_ID ?? 'user01',
    over.ACNT_NO ?? '5012345601',
    over.ODER_NO ?? '0000044600',
    over.OODER_NO ?? '0000000000',
    over.SELN_BYOV_CLS ?? '02',
    over.RCTF_CLS ?? '0',
    over.ODER_KIND2 ?? '00',
    over.STCK_SHRN_ISCD ?? 'WMT',
    over.CNTG_QTY ?? '1',
    over.CNTG_UNPR ?? '107.47',
    over.STCK_CNTG_HOUR ?? '133000',
    over.RFUS_YN ?? 'N',
    over.CNTG_YN ?? '2',
    over.ACPT_YN ?? '2',
    'BRNC', '1', 'acct', 'Walmart', '', '', '', '', '', '', '107.470000',
  ]
  return f.join('^')
}

describe('parseFillNotice', () => {
  it('체결 통보(CNTG_YN=2)에서 ODNO/종목/수량/단가를 읽는다', () => {
    expect(parseFillNotice(notice())).toEqual({
      orderId: '0000044600',
      ticker: 'WMT',
      executedQty: 1,
      executedPrice: 107.47,
    })
  })

  it('주문 접수 통보(CNTG_YN=1)는 체결이 아니므로 null', () => {
    // 같은 채널로 주문·정정·취소·거부 접수 통보가 함께 오는데, 이걸 체결로 처리하면
    // 아직 체결되지 않은 주문을 EXECUTED 로 확정해버린다.
    expect(parseFillNotice(notice({ CNTG_YN: '1' }))).toBeNull()
  })

  it('체결수량이 0 이거나 숫자가 아니면 null', () => {
    expect(parseFillNotice(notice({ CNTG_QTY: '0' }))).toBeNull()
    expect(parseFillNotice(notice({ CNTG_QTY: '' }))).toBeNull()
    expect(parseFillNotice(notice({ CNTG_QTY: 'abc' }))).toBeNull()
  })

  it('주문번호가 비면 null — 조회 키가 없으면 쓸 수 없다', () => {
    expect(parseFillNotice(notice({ ODER_NO: '' }))).toBeNull()
    expect(parseFillNotice(notice({ ODER_NO: '   ' }))).toBeNull()
  })

  it('단가가 0/비정상이면 수량만 살리고 단가는 null', () => {
    const parsed = parseFillNotice(notice({ CNTG_UNPR: '0' }))
    expect(parsed).not.toBeNull()
    expect(parsed?.executedQty).toBe(1)
    expect(parsed?.executedPrice).toBeNull()
  })

  it('필드 수가 부족한 프레임은 null (깨진 입력에 인덱스 접근하지 않는다)', () => {
    expect(parseFillNotice('')).toBeNull()
    expect(parseFillNotice('a^b^c')).toBeNull()
  })

  it('종목코드/주문번호의 공백은 제거한다', () => {
    const parsed = parseFillNotice(notice({ ODER_NO: ' 0000044600 ', STCK_SHRN_ISCD: ' WMT ' }))
    expect(parsed?.orderId).toBe('0000044600')
    expect(parsed?.ticker).toBe('WMT')
  })
})
