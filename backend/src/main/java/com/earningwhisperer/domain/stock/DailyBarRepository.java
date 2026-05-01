package com.earningwhisperer.domain.stock;

import org.springframework.data.jpa.repository.JpaRepository;

import java.time.LocalDate;
import java.util.List;
import java.util.Optional;

public interface DailyBarRepository extends JpaRepository<DailyBar, Long> {

    List<DailyBar> findTop30ByStock_IdOrderByBarDateDesc(Long stockId);

    Optional<DailyBar> findByStock_IdAndBarDate(Long stockId, LocalDate barDate);

    List<DailyBar> findByStock_IdAndBarDateBetween(Long stockId, LocalDate from, LocalDate to);
}
