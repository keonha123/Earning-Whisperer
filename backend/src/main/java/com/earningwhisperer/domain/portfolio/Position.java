package com.earningwhisperer.domain.portfolio;

import com.earningwhisperer.domain.user.User;
import com.earningwhisperer.global.common.BaseEntity;
import jakarta.persistence.*;
import lombok.AccessLevel;
import lombok.Builder;
import lombok.Getter;
import lombok.NoArgsConstructor;

import java.time.LocalDateTime;

/**
 * 사용자의 보유 종목 스냅샷.
 *
 * Trading Terminal 이 KIS API 잔고 조회 결과를 동기화한 값. 평균 매수가(avgPrice) 와 수량(quantity)
 * 만 보존하며 실시간 가격은 미보유. RuleEngine 의 maxPositionRatio 검증에 매수 기준 비중을
 * 산출하는 용도로 사용된다.
 */
@Getter
@NoArgsConstructor(access = AccessLevel.PROTECTED)
@Entity
@Table(name = "positions",
        uniqueConstraints = {
                @UniqueConstraint(name = "uk_position_account_ticker",
                        columnNames = {"broker_account_id", "ticker"})
        },
        indexes = {
                @Index(name = "idx_position_user", columnList = "user_id"),
                @Index(name = "idx_position_broker_account", columnList = "broker_account_id")
        })
public class Position extends BaseEntity {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @ManyToOne(fetch = FetchType.LAZY)
    @JoinColumn(name = "user_id", nullable = false)
    private User user;

    /**
     * 보유종목이 속한 BrokerAccount. 모드별/계정별 포지션 분리의 핵심 식별자.
     * unique(broker_account_id, ticker) 로 한 계정 내 동일 종목 중복 방지.
     */
    @Column(name = "broker_account_id", nullable = false)
    private Long brokerAccountId;

    @Column(nullable = false, length = 20)
    private String ticker;

    @Column(nullable = false)
    private Integer quantity;

    @Column(nullable = false)
    private Double avgPrice;

    @Column(nullable = false)
    private LocalDateTime syncedAt;

    @Builder
    public Position(User user, Long brokerAccountId, String ticker, Integer quantity, Double avgPrice) {
        this.user = user;
        this.brokerAccountId = brokerAccountId;
        this.ticker = ticker;
        this.quantity = quantity;
        this.avgPrice = avgPrice;
        this.syncedAt = LocalDateTime.now();
    }

    /** Terminal sync 시 기존 row 의 수량/평균가 갱신. */
    public void update(Integer quantity, Double avgPrice) {
        this.quantity = quantity;
        this.avgPrice = avgPrice;
        this.syncedAt = LocalDateTime.now();
    }

    /** 매수 기준 평가금액 = 평균가 × 수량. 실시간 가격이 아닌 보수적 추정치. */
    public double bookValue() {
        return avgPrice * quantity;
    }
}
