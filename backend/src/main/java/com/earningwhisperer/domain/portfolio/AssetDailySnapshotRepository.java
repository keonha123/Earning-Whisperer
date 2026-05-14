package com.earningwhisperer.domain.portfolio;

import org.springframework.data.jpa.repository.JpaRepository;

import java.time.LocalDate;
import java.util.List;
import java.util.Optional;

public interface AssetDailySnapshotRepository extends JpaRepository<AssetDailySnapshot, Long> {

    Optional<AssetDailySnapshot> findByUserIdAndSnapshotDate(Long userId, LocalDate snapshotDate);

    List<AssetDailySnapshot> findByUserIdAndSnapshotDateBetweenOrderBySnapshotDateAsc(
            Long userId, LocalDate from, LocalDate to);
}
