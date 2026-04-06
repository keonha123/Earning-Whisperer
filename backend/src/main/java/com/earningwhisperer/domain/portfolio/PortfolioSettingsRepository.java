package com.earningwhisperer.domain.portfolio;

import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Query;

import java.util.List;
import java.util.Optional;

public interface PortfolioSettingsRepository extends JpaRepository<PortfolioSettings, Long> {

    Optional<PortfolioSettings> findByUserId(Long userId);

    @Query("SELECT ps FROM PortfolioSettings ps JOIN FETCH ps.user")
    List<PortfolioSettings> findAllWithUser();
}
