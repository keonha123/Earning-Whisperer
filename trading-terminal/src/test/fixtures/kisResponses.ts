/**
 * KIS Open API 응답 fixture.
 * 실제 KIS 모의투자 응답 스펙을 단위 테스트에서 재현하기 위한 최소 페이로드.
 */

// ── 토큰 발급 ────────────────────────────────────────────────────
export const tokenIssueSuccessResponse = {
  access_token: 'mocked.access.token',
  token_type: 'Bearer',
  expires_in: 86400,
}

export const tokenIssueRateLimitErrorResponse = {
  error_description: '접근토큰 발급 잠시 후 다시 시도하세요(1분당 1회)',
  error_code: 'EGW00133',
}

export function buildAxiosError(
  data: Record<string, unknown>,
  status = 403,
): Error & { response: { data: Record<string, unknown>; status: number } } {
  const err = new Error('AxiosError') as Error & {
    response: { data: Record<string, unknown>; status: number }
  }
  err.response = { data, status }
  return err
}

// ── 잔고 조회 (VTTS3012R) ─────────────────────────────────────────
export const balanceWithHoldings = {
  rt_cd: '0',
  output1: [
    {
      ovrs_pdno: 'TSLA',
      ovrs_cblc_qty: '10',
      pchs_avg_pric: '230.55',
      now_pric2: '245.10',
    },
    {
      ovrs_pdno: 'AAPL',
      ovrs_cblc_qty: '5',
      pchs_avg_pric: '185.00',
      now_pric2: '190.20',
    },
  ],
  output2: {},
}

export const balanceEmpty = {
  rt_cd: '0',
  output1: [],
  output2: {},
}

// ── 주문가능외화 (VTTS3007R) ──────────────────────────────────────
export const psAmountSuccess = {
  rt_cd: '0',
  output: {
    ord_psbl_frcr_amt: '12345.67',
  },
}

// ── 현재가 (HHDFS00000300) ────────────────────────────────────────
export function currentPriceResponse(last: number | string) {
  return {
    rt_cd: '0',
    output: {
      last: String(last),
    },
  }
}

export const currentPriceUndefinedResponse = {
  rt_cd: '0',
  output: {},
}

// ── 주문 응답 (VTTT1002U/VTTT1006U) ───────────────────────────────
export function orderSuccessResponse(odno: string) {
  return {
    rt_cd: '0',
    msg1: '정상처리되었습니다.',
    output: {
      ODNO: odno,
      KRX_FWDG_ORD_ORGNO: '00000',
      ORD_TMD: '093015',
    },
  }
}

// ── KIS rt_cd 비즈니스 실패 응답 (HTTP 200이지만 rt_cd='1') ──────────
/**
 * KIS Open API는 HTTP 200으로 응답하면서 rt_cd 필드로 비즈니스 성공/실패를 구분.
 * 실패 시: rt_cd='1', msg_cd/msg1에 사유 (예: APBK0918 = 주문가능금액 부족).
 */
export function kisOrderRejectResponse(msgCd: string, msg1: string) {
  return {
    rt_cd: '1',
    msg_cd: msgCd,
    msg1,
    output: {},
  }
}

export function kisBalanceRejectResponse(msgCd: string, msg1: string) {
  return {
    rt_cd: '1',
    msg_cd: msgCd,
    msg1,
    output1: [],
    output2: {},
  }
}

export function kisPsamountRejectResponse(msgCd: string, msg1: string) {
  return {
    rt_cd: '1',
    msg_cd: msgCd,
    msg1,
    output: {},
  }
}

export function kisCurrentPriceRejectResponse(msgCd: string, msg1: string) {
  return {
    rt_cd: '1',
    msg_cd: msgCd,
    msg1,
    output: {},
  }
}
