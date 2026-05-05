package com.earningwhisperer.domain.stock;

/**
 * ticker → 가장 최근 close 매핑 projection.
 *
 * <p>{@link DailyBarRepository#findLatestClosesByTickers} 의 JPQL constructor projection 결과 타입.
 * SignalService 의 시장 기준 비중 계산에서 N+1 회피용 batch fetch 결과로 사용된다.
 *
 * <p>close 는 daily_bar.close_price (BigDecimal) 의 doubleValue 변환값. 호출 측이 null 이거나
 * 0 이하인 close 를 fallback (avgPrice) 로 처리.
 */
public record TickerLatestClose(String ticker, Double close) {}
