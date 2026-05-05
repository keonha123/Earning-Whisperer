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

    @BeforeEach
    void setUp() {
        user = userRepository.save(User.builder()
                .email("p@test.com").password("pwd").nickname("p").build());
    }

    @Test
    @DisplayName("findByUserId - 해당 사용자의 모든 position 반환")
    void findByUserId_사용자별_position_반환() {
        positionRepository.save(Position.builder().user(user).ticker("NVDA").quantity(10).avgPrice(125.0).build());
        positionRepository.save(Position.builder().user(user).ticker("TSLA").quantity(5).avgPrice(200.0).build());

        List<Position> result = positionRepository.findByUserId(user.getId());

        assertThat(result).hasSize(2);
    }

    @Test
    @DisplayName("findByUserIdAndTicker - 특정 ticker 조회")
    void findByUserIdAndTicker_특정_ticker() {
        positionRepository.save(Position.builder().user(user).ticker("NVDA").quantity(10).avgPrice(125.0).build());

        assertThat(positionRepository.findByUserIdAndTicker(user.getId(), "NVDA")).isPresent();
        assertThat(positionRepository.findByUserIdAndTicker(user.getId(), "AAPL")).isEmpty();
    }

    @Test
    @DisplayName("deleteByUserIdAndTickerNotIn - 보낸 목록에 없는 ticker 만 삭제")
    void deleteByUserIdAndTickerNotIn_누락_삭제() {
        positionRepository.save(Position.builder().user(user).ticker("NVDA").quantity(10).avgPrice(125.0).build());
        positionRepository.save(Position.builder().user(user).ticker("TSLA").quantity(5).avgPrice(200.0).build());
        positionRepository.save(Position.builder().user(user).ticker("AAPL").quantity(3).avgPrice(180.0).build());

        // NVDA, TSLA 만 유지 (AAPL 은 사용자가 매도해서 더이상 보유 안 함)
        int deleted = positionRepository.deleteByUserIdAndTickerNotIn(user.getId(), Set.of("NVDA", "TSLA"));

        assertThat(deleted).isEqualTo(1);
        List<Position> remaining = positionRepository.findByUserId(user.getId());
        assertThat(remaining).extracting(Position::getTicker).containsExactlyInAnyOrder("NVDA", "TSLA");
    }

    @Test
    @DisplayName("deleteByUserId - 사용자의 모든 position 삭제")
    void deleteByUserId_전체_삭제() {
        positionRepository.save(Position.builder().user(user).ticker("NVDA").quantity(10).avgPrice(125.0).build());
        positionRepository.save(Position.builder().user(user).ticker("TSLA").quantity(5).avgPrice(200.0).build());

        int deleted = positionRepository.deleteByUserId(user.getId());

        assertThat(deleted).isEqualTo(2);
        assertThat(positionRepository.findByUserId(user.getId())).isEmpty();
    }

    @Test
    @DisplayName("unique(user_id, ticker) - 다른 사용자는 같은 ticker 보유 가능")
    void unique_제약_사용자별_분리() {
        User otherUser = userRepository.save(User.builder()
                .email("o@test.com").password("pwd").nickname("o").build());
        positionRepository.save(Position.builder().user(user).ticker("NVDA").quantity(10).avgPrice(125.0).build());
        positionRepository.save(Position.builder().user(otherUser).ticker("NVDA").quantity(20).avgPrice(130.0).build());

        assertThat(positionRepository.findByUserId(user.getId())).hasSize(1);
        assertThat(positionRepository.findByUserId(otherUser.getId())).hasSize(1);
    }
}
