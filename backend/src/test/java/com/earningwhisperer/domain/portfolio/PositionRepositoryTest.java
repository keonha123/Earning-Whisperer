package com.earningwhisperer.domain.portfolio;

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
import java.util.Set;

import static org.assertj.core.api.Assertions.assertThat;

@DataJpaTest
@Import(JpaConfig.class)
@DisplayName("PositionRepository 슬라이스 테스트")
class PositionRepositoryTest {

    @Autowired private PositionRepository positionRepository;
    @Autowired private UserRepository userRepository;

    private User user;
    private final long brokerAccountId = 100L;

    @BeforeEach
    void setUp() {
        user = userRepository.save(User.builder()
                .email("p@test.com").password("pwd").nickname("p").build());
    }

    @Test
    @DisplayName("findByBrokerAccountId - 해당 broker 의 모든 position 반환")
    void findByBrokerAccountId_broker별_position_반환() {
        positionRepository.save(Position.builder().user(user).brokerAccountId(brokerAccountId)
                .ticker("NVDA").quantity(10).avgPrice(125.0).build());
        positionRepository.save(Position.builder().user(user).brokerAccountId(brokerAccountId)
                .ticker("TSLA").quantity(5).avgPrice(200.0).build());

        List<Position> result = positionRepository.findByBrokerAccountId(brokerAccountId);

        assertThat(result).hasSize(2);
    }

    @Test
    @DisplayName("findByBrokerAccountIdAndTicker - 특정 ticker 조회")
    void findByBrokerAccountIdAndTicker_특정_ticker() {
        positionRepository.save(Position.builder().user(user).brokerAccountId(brokerAccountId)
                .ticker("NVDA").quantity(10).avgPrice(125.0).build());

        assertThat(positionRepository.findByBrokerAccountIdAndTicker(brokerAccountId, "NVDA")).isPresent();
        assertThat(positionRepository.findByBrokerAccountIdAndTicker(brokerAccountId, "AAPL")).isEmpty();
    }

    @Test
    @DisplayName("deleteByBrokerAccountIdAndTickerNotIn - 보낸 목록에 없는 ticker 만 삭제")
    void deleteByBrokerAccountIdAndTickerNotIn_누락_삭제() {
        positionRepository.save(Position.builder().user(user).brokerAccountId(brokerAccountId)
                .ticker("NVDA").quantity(10).avgPrice(125.0).build());
        positionRepository.save(Position.builder().user(user).brokerAccountId(brokerAccountId)
                .ticker("TSLA").quantity(5).avgPrice(200.0).build());
        positionRepository.save(Position.builder().user(user).brokerAccountId(brokerAccountId)
                .ticker("AAPL").quantity(3).avgPrice(180.0).build());

        int deleted = positionRepository.deleteByBrokerAccountIdAndTickerNotIn(
                brokerAccountId, Set.of("NVDA", "TSLA"));

        assertThat(deleted).isEqualTo(1);
        List<Position> remaining = positionRepository.findByBrokerAccountId(brokerAccountId);
        assertThat(remaining).extracting(Position::getTicker).containsExactlyInAnyOrder("NVDA", "TSLA");
    }

    @Test
    @DisplayName("deleteByBrokerAccountId - 해당 broker 의 모든 position 삭제")
    void deleteByBrokerAccountId_전체_삭제() {
        positionRepository.save(Position.builder().user(user).brokerAccountId(brokerAccountId)
                .ticker("NVDA").quantity(10).avgPrice(125.0).build());
        positionRepository.save(Position.builder().user(user).brokerAccountId(brokerAccountId)
                .ticker("TSLA").quantity(5).avgPrice(200.0).build());

        int deleted = positionRepository.deleteByBrokerAccountId(brokerAccountId);

        assertThat(deleted).isEqualTo(2);
        assertThat(positionRepository.findByBrokerAccountId(brokerAccountId)).isEmpty();
    }

    @Test
    @DisplayName("unique(broker_account_id, ticker) - 다른 broker_account 면 같은 ticker 보유 가능")
    void unique_제약_broker별_분리() {
        positionRepository.save(Position.builder().user(user).brokerAccountId(100L)
                .ticker("NVDA").quantity(10).avgPrice(125.0).build());
        positionRepository.save(Position.builder().user(user).brokerAccountId(200L)
                .ticker("NVDA").quantity(20).avgPrice(130.0).build());

        assertThat(positionRepository.findByBrokerAccountId(100L)).hasSize(1);
        assertThat(positionRepository.findByBrokerAccountId(200L)).hasSize(1);
    }
}
