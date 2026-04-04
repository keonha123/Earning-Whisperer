package com.earningwhisperer.domain.earnings;

import com.earningwhisperer.domain.stock.Stock;
import com.earningwhisperer.domain.stock.StockRepository;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.time.Instant;
import java.time.temporal.ChronoUnit;
import java.util.List;

@Service
@RequiredArgsConstructor
public class EarningsCalendarService {

    private final EarningsCalendarRepository earningsCalendarRepository;
    private final StockRepository stockRepository;

    @Transactional(readOnly = true)
    public List<EarningsCalendar> getUpcomingByTickers(List<String> tickers) {
        if (tickers == null || tickers.isEmpty()) {
            return List.of();
        }
        return earningsCalendarRepository.findUpcomingByTickers(tickers, Instant.now());
    }

    @Transactional(readOnly = true)
    public List<EarningsCalendar> getCalendar(int daysAhead) {
        Instant from = Instant.now();
        Instant to = from.plus(daysAhead, ChronoUnit.DAYS);
        return earningsCalendarRepository.findByScheduledAtBetween(from, to);
    }

    /**
     * Finnhub 스케줄러에서 호출. 수신한 어닝콜 데이터를 upsert 처리.
     */
    @Transactional
    public void upsert(String ticker, Instant scheduledAt, boolean confirmed) {
        Stock stock = stockRepository.findByTicker(ticker).orElse(null);
        if (stock == null) return; // S&P 500 외 종목은 무시

        earningsCalendarRepository.findByStockTickerAndScheduledAt(ticker, scheduledAt)
                .ifPresentOrElse(
                        existing -> existing.update(scheduledAt, confirmed),
                        () -> earningsCalendarRepository.save(
                                EarningsCalendar.builder()
                                        .stock(stock)
                                        .scheduledAt(scheduledAt)
                                        .confirmed(confirmed)
                                        .build())
                );
    }
}
