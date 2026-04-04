package com.earningwhisperer.domain.trade;

import org.springframework.data.domain.Page;
import org.springframework.data.domain.Pageable;
import org.springframework.data.jpa.repository.JpaRepository;

import java.util.List;

public interface TradeRepository extends JpaRepository<Trade, Long> {

    List<Trade> findByUserIdOrderByCreatedAtDesc(Long userId);

    List<Trade> findByUserIdAndTickerOrderByCreatedAtDesc(Long userId, String ticker);

    Page<Trade> findByUserId(Long userId, Pageable pageable);
}
