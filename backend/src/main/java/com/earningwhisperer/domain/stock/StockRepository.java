package com.earningwhisperer.domain.stock;

import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Query;

import java.util.Collection;
import java.util.List;
import java.util.Optional;

public interface StockRepository extends JpaRepository<Stock, Long> {

    Optional<Stock> findByTicker(String ticker);

    boolean existsByTicker(String ticker);

    List<Stock> findByActiveTrue();

    List<Stock> findByActiveTrueAndTickerContainingIgnoreCaseOrActiveTrueAndCompanyNameContainingIgnoreCase(
            String ticker, String companyName);

    List<Stock> findByTickerIn(Collection<String> tickers);

    @Query("""
            SELECT s, sm FROM Stock s
            LEFT JOIN StockMeta sm ON sm.stock.id = s.id
            WHERE s.active = true
            ORDER BY COALESCE(sm.marketCapUsd, 0) DESC
            """)
    List<Object[]> findAllActiveWithMetaSorted();
}
