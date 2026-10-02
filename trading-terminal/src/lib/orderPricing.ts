/**
 * 즉시 체결용 지정가 산출 — main / renderer 공용.
 *
 * KIS 해외주식 주문에는 매수 시장가 코드가 없다. `ORD_DVSN` 매수 코드는
 * 지정가(00) / LOO(32) / LOC(34) 뿐이고, 모의투자(VTTT1002U) 는 00 만 허용한다.
 * 따라서 "시장가" 의도를 그대로 보내면 `OVRS_ORD_UNPR='0'` 인 0달러 지정가가 나가
 * 영원히 체결되지 않는다.
 *
 * 대신 현재가에 버퍼를 얹은(매도는 내린) 지정가를 보내 실질적으로 즉시 체결시키고,
 * 동시에 슬리피지 상한을 둔다.
 */

/** 현재가 대비 가감 폭. 1% — 미국 대형주 호가 스프레드를 넉넉히 덮으면서 슬리피지 상한 역할. */
export const IMMEDIATE_FILL_BUFFER = 0.01

/**
 * 즉시 체결을 노리는 지정가를 계산한다. 현재가가 없거나 비정상이면 null.
 *
 * 미국 주식 호가 단위는 $0.01 이므로 2자리로 맞추되, 체결 방향으로 보정한다
 * (매수는 올림, 매도는 내림).
 */
export function immediateFillPrice(side: 'BUY' | 'SELL', currentPrice: number): number | null {
  if (!Number.isFinite(currentPrice) || currentPrice <= 0) return null
  const raw =
    side === 'BUY'
      ? currentPrice * (1 + IMMEDIATE_FILL_BUFFER)
      : currentPrice * (1 - IMMEDIATE_FILL_BUFFER)
  const rounded = side === 'BUY' ? Math.ceil(raw * 100) / 100 : Math.floor(raw * 100) / 100
  return rounded > 0 ? rounded : null
}
