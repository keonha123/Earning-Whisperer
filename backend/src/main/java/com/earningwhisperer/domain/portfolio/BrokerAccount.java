package com.earningwhisperer.domain.portfolio;

import com.earningwhisperer.domain.user.User;
import com.earningwhisperer.global.common.BaseEntity;
import jakarta.persistence.*;
import lombok.AccessLevel;
import lombok.Builder;
import lombok.Getter;
import lombok.NoArgsConstructor;

/**
 * 사용자의 증권사 계정. 한 사용자가 여러 증권사 / 같은 증권사의 모의·실전 계정을 동시에 보유할 수 있다.
 *
 * <p>현재 단계에서는 KIS 모의/실전 두 종류만 활용하지만, unique 제약을 (user, broker, isPaper) 로 두어
 * 추후 같은 broker+isPaper 조합 안에서 다중 계정으로 확장 가능하도록 명시적으로 닫아두지 않았다 (alias 로 구분).
 *
 * <p>cashBalance 는 이전에 PortfolioSettings 에 단일 컬럼으로 있던 값을 broker 별로 분리해
 * 본 엔티티로 옮긴 것. RuleEngine 의 maxPositionRatio 검증과 PositionService.computePositionRatio 모두
 * 본 엔티티의 cashBalance 를 기반으로 계산한다.
 */
@Getter
@NoArgsConstructor(access = AccessLevel.PROTECTED)
@Entity
@Table(name = "broker_accounts",
        uniqueConstraints = {
                @UniqueConstraint(name = "uk_broker_account_user_broker_paper",
                        columnNames = {"user_id", "broker", "is_paper"})
        },
        indexes = {
                @Index(name = "idx_broker_account_user", columnList = "user_id")
        })
public class BrokerAccount extends BaseEntity {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @ManyToOne(fetch = FetchType.LAZY)
    @JoinColumn(name = "user_id", nullable = false)
    private User user;

    @Enumerated(EnumType.STRING)
    @Column(nullable = false, length = 20)
    private Broker broker;

    @Column(name = "is_paper", nullable = false)
    private Boolean isPaper;

    /** 사용자 표시명. 기본값은 "{broker} {모의|실전}" 형태. */
    @Column(nullable = false, length = 50)
    private String alias;

    /**
     * 실계좌 예수금. Trading Terminal 의 KIS 잔고 sync 가 갱신.
     * null = 아직 동기화 미완료 (SignalService fail-safe HOLD 트리거).
     */
    @Column
    private Double cashBalance;

    @Builder
    public BrokerAccount(User user, Broker broker, Boolean isPaper, String alias, Double cashBalance) {
        this.user = user;
        this.broker = broker;
        this.isPaper = isPaper;
        this.alias = alias != null ? alias : defaultAlias(broker, isPaper);
        this.cashBalance = cashBalance;
    }

    public void syncCashBalance(Double cashBalance) {
        this.cashBalance = cashBalance;
    }

    public void renameAlias(String alias) {
        if (alias == null || alias.isBlank()) {
            throw new IllegalArgumentException("alias 는 비어 있을 수 없습니다.");
        }
        this.alias = alias;
    }

    private static String defaultAlias(Broker broker, Boolean isPaper) {
        return broker.name() + " " + (Boolean.TRUE.equals(isPaper) ? "모의" : "실전");
    }
}
