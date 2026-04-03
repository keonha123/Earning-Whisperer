package com.earningwhisperer.domain.stock;

import org.springframework.data.jpa.repository.JpaRepository;

import java.util.List;
import java.util.Optional;

public interface StockRepository extends JpaRepository<Stock, Long> {

    Optional<Stock> findByTicker(String ticker);

    boolean existsByTicker(String ticker);

    List<Stock> findByActiveTrue();

    List<Stock> findByActiveTrueAndTickerContainingIgnoreCaseOrActiveTrueAndCompanyNameContainingIgnoreCase(
            String ticker, String companyName);
}
