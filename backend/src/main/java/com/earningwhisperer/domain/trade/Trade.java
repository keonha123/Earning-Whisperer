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
import java.util.Objects;

@Getter
@NoArgsConstructor(access = AccessLevel.PROTECTED)
@Entity
@Table(name = "trades",
        indexes = {
                @Index(name = "idx_trade_user_ticker", columnList = "user_id, ticker"),
                @Index(name = "idx_trade_created_at", columnList = "created_at"),
                @Index(name = "idx_trade_broker_account", columnList = "broker_account_id")
        },
        uniqueConstraints = {
                @UniqueConstraint(name = "uk_trade_broker_order_id", columnNames = "broker_order_id")
        })
public class Trade {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @ManyToOne(fetch = FetchType.LAZY)
    @JoinColumn(name = "user_id", nullable = false)
    private User user;

    /**
     * 거래가 일어난 BrokerAccount (모의/실전 또는 다중 계정 분리).
     * SignalService 가 활성 BrokerAccount 만 사용하므로 PENDING 단계에서 박힌 후 변하지 않는다.
     */
    @Column(name = "broker_account_id", nullable = false)
    private Long brokerAccountId;

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

    /**
     * Terminal 로 발행된 주문 비율 (BUY: 예수금 대비 매수, SELL: 보유수량 대비 매도).
     * Terminal 미접속 후 재접속 시 PENDING 명령을 그대로 복원하기 위해 보존한다.
     * 마이그레이션 호환을 위해 nullable.
     */
    @Column
    private Double orderRatio;

    /**
     * Trade 를 유발한 시그널의 AI 점수. 재접속 시 명령 복원용.
     * 마이그레이션 호환을 위해 nullable.
     */
    @Column
    private Double aiScore;

    @Column(nullable = false)
    private LocalDateTime createdAt;

    @PrePersist
    protected void onCreate() {
        this.createdAt = LocalDateTime.now();
    }

    @Builder
    public Trade(User user, Long brokerAccountId, SignalHistory signal, String ticker, TradeAction side,
                 OrderType orderType, Integer orderQty, Double price,
                 Double orderRatio, Double aiScore) {
        this.user = user;
        this.brokerAccountId = brokerAccountId;
        this.signal = signal;
        this.ticker = ticker;
        this.side = side;
        this.orderType = orderType;
        this.orderQty = orderQty;
        this.price = price;
        this.orderRatio = orderRatio;
        this.aiScore = aiScore;
        this.executedQty = 0;
        this.status = TradeStatus.PENDING;
    }

    /**
     * EXECUTED 전이. Trading Terminal 의 콜백은 네트워크 retry 로 동일 페이로드가 중복 도착할 수 있어
     * 같은 입력에 대해서는 멱등으로 동작한다.
     * - PENDING → EXECUTED 정상 전이
     * - 이미 EXECUTED 이고 (executedQty, executedPrice, brokerOrderId) 가 모두 같으면 no-op
     * - 그 외(다른 값으로 EXECUTED, FAILED 에서 전이 시도)는 TradeStateConflictException
     */
    public void executed(int executedQty, Double executedPrice, String brokerOrderId) {
        if (this.status == TradeStatus.EXECUTED) {
            if (this.executedQty == executedQty
                    && Objects.equals(this.executedPrice, executedPrice)
                    && Objects.equals(this.brokerOrderId, brokerOrderId)) {
                return;
            }
            throw new TradeStateConflictException(
                    "이미 EXECUTED 인 Trade 에 다른 체결 결과 콜백 — tradeId=" + this.id);
        }
        if (this.status != TradeStatus.PENDING) {
            throw new TradeStateConflictException(
                    "PENDING 에서만 EXECUTED 전이 가능 — 현재 status=" + this.status + " tradeId=" + this.id);
        }
        this.executedQty = executedQty;
        this.executedPrice = executedPrice;
        this.brokerOrderId = brokerOrderId;
        this.orderQty = executedQty;
        this.status = TradeStatus.EXECUTED;
    }

    /**
     * FAILED 전이. executed() 와 마찬가지로 네트워크 retry 멱등성을 보장한다.
     * - PENDING → FAILED 정상 전이
     * - 이미 FAILED 면 no-op
     * - EXECUTED/EXPIRED 에서 FAILED 전이 시도는 TradeStateConflictException
     */
    public void failed() {
        if (this.status == TradeStatus.FAILED) {
            return;
        }
        if (this.status != TradeStatus.PENDING) {
            throw new TradeStateConflictException(
                    "PENDING 에서만 FAILED 전이 가능 — 현재 status=" + this.status + " tradeId=" + this.id);
        }
        this.status = TradeStatus.FAILED;
    }

    /**
     * EXPIRED 전이. TTL 만료 scheduler 가 호출한다.
     * - PENDING → EXPIRED 정상 전이
     * - 이미 EXPIRED 면 no-op (scheduler 중복 실행 안전)
     * - EXECUTED/FAILED 에서 EXPIRED 전이 시도는 TradeStateConflictException
     *   (콜백이 먼저 도착해 종결된 Trade 는 expire 대상 아님)
     */
    public void expire() {
        if (this.status == TradeStatus.EXPIRED) {
            return;
        }
        if (this.status != TradeStatus.PENDING) {
            throw new TradeStateConflictException(
                    "PENDING 에서만 EXPIRED 전이 가능 — 현재 status=" + this.status + " tradeId=" + this.id);
        }
        this.status = TradeStatus.EXPIRED;
    }
}
