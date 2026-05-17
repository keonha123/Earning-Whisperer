package com.earningwhisperer.domain.signal;

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
@DisplayName("SignalHistoryRepository 슬라이스 테스트")
class SignalHistoryRepositoryTest {

    @Autowired
    private SignalHistoryRepository signalHistoryRepository;

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
    @DisplayName("findByUserIdAndTickerOrderByCreatedAtDesc - 특정 ticker의 시그널만 최신순으로 반환한다")
    void findByUserIdAndTicker_특정_ticker의_시그널을_최신순으로_반환한다() {
        // Arrange
        signalHistoryRepository.save(buildSignal(user, "NVDA", TradeAction.BUY, 1741827000L));
        signalHistoryRepository.save(buildSignal(user, "NVDA", TradeAction.SELL, 1741827060L));
        signalHistoryRepository.save(buildSignal(user, "TSLA", TradeAction.BUY, 1741827120L));

        // Act
        List<SignalHistory> result = signalHistoryRepository
                .findByUserIdAndTickerOrderByCreatedAtDesc(user.getId(), "NVDA");

        // Assert
        assertThat(result).hasSize(2);
        assertThat(result).extracting(SignalHistory::getTicker)
                .containsOnly("NVDA");
        assertThat(result.get(0).getSignalTimestamp())
                .isGreaterThan(result.get(1).getSignalTimestamp());
    }

    @Test
    @DisplayName("findByUserIdOrderByCreatedAtDesc - 해당 사용자의 전체 시그널을 최신순으로 반환한다")
    void findByUserId_전체_시그널을_최신순으로_반환한다() {
        // Arrange
        signalHistoryRepository.save(buildSignal(user, "NVDA", TradeAction.BUY, 1741827000L));
        signalHistoryRepository.save(buildSignal(user, "TSLA", TradeAction.SELL, 1741827060L));

        // Act
        List<SignalHistory> result = signalHistoryRepository
                .findByUserIdOrderByCreatedAtDesc(user.getId());

        // Assert
        assertThat(result).hasSize(2);
    }

    @Test
    @DisplayName("findByUserIdAndTickerOrderByCreatedAtDesc - 다른 사용자의 시그널은 반환하지 않는다")
    void findByUserIdAndTicker_다른_사용자의_시그널은_반환하지_않는다() {
        // Arrange
        User otherUser = userRepository.save(User.builder()
                .email("other@test.com")
                .password("password")
                .nickname("other")
                .build());

        signalHistoryRepository.save(buildSignal(user, "NVDA", TradeAction.BUY, 1741827000L));
        signalHistoryRepository.save(buildSignal(otherUser, "NVDA", TradeAction.SELL, 1741827060L));

        // Act
        List<SignalHistory> result = signalHistoryRepository
                .findByUserIdAndTickerOrderByCreatedAtDesc(user.getId(), "NVDA");

        // Assert
        assertThat(result).hasSize(1);
    }

    private SignalHistory buildSignal(User owner, String ticker, TradeAction action, Long timestamp) {
        return SignalHistory.builder()
                .user(owner)
                .ticker(ticker)
                .aiScore(0.72)
                .rationale("테스트 해설")
                .textChunk("테스트 원문")
                .action(action)
                .signalTimestamp(timestamp)
                .build();
    }
}
