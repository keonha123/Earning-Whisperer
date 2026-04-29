/**
 * 시세 폴링 도메인 공유 타입.
 *
 * main(PricePoller) 와 renderer(usePricesStore/usePrices) 가 동일한 형태로
 * 다뤄야 하는 페이로드를 단일 정의로 박제해 silent drift 를 방지한다.
 *
 * - PriceEntry: ticker 별 캐시 단건. Renderer store 의 값 자료형.
 * - PriceUpdate: PRICES_UPDATE broadcast 의 batch 항목. PriceEntry + ticker.
 *   (PRICES_GET 응답은 Record<ticker, PriceEntry> 형태로 전달.)
 */

export interface PriceEntry {
  currentPrice: number
  lastUpdated: number
}

export interface PriceUpdate extends PriceEntry {
  ticker: string
}
