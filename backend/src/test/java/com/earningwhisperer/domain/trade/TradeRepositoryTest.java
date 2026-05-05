package com.earningwhisperer.domain.trade;

import com.earningwhisperer.domain.signal.TradeAction;
import com.earningwhisperer.domain.user.User;
import com.earningwhisperer.domain.user.UserRepository;
import com.earningwhisperer.global.config.JpaConfig;
import org.hibernate.resource.jdbc.spi.StatementInspector;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.orm.jpa.DataJpaTest;
import org.springframework.context.annotation.Import;
import org.springframework.test.context.TestPropertySource;

import java.time.LocalDateTime;
import java.util.List;
import java.util.Optional;
import java.util.concurrent.CopyOnWriteArrayList;

import static org.assertj.core.api.Assertions.assertThat;

@DataJpaTest
@Import(JpaConfig.class)
@TestPropertySource(properties = {
        "spring.jpa.properties.hibernate.session_factory.statement_inspector=" +
                "com.earningwhisperer.domain.trade.TradeRepositoryTest$CapturingStatementInspector"
})
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

    @Test
    @DisplayName("findByBrokerAccountIdAndStatusAndCreatedAtAfter - threshold 이후 PENDING 만 반환")
    void findByBrokerAccountIdAndStatusAndCreatedAtAfter_미만료_PENDING_반환() {
        // Arrange — PENDING 2건 저장 (현재 시각 기준)
        long brokerAccountId = 100L;
        tradeRepository.save(buildTrade(user, brokerAccountId, "NVDA", TradeAction.BUY));
        tradeRepository.save(buildTrade(user, brokerAccountId, "TSLA", TradeAction.SELL));

        LocalDateTime threshold = LocalDateTime.now().minusSeconds(30);

        // Act
        List<Trade> result = tradeRepository
                .findByBrokerAccountIdAndStatusAndCreatedAtAfter(brokerAccountId, TradeStatus.PENDING, threshold);

        // Assert — threshold 이후에 만들어졌으므로 모두 반환
        assertThat(result).hasSize(2);

        // Act2 — threshold 가 미래이면 결과 없음
        List<Trade> empty = tradeRepository
                .findByBrokerAccountIdAndStatusAndCreatedAtAfter(brokerAccountId, TradeStatus.PENDING,
                        LocalDateTime.now().plusMinutes(1));

        // Assert
        assertThat(empty).isEmpty();
    }

    @Test
    @DisplayName("findByIdForUpdate - 정상 row 반환 / 없는 id 면 empty")
    void findByIdForUpdate_정상_row_반환_없는_id면_empty() {
        // Arrange
        Trade saved = tradeRepository.save(buildTrade(user, "NVDA", TradeAction.BUY));

        // Act — 존재하는 id 는 row 반환 (PESSIMISTIC_WRITE 락 + SELECT ... FOR UPDATE 발행)
        Optional<Trade> found = tradeRepository.findByIdForUpdate(saved.getId());

        // Assert
        assertThat(found).isPresent();
        assertThat(found.get().getId()).isEqualTo(saved.getId());

        // Act2 — 없는 id 는 empty
        Optional<Trade> missing = tradeRepository.findByIdForUpdate(-1L);

        // Assert
        assertThat(missing).isEmpty();
    }

    @Test
    @DisplayName("findByIdForUpdate - 실제 SQL 에 'for update' 토큰 포함 (PESSIMISTIC_WRITE 회귀 가드)")
    void findByIdForUpdate_SQL_for_update_토큰_포함() {
        // Arrange
        Trade saved = tradeRepository.save(buildTrade(user, "NVDA", TradeAction.BUY));
        CapturingStatementInspector.clear();

        // Act — Statement Inspector 가 Hibernate 가 발행한 SQL 텍스트를 캡처
        tradeRepository.findByIdForUpdate(saved.getId());

        // Assert — 캡처된 SQL 중 한 건이라도 'for update' 토큰 포함 (대소문자 무관)
        boolean hasForUpdate = CapturingStatementInspector.captured().stream()
                .map(String::toLowerCase)
                .anyMatch(sql -> sql.contains("for update"));
        assertThat(hasForUpdate)
                .as("PESSIMISTIC_WRITE 락이 'SELECT ... FOR UPDATE' 형태로 발행되어야 한다. captured=%s",
                        CapturingStatementInspector.captured())
                .isTrue();
    }

    @Test
    @DisplayName("expirePendingBefore - threshold 이전 PENDING 만 EXPIRED 로 일괄 update")
    void expirePendingBefore_PENDING_만_EXPIRED로_전환() {
        // Arrange
        Trade pending = tradeRepository.save(buildTrade(user, 100L, "NVDA", TradeAction.BUY));
        Long pendingId = pending.getId();

        // Act — 미래 threshold 면 모두 만료 대상
        int affected = tradeRepository.expirePendingBefore(LocalDateTime.now().plusMinutes(1));

        // Assert — UPDATE row 수 + DB 상태 검증
        assertThat(affected).isEqualTo(1);
        Trade reloaded = tradeRepository.findById(pendingId).orElseThrow();
        assertThat(reloaded.getStatus()).isEqualTo(TradeStatus.EXPIRED);

        // Act2 — 이미 EXPIRED 면 두 번째 호출은 0 (멱등)
        int second = tradeRepository.expirePendingBefore(LocalDateTime.now().plusMinutes(1));

        assertThat(second).isZero();
    }

    private Trade buildTrade(User owner, String ticker, TradeAction side) {
        return buildTrade(owner, 100L, ticker, side);
    }

    private Trade buildTrade(User owner, long brokerAccountId, String ticker, TradeAction side) {
        return Trade.builder()
                .user(owner)
                .brokerAccountId(brokerAccountId)
                .ticker(ticker)
                .side(side)
                .orderType(OrderType.MARKET)
                .orderQty(10)
                .price(0.0)
                .build();
    }

    /**
     * Hibernate 가 발행하는 모든 JDBC SQL 을 캡처하는 StatementInspector.
     *
     * <p>{@code spring.jpa.properties.hibernate.session_factory.statement_inspector} 프로퍼티로
     * Hibernate 가 직접 인스턴스를 생성하므로 public + no-arg constructor 가 필요하다.
     * 캡처 버퍼는 static (인스턴스 간 공유) 으로 유지해 테스트가 어디서든 검증할 수 있게 한다.
     */
    public static class CapturingStatementInspector implements StatementInspector {

        private static final CopyOnWriteArrayList<String> CAPTURED = new CopyOnWriteArrayList<>();

        @Override
        public String inspect(String sql) {
            CAPTURED.add(sql);
            return sql;
        }

        static void clear() {
            CAPTURED.clear();
        }

        static List<String> captured() {
            return List.copyOf(CAPTURED);
        }
    }
}
