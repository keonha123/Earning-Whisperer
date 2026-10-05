package com.earningwhisperer.domain.stock;

/**
 * ticker → 가장 최근 close 매핑 projection.
 *
 * <p>{@link DailyBarRepository#findLatestClosesByTickers} 의 JPQL constructor projection 결과 타입.
 * StockPriceCache 의 종가 batch fetch 결과로 사용된다.
 *
 * <p>close 는 daily_bar.close_price (BigDecimal) 의 doubleValue 변환값. null 이거나 0 이하일 수
 * 있으므로 호출 측이 걸러낸다.
 */
public record TickerLatestClose(String ticker, Double close) {}
