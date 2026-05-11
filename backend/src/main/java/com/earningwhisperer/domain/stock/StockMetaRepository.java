package com.earningwhisperer.domain.stock;

import org.springframework.data.jpa.repository.JpaRepository;

import java.time.Instant;
import java.util.List;
import java.util.Optional;

public interface StockMetaRepository extends JpaRepository<StockMeta, Long> {

    Optional<StockMeta> findByStock_Id(Long stockId);

    List<StockMeta> findByLastSyncedAtBefore(Instant threshold);
}
