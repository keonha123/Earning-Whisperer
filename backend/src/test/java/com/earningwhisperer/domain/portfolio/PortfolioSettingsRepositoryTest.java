package com.earningwhisperer.domain.portfolio;

import com.earningwhisperer.domain.user.User;
import com.earningwhisperer.domain.user.UserRepository;
import com.earningwhisperer.global.config.JpaConfig;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.orm.jpa.DataJpaTest;
import org.springframework.context.annotation.Import;

import java.util.Optional;

import static org.assertj.core.api.Assertions.assertThat;

@DataJpaTest
@Import(JpaConfig.class)
@DisplayName("PortfolioSettingsRepository 슬라이스 테스트")
class PortfolioSettingsRepositoryTest {

    @Autowired
    private PortfolioSettingsRepository portfolioSettingsRepository;

    @Autowired
    private UserRepository userRepository;

    @Test
    @DisplayName("findByUserId - User의 포트폴리오 설정을 조회한다")
    void findByUserId_사용자의_포트폴리오_설정을_반환한다() {
        // Arrange
        User user = userRepository.save(User.builder()
                .email("test@test.com")
                .password("password")
                .nickname("tester")
                .build());

        portfolioSettingsRepository.save(PortfolioSettings.builder()
                .user(user)
                .buyAmountRatio(0.1)
                .maxPositionRatio(0.3)
                .cooldownMinutes(5)
                .emaThreshold(0.6)
                .tradingMode(TradingMode.MANUAL)
                .build());

        // Act
        Optional<PortfolioSettings> result = portfolioSettingsRepository.findByUserId(user.getId());

        // Assert
        assertThat(result).isPresent();
        assertThat(result.get().getBuyAmountRatio()).isEqualTo(0.1);
        assertThat(result.get().getTradingMode()).isEqualTo(TradingMode.MANUAL);
    }

    @Test
    @DisplayName("findByUserId - 설정이 없는 사용자는 빈 Optional을 반환한다")
    void findByUserId_설정이_없는_사용자는_빈값을_반환한다() {
        // Act
        Optional<PortfolioSettings> result = portfolioSettingsRepository.findByUserId(999L);

        // Assert
        assertThat(result).isEmpty();
    }
}
