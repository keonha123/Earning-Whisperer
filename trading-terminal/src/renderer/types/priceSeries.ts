/**
 * 가격 차트 시계열 한 점.
 *
 * 실데이터는 `STOCK_GET_DETAIL` 의 `chart30d`(30일 일봉 종가)에서 온다.
 */
export interface PricePoint {
  /** X축 라벨. 일봉은 "MM-DD". */
  time: string
  /** 종가. */
  price: number
}
