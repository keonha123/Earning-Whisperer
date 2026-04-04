package com.earningwhisperer.domain.portfolio;

import com.earningwhisperer.domain.user.User;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;

@DisplayName("PortfolioSettings 엔티티 단위 테스트")
class PortfolioSettingsTest {

    @Test
    @DisplayName("update() 호출 시 모든 설정 필드가 새 값으로 변경된다")
    void update_호출시_모든_필드가_변경된다() {
        // Arrange
        User user = User.builder()
                .email("test@test.com")
                .password("password")
                .nickname("tester")
                .build();

        PortfolioSettings settings = PortfolioSettings.builder()
                .user(user)
                .buyAmountRatio(0.1)
                .maxPositionRatio(0.3)
                .cooldownMinutes(5)
                .emaThreshold(0.6)
                .tradingMode(TradingMode.MANUAL)
                .build();

        // Act
        settings.update(0.2, 0.5, 10, 0.7, TradingMode.AUTO_PILOT);

        // Assert
        assertThat(settings.getBuyAmountRatio()).isEqualTo(0.2);
        assertThat(settings.getMaxPositionRatio()).isEqualTo(0.5);
        assertThat(settings.getCooldownMinutes()).isEqualTo(10);
        assertThat(settings.getEmaThreshold()).isEqualTo(0.7);
        assertThat(settings.getTradingMode()).isEqualTo(TradingMode.AUTO_PILOT);
    }

    @Test
    @DisplayName("Builder로 생성 시 전달한 값이 그대로 저장된다")
    void builder_생성시_필드값이_올바르게_설정된다() {
        // Arrange & Act
        User user = User.builder()
                .email("test@test.com")
                .password("password")
                .nickname("tester")
                .build();

        PortfolioSettings settings = PortfolioSettings.builder()
                .user(user)
                .buyAmountRatio(0.1)
                .maxPositionRatio(0.3)
                .cooldownMinutes(5)
                .emaThreshold(0.6)
                .tradingMode(TradingMode.SEMI_AUTO)
                .build();

        // Assert
        assertThat(settings.getBuyAmountRatio()).isEqualTo(0.1);
        assertThat(settings.getMaxPositionRatio()).isEqualTo(0.3);
        assertThat(settings.getCooldownMinutes()).isEqualTo(5);
        assertThat(settings.getEmaThreshold()).isEqualTo(0.6);
        assertThat(settings.getTradingMode()).isEqualTo(TradingMode.SEMI_AUTO);
    }
}
