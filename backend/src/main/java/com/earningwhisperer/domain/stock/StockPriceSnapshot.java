package com.earningwhisperer.domain.stock;

public record StockPriceSnapshot(
        String ticker,
        double currentPrice,
        double previousClose,
        double changePercent,
        long updatedAt
) {
    /**
     * 전일종가만 갈아 끼우고 현재가는 유지한다.
     *
     * <p>일봉이 새로 적재되면 전일종가가 바뀐다. 그때 현재가까지 덮어쓰면 실시간 시세가
     * 사라지므로 변동률만 다시 계산한다.
     */
    public StockPriceSnapshot withPreviousClose(double newPreviousClose, long now) {
        double change = newPreviousClose > 0
                ? (currentPrice - newPreviousClose) / newPreviousClose * 100.0
                : 0.0;
        return new StockPriceSnapshot(ticker, currentPrice, newPreviousClose, change, now);
    }

    public StockPriceSnapshot withPrice(double newPrice, long now) {
        double change = previousClose > 0
                ? (newPrice - previousClose) / previousClose * 100.0
                : 0.0;
        return new StockPriceSnapshot(ticker, newPrice, previousClose, change, now);
    }
}
