package com.earningwhisperer.domain.stock;

public record StockPriceSnapshot(
        String ticker,
        double currentPrice,
        double previousClose,
        double changePercent,
        long updatedAt
) {
    public StockPriceSnapshot withPrice(double newPrice, long now) {
        double change = previousClose > 0
                ? (newPrice - previousClose) / previousClose * 100.0
                : 0.0;
        return new StockPriceSnapshot(ticker, newPrice, previousClose, change, now);
    }
}
