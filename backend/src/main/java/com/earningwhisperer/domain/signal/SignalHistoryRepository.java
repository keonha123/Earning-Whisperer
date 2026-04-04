package com.earningwhisperer.domain.signal;

import org.springframework.data.jpa.repository.JpaRepository;

import java.util.List;
import java.util.Optional;

public interface SignalHistoryRepository extends JpaRepository<SignalHistory, Long> {

    List<SignalHistory> findByUserIdAndTickerOrderByCreatedAtDesc(Long userId, String ticker);

    List<SignalHistory> findByUserIdOrderByCreatedAtDesc(Long userId);

    /** 쿨다운 체크용: 특정 유저+종목의 가장 최근 신호 1건 조회 */
    Optional<SignalHistory> findTop1ByUserIdAndTickerOrderByCreatedAtDesc(Long userId, String ticker);
}
