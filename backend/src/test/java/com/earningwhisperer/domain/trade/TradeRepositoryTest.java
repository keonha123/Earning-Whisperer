package com.earningwhisperer.domain.trade;

import com.earningwhisperer.domain.signal.TradeAction;
import com.earningwhisperer.domain.user.User;
import com.earningwhisperer.domain.user.UserRepository;
import com.earningwhisperer.global.config.JpaConfig;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.orm.jpa.DataJpaTest;
import org.springframework.context.annotation.Import;

import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;

@DataJpaTest
@Import(JpaConfig.class)
@DisplayName("TradeRepository 슬라이스 테스트")
class TradeRepositoryTest {

    @Autowired
    private TradeRepository tradeRepository;

    @Autowired
    private UserRepository userRepository;

    private User user;

    @BeforeEach
    void setUp() {
        user = userRepository.save(User.builder()
                .email("test@test.com")
                .password("password")
                .nickname("tester")
                .build());
    }

    @Test
    @DisplayName("findByUserIdOrderByCreatedAtDesc - 해당 사용자의 전체 거래를 최신순으로 반환한다")
    void findByUserId_전체_거래를_최신순으로_반환한다() {
        // Arrange
        tradeRepository.save(buildTrade(user, "NVDA", TradeAction.BUY));
        tradeRepository.save(buildTrade(user, "TSLA", TradeAction.SELL));

        // Act
        List<Trade> result = tradeRepository.findByUserIdOrderByCreatedAtDesc(user.getId());

        // Assert
        assertThat(result).hasSize(2);
    }

    @Test
    @DisplayName("findByUserIdAndTickerOrderByCreatedAtDesc - 특정 ticker의 거래만 반환한다")
    void findByUserIdAndTicker_특정_ticker의_거래를_반환한다() {
        // Arrange
        tradeRepository.save(buildTrade(user, "NVDA", TradeAction.BUY));
        tradeRepository.save(buildTrade(user, "NVDA", TradeAction.SELL));
        tradeRepository.save(buildTrade(user, "TSLA", TradeAction.BUY));

        // Act
        List<Trade> result = tradeRepository
                .findByUserIdAndTickerOrderByCreatedAtDesc(user.getId(), "NVDA");

        // Assert
        assertThat(result).hasSize(2);
        assertThat(result).extracting(Trade::getTicker).containsOnly("NVDA");
    }

    @Test
    @DisplayName("findByUserIdOrderByCreatedAtDesc - 다른 사용자의 거래는 반환하지 않는다")
    void findByUserId_다른_사용자의_거래는_반환하지_않는다() {
        // Arrange
        User otherUser = userRepository.save(User.builder()
                .email("other@test.com")
                .password("password")
                .nickname("other")
                .build());

        tradeRepository.save(buildTrade(user, "NVDA", TradeAction.BUY));
        tradeRepository.save(buildTrade(otherUser, "NVDA", TradeAction.BUY));

        // Act
        List<Trade> result = tradeRepository.findByUserIdOrderByCreatedAtDesc(user.getId());

        // Assert
        assertThat(result).hasSize(1);
    }

    private Trade buildTrade(User owner, String ticker, TradeAction side) {
        return Trade.builder()
                .user(owner)
                .ticker(ticker)
                .side(side)
                .orderType(OrderType.MARKET)
                .orderQty(10)
                .price(0.0)
                .build();
    }
}
