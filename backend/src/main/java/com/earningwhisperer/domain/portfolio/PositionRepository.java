package com.earningwhisperer.domain.portfolio;

import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Modifying;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;

import java.util.Collection;
import java.util.List;
import java.util.Optional;

public interface PositionRepository extends JpaRepository<Position, Long> {

    List<Position> findByBrokerAccountId(Long brokerAccountId);

    Optional<Position> findByBrokerAccountIdAndTicker(Long brokerAccountId, String ticker);

    /**
     * Terminal snapshot 동기화 시 보낸 ticker 목록에 없는 BrokerAccount 보유 row 를 일괄 삭제.
     */
    @Modifying(clearAutomatically = true, flushAutomatically = true)
    @Query("DELETE FROM Position p WHERE p.brokerAccountId = :brokerAccountId AND p.ticker NOT IN :tickers")
    int deleteByBrokerAccountIdAndTickerNotIn(@Param("brokerAccountId") Long brokerAccountId,
                                               @Param("tickers") Collection<String> tickers);

    @Modifying(clearAutomatically = true, flushAutomatically = true)
    @Query("DELETE FROM Position p WHERE p.brokerAccountId = :brokerAccountId")
    int deleteByBrokerAccountId(@Param("brokerAccountId") Long brokerAccountId);
}
