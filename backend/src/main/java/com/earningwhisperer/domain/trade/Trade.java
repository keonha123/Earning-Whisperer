package com.earningwhisperer.domain.trade;

import com.earningwhisperer.domain.signal.SignalHistory;
import com.earningwhisperer.domain.signal.TradeAction;
import com.earningwhisperer.domain.user.User;
import jakarta.persistence.*;
import lombok.AccessLevel;
import lombok.Builder;
import lombok.Getter;
import lombok.NoArgsConstructor;

import java.time.LocalDateTime;

@Getter
@NoArgsConstructor(access = AccessLevel.PROTECTED)
@Entity
@Table(name = "trades", indexes = {
        @Index(name = "idx_trade_user_ticker", columnList = "user_id, ticker"),
        @Index(name = "idx_trade_created_at", columnList = "created_at")
})
public class Trade {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @ManyToOne(fetch = FetchType.LAZY)
    @JoinColumn(name = "user_id", nullable = false)
    private User user;

    /**
     * 이 거래를 유발한 AI 시그널 (HOLD이면 null)
     */
    @ManyToOne(fetch = FetchType.LAZY)
    @JoinColumn(name = "signal_id")
    private SignalHistory signal;

    @Column(nullable = false, length = 20)
    private String ticker;

    @Enumerated(EnumType.STRING)
    @Column(nullable = false, length = 10)
    private TradeAction side; // BUY or SELL

    @Enumerated(EnumType.STRING)
    @Column(nullable = false, length = 10)
    private OrderType orderType;

    /**
     * 주문 수량. PENDING 상태에서는 0(센티널) — 실제 수량은 Trading Terminal이 현재가·잔고를 바탕으로
     * 산출하므로 서버 시점에서는 미정이다. 체결 콜백 수신 시 executed()에서 executedQty로 덮어쓴다.
     */
    @Column(nullable = false)
    private Integer orderQty;

    /**
     * 주문 단가 (시장가 주문 시 0)
     */
    @Column(nullable = false)
    private Double price;

    /**
     * 실제 체결된 수량 (체결 전에는 0)
     */
    @Column(nullable = false)
    private Integer executedQty;

    /**
     * 실제 체결 단가 (체결 전에는 null)
     */
    @Column
    private Double executedPrice;

    @Enumerated(EnumType.STRING)
    @Column(nullable = false, length = 10)
    private TradeStatus status;

    /**
     * 증권사가 부여한 주문 ID (조회/취소 시 사용)
     */
    @Column(length = 50)
    private String brokerOrderId;

    @Column(nullable = false)
    private LocalDateTime createdAt;

    @PrePersist
    protected void onCreate() {
        this.createdAt = LocalDateTime.now();
    }

    @Builder
    public Trade(User user, SignalHistory signal, String ticker, TradeAction side,
                 OrderType orderType, Integer orderQty, Double price) {
        this.user = user;
        this.signal = signal;
        this.ticker = ticker;
        this.side = side;
        this.orderType = orderType;
        this.orderQty = orderQty;
        this.price = price;
        this.executedQty = 0;
        this.status = TradeStatus.PENDING;
    }

    public void executed(int executedQty, Double executedPrice, String brokerOrderId) {
        if (this.status != TradeStatus.PENDING) {
            throw new IllegalStateException(
                    "PENDING 상태에서만 체결 전환 가능 — 현재 status=" + this.status + " tradeId=" + this.id);
        }
        this.executedQty = executedQty;
        this.executedPrice = executedPrice;
        this.brokerOrderId = brokerOrderId;
        this.orderQty = executedQty;
        this.status = TradeStatus.EXECUTED;
    }

    public void failed() {
        if (this.status != TradeStatus.PENDING) {
            throw new IllegalStateException(
                    "PENDING 상태에서만 실패 전환 가능 — 현재 status=" + this.status + " tradeId=" + this.id);
        }
        this.status = TradeStatus.FAILED;
    }
}
