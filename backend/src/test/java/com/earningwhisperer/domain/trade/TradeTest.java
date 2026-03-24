package com.earningwhisperer.domain.trade;

import com.earningwhisperer.domain.signal.TradeAction;
import com.earningwhisperer.domain.user.User;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;

@DisplayName("Trade 엔티티 단위 테스트")
class TradeTest {

    private User user;

    @BeforeEach
    void setUp() {
        user = User.builder()
                .email("test@test.com")
                .password("password")
                .nickname("tester")
                .build();
    }

    @Test
    @DisplayName("Builder로 생성 시 초기 status는 PENDING, executedQty는 0이다")
    void builder_생성시_초기값이_올바르게_설정된다() {
        // Arrange & Act
        Trade trade = Trade.builder()
                .user(user)
                .ticker("NVDA")
                .side(TradeAction.BUY)
                .orderType(OrderType.MARKET)
                .orderQty(10)
                .price(0.0)
                .build();

        // Assert
        assertThat(trade.getStatus()).isEqualTo(TradeStatus.PENDING);
        assertThat(trade.getExecutedQty()).isEqualTo(0);
        assertThat(trade.getBrokerOrderId()).isNull();
    }

    @Test
    @DisplayName("executed() 호출 시 status가 EXECUTED로 변경되고 체결 정보가 저장된다")
    void executed_호출시_상태가_EXECUTED로_변경된다() {
        // Arrange
        Trade trade = Trade.builder()
                .user(user)
                .ticker("NVDA")
                .side(TradeAction.BUY)
                .orderType(OrderType.MARKET)
                .orderQty(10)
                .price(0.0)
                .build();

        // Act
        trade.executed(10, "BROKER-ORDER-001");

        // Assert
        assertThat(trade.getStatus()).isEqualTo(TradeStatus.EXECUTED);
        assertThat(trade.getExecutedQty()).isEqualTo(10);
        assertThat(trade.getBrokerOrderId()).isEqualTo("BROKER-ORDER-001");
    }

    @Test
    @DisplayName("failed() 호출 시 status가 FAILED로 변경된다")
    void failed_호출시_상태가_FAILED로_변경된다() {
        // Arrange
        Trade trade = Trade.builder()
                .user(user)
                .ticker("NVDA")
                .side(TradeAction.BUY)
                .orderType(OrderType.MARKET)
                .orderQty(10)
                .price(0.0)
                .build();

        // Act
        trade.failed();

        // Assert
        assertThat(trade.getStatus()).isEqualTo(TradeStatus.FAILED);
    }
}
