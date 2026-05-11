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

    /**
     * 모든 사용자/브로커 계정의 Position 에 등록된 unique ticker 목록.
     *
     * <p>DailyBarSync 가 watchlist 외 보유 종목까지 포함해 일봉을 사전 적재할 수 있게 한다.
     * Position.computePositionRatio 의 시장기준 비중 계산이 daily_bar fallback 으로
     * 떨어지는 케이스를 차단.
     */
    @Query("SELECT DISTINCT p.ticker FROM Position p WHERE p.ticker IS NOT NULL")
    List<String> findDistinctTickers();
}
