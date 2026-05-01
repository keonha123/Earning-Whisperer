package com.earningwhisperer.domain.earnings;

import org.springframework.data.jpa.repository.JpaRepository;

import java.util.List;

public interface EarningsResultRepository extends JpaRepository<EarningsResult, Long> {

    List<EarningsResult> findTop4ByStock_IdOrderByAnnouncedAtDesc(Long stockId);

    List<EarningsResult> findByPriceReactionPercentIsNull();
}
