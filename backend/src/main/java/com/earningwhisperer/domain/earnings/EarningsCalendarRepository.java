package com.earningwhisperer.domain.earnings;

import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;

import java.time.Instant;
import java.util.List;
import java.util.Optional;

public interface EarningsCalendarRepository extends JpaRepository<EarningsCalendar, Long> {

    Optional<EarningsCalendar> findByStockTickerAndScheduledAt(String ticker, Instant scheduledAt);

    @Query("""
            SELECT e FROM EarningsCalendar e JOIN FETCH e.stock s
            WHERE s.ticker IN :tickers AND e.scheduledAt >= :from
            ORDER BY e.scheduledAt ASC
            """)
    List<EarningsCalendar> findUpcomingByTickers(
            @Param("tickers") List<String> tickers,
            @Param("from") Instant from);

    @Query("""
            SELECT e FROM EarningsCalendar e JOIN FETCH e.stock
            WHERE e.scheduledAt BETWEEN :from AND :to
            ORDER BY e.scheduledAt ASC
            """)
    List<EarningsCalendar> findByScheduledAtBetween(
            @Param("from") Instant from,
            @Param("to") Instant to);
}
