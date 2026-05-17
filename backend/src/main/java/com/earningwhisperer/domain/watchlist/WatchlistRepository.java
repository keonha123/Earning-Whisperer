package com.earningwhisperer.domain.watchlist;

import com.earningwhisperer.domain.stock.Stock;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;

import java.util.List;
import java.util.Optional;

public interface WatchlistRepository extends JpaRepository<WatchlistItem, Long> {

    @Query("SELECT w FROM WatchlistItem w JOIN FETCH w.stock WHERE w.user.id = :userId ORDER BY w.createdAt DESC")
    List<WatchlistItem> findByUserIdWithStock(@Param("userId") Long userId);

    Optional<WatchlistItem> findByUserIdAndStockTicker(Long userId, String ticker);

    boolean existsByUserIdAndStockTicker(Long userId, String ticker);

    /**
     * 모든 사용자의 watchlist 에 등록된 unique Stock 목록.
     *
     * <p>스케줄러가 트랜잭션 없이 외부에서 stockId/ticker 만 추출하기 위해 EAGER 로딩되는
     * Stock 리스트를 반환한다. lazy proxy 가 detached 상태로 새어나가는 것을 방지.
     * 같은 ticker 가 N명의 사용자 watchlist 에 있어도 1건만 반환된다.
     */
    @Query("SELECT DISTINCT w.stock FROM WatchlistItem w")
    List<Stock> findDistinctStocks();
}
