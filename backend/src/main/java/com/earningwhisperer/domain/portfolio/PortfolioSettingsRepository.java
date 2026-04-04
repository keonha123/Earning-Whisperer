package com.earningwhisperer.domain.portfolio;

import org.springframework.data.jpa.repository.JpaRepository;

import java.util.Optional;

public interface PortfolioSettingsRepository extends JpaRepository<PortfolioSettings, Long> {

    Optional<PortfolioSettings> findByUserId(Long userId);
}
