package com.earningwhisperer.domain.portfolio;

import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

@Service
@RequiredArgsConstructor
public class PortfolioSettingsService {

    private final PortfolioSettingsRepository portfolioSettingsRepository;

    @Transactional(readOnly = true)
    public PortfolioSettings getSettings(Long userId) {
        return portfolioSettingsRepository.findByUserId(userId)
                .orElseThrow(() -> new IllegalArgumentException("포트폴리오 설정을 찾을 수 없습니다. userId=" + userId));
    }

    @Transactional
    public PortfolioSettings updateSettings(Long userId, Double buyAmountRatio, Double maxPositionRatio,
                                            Integer cooldownMinutes, Double emaThreshold, TradingMode tradingMode) {
        PortfolioSettings settings = getSettings(userId);
        settings.update(buyAmountRatio, maxPositionRatio, cooldownMinutes, emaThreshold, tradingMode);
        return settings;
    }
}
