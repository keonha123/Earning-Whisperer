package com.earningwhisperer.domain.trade;

import com.earningwhisperer.domain.signal.TradeAction;
import com.earningwhisperer.domain.user.User;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

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
        trade.executed(10, 125.50, "BROKER-ORDER-001");

        // Assert
        assertThat(trade.getStatus()).isEqualTo(TradeStatus.EXECUTED);
        assertThat(trade.getExecutedQty()).isEqualTo(10);
        assertThat(trade.getExecutedPrice()).isEqualTo(125.50);
        assertThat(trade.getBrokerOrderId()).isEqualTo("BROKER-ORDER-001");
    }

    @Test
    @DisplayName("executed() 호출 시 센티널 orderQty(0)가 실체결 수량으로 갱신된다")
    void executed_호출시_센티널_orderQty가_실수량으로_갱신된다() {
        // Arrange — PENDING 시점엔 orderQty=0 센티널
        Trade trade = Trade.builder()
                .user(user)
                .ticker("NVDA")
                .side(TradeAction.BUY)
                .orderType(OrderType.MARKET)
                .orderQty(0)
                .price(0.0)
                .build();

        // Act — Trading Terminal이 3주 체결 보고
        trade.executed(3, 125.50, "BROKER-ORDER-777");

        // Assert — orderQty, executedQty 모두 3
        assertThat(trade.getOrderQty()).isEqualTo(3);
        assertThat(trade.getExecutedQty()).isEqualTo(3);
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

    @Test
    @DisplayName("executed() 동일 입력으로 재호출 시 멱등하게 no-op 한다")
    void executed_동일_입력_재호출은_멱등() {
        Trade trade = pendingTrade();
        trade.executed(3, 125.50, "BROKER-1");

        // Act — 같은 입력으로 한 번 더 호출 (네트워크 retry 시나리오)
        trade.executed(3, 125.50, "BROKER-1");

        assertThat(trade.getStatus()).isEqualTo(TradeStatus.EXECUTED);
        assertThat(trade.getExecutedQty()).isEqualTo(3);
        assertThat(trade.getBrokerOrderId()).isEqualTo("BROKER-1");
    }

    @Test
    @DisplayName("executed() 후 다른 결과로 재호출 시 TradeStateConflictException")
    void executed_다른_입력_재호출은_충돌() {
        Trade trade = pendingTrade();
        trade.executed(3, 125.50, "BROKER-1");

        assertThatThrownBy(() -> trade.executed(5, 130.00, "BROKER-2"))
                .isInstanceOf(TradeStateConflictException.class);
    }

    @Test
    @DisplayName("failed() 재호출 시 멱등하게 no-op 한다")
    void failed_재호출은_멱등() {
        Trade trade = pendingTrade();
        trade.failed();

        // Act
        trade.failed();

        assertThat(trade.getStatus()).isEqualTo(TradeStatus.FAILED);
    }

    @Test
    @DisplayName("EXECUTED 상태에서 failed() 호출 시 TradeStateConflictException")
    void EXECUTED에서_failed_시도는_충돌() {
        Trade trade = pendingTrade();
        trade.executed(3, 125.50, "BROKER-1");

        assertThatThrownBy(trade::failed)
                .isInstanceOf(TradeStateConflictException.class);
    }

    @Test
    @DisplayName("FAILED 상태에서 executed() 호출 시 TradeStateConflictException")
    void FAILED에서_executed_시도는_충돌() {
        Trade trade = pendingTrade();
        trade.failed();

        assertThatThrownBy(() -> trade.executed(3, 125.50, "BROKER-1"))
                .isInstanceOf(TradeStateConflictException.class);
    }

    @Test
    @DisplayName("expire() 호출 시 status 가 EXPIRED 로 변경된다")
    void expire_호출시_상태가_EXPIRED로_변경된다() {
        Trade trade = pendingTrade();

        trade.expire();

        assertThat(trade.getStatus()).isEqualTo(TradeStatus.EXPIRED);
    }

    @Test
    @DisplayName("expire() 재호출은 멱등하게 no-op")
    void expire_재호출은_멱등() {
        Trade trade = pendingTrade();
        trade.expire();

        trade.expire();

        assertThat(trade.getStatus()).isEqualTo(TradeStatus.EXPIRED);
    }

    @Test
    @DisplayName("EXECUTED 상태에서 expire() 호출 시 TradeStateConflictException")
    void EXECUTED에서_expire_시도는_충돌() {
        Trade trade = pendingTrade();
        trade.executed(3, 125.50, "BROKER-1");

        assertThatThrownBy(trade::expire)
                .isInstanceOf(TradeStateConflictException.class);
    }

    @Test
    @DisplayName("EXPIRED 상태에서 executed() 호출 시 TradeStateConflictException")
    void EXPIRED에서_executed_시도는_충돌() {
        Trade trade = pendingTrade();
        trade.expire();

        assertThatThrownBy(() -> trade.executed(3, 125.50, "BROKER-1"))
                .isInstanceOf(TradeStateConflictException.class);
    }

    @Test
    @DisplayName("orderRatio/aiScore 가 builder 로 보존된다")
    void builder_orderRatio_aiScore_보존() {
        Trade trade = Trade.builder()
                .user(user)
                .ticker("NVDA")
                .side(TradeAction.BUY)
                .orderType(OrderType.MARKET)
                .orderQty(0)
                .price(0.0)
                .orderRatio(0.1)
                .aiScore(0.85)
                .build();

        assertThat(trade.getOrderRatio()).isEqualTo(0.1);
        assertThat(trade.getAiScore()).isEqualTo(0.85);
    }

    private Trade pendingTrade() {
        return Trade.builder()
                .user(user)
                .ticker("NVDA")
                .side(TradeAction.BUY)
                .orderType(OrderType.MARKET)
                .orderQty(0)
                .price(0.0)
                .build();
    }
}
