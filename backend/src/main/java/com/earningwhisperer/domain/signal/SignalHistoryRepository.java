package com.earningwhisperer.domain.signal;

import org.springframework.data.jpa.repository.JpaRepository;

import java.util.List;

public interface SignalHistoryRepository extends JpaRepository<SignalHistory, Long> {

    List<SignalHistory> findByUserIdAndTickerOrderByCreatedAtDesc(Long userId, String ticker);

    List<SignalHistory> findByUserIdOrderByCreatedAtDesc(Long userId);
}
