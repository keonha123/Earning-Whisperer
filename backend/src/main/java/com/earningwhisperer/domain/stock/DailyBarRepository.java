package com.earningwhisperer.domain.stock;

import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;

import java.time.LocalDate;
import java.util.Collection;
import java.util.List;
import java.util.Optional;

public interface DailyBarRepository extends JpaRepository<DailyBar, Long> {

    List<DailyBar> findTop30ByStock_IdOrderByBarDateDesc(Long stockId);

    Optional<DailyBar> findByStock_IdAndBarDate(Long stockId, LocalDate barDate);

    List<DailyBar> findByStock_IdAndBarDateBetween(Long stockId, LocalDate from, LocalDate to);

    /**
     * ticker 목록에 대해 각 ticker 의 가장 최근 종가를 일괄 조회. SignalService 의 시장 기준 비중 계산에서
     * N+1 회피용. ticker 가 stocks 테이블에 없거나 daily_bar 가 비어있으면 결과 List 에 포함되지 않음
     * (호출 측 fallback 처리).
     *
     * <p>close_price 는 BigDecimal 컬럼이므로 cast(... as double) 로 명시 변환 — H2 / MySQL 양쪽 모두
     * Hibernate 6 표준 함수로 동일하게 동작한다.
     */
    @Query("""
            SELECT new com.earningwhisperer.domain.stock.TickerLatestClose(
                       s.ticker, cast(db.closePrice as double))
            FROM DailyBar db JOIN db.stock s
            WHERE s.ticker IN :tickers
              AND db.barDate = (
                  SELECT MAX(db2.barDate) FROM DailyBar db2 WHERE db2.stock.id = s.id
              )
            """)
    List<TickerLatestClose> findLatestClosesByTickers(@Param("tickers") Collection<String> tickers);
}
