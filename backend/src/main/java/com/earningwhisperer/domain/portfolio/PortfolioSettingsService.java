package com.earningwhisperer.domain.portfolio;

import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.util.List;

@Service
@RequiredArgsConstructor
public class PortfolioSettingsService {

    private final PortfolioSettingsRepository portfolioSettingsRepository;

    @Transactional(readOnly = true)
    public List<PortfolioSettings> getAllSettings() {
        return portfolioSettingsRepository.findAllWithUser();
    }

    @Transactional(readOnly = true)
    public PortfolioSettings getSettings(Long userId) {
        return portfolioSettingsRepository.findByUserId(userId)
                .orElseThrow(() -> new IllegalArgumentException("포트폴리오 설정을 찾을 수 없습니다. userId=" + userId));
    }

    @Transactional
    public PortfolioSettings updateSettings(Long userId, Double buyAmountRatio, Double maxPositionRatio,
                                            Integer cooldownMinutes, Double aiScoreThreshold, TradingMode tradingMode) {
        PortfolioSettings settings = getSettings(userId);
        settings.update(buyAmountRatio, maxPositionRatio, cooldownMinutes, aiScoreThreshold, tradingMode);
        return settings;
    }

    /**
     * Trading Terminal 전용 — aiScoreThreshold는 기존 값을 유지한다.
     */
    @Transactional
    public PortfolioSettings updateFromTerminal(Long userId, Double buyAmountRatio, Double maxPositionRatio,
                                                Integer cooldownMinutes, TradingMode tradingMode) {
        PortfolioSettings settings = getSettings(userId);
        settings.update(buyAmountRatio, maxPositionRatio, cooldownMinutes, settings.getAiScoreThreshold(), tradingMode);
        return settings;
    }

    /**
     * Contract 4b — Trading Terminal 실계좌 잔고 동기화.
     * cashBalance를 저장하여 룰 엔진의 동적 수량 계산에 활용한다.
     */
    @Transactional
    public void syncCashBalance(Long userId, Double cashBalance) {
        PortfolioSettings settings = getSettings(userId);
        settings.syncCashBalance(cashBalance);
    }
}
