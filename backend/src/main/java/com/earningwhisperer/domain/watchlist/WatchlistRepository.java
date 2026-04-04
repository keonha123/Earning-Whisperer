package com.earningwhisperer.domain.watchlist;

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
}
