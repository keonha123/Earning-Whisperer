package com.earningwhisperer.domain.portfolio;

import com.earningwhisperer.domain.user.User;
import com.earningwhisperer.global.common.BaseEntity;
import jakarta.persistence.*;
import lombok.AccessLevel;
import lombok.Builder;
import lombok.Getter;
import lombok.NoArgsConstructor;

/**
 * 사용자의 증권사(또는 페이퍼) 계정.
 *
 * <p>accountType 단일 컬럼으로 계정 종류를 표현한다. unique 제약은 (user_id, account_type) 으로,
 * 한 사용자가 KIS_REAL / KIS_PAPER / SELF_PAPER 각 1개씩 보유 가능.
 *
 * <p>cashBalance 는 Trading Terminal 의 잔고 sync 가 갱신하며, RuleEngine 의 maxPositionRatio 검증과
 * PositionService.computePositionRatio 가 이 값을 기반으로 계산한다.
 */
@Getter
@NoArgsConstructor(access = AccessLevel.PROTECTED)
@Entity
@Table(name = "broker_accounts",
        uniqueConstraints = {
                @UniqueConstraint(name = "uk_broker_account_user_type",
                        columnNames = {"user_id", "account_type"})
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
    @Column(name = "account_type", nullable = false, length = 20)
    private AccountType accountType;

    /** 사용자 표시명. 기본값은 accountType 에 따른 한국어 레이블. */
    @Column(nullable = false, length = 50)
    private String alias;

    /**
     * 실계좌 예수금. Trading Terminal 의 KIS 잔고 sync 가 갱신.
     * null = 아직 동기화 미완료 (SignalService fail-safe HOLD 트리거).
     */
    @Column
    private Double cashBalance;

    @Builder
    public BrokerAccount(User user, AccountType accountType, String alias, Double cashBalance) {
        this.user = user;
        this.accountType = accountType;
        this.alias = alias != null ? alias : defaultAlias(accountType);
        this.cashBalance = cashBalance;
    }

    public void syncCashBalance(Double cashBalance) {
        this.cashBalance = cashBalance;
    }

    public void adjustCashBalance(double delta) {
        this.cashBalance = (this.cashBalance != null ? this.cashBalance : 0.0) + delta;
    }

    public void renameAlias(String alias) {
        if (alias == null || alias.isBlank()) {
            throw new IllegalArgumentException("alias 는 비어 있을 수 없습니다.");
        }
        this.alias = alias;
    }

    private static String defaultAlias(AccountType accountType) {
        return switch (accountType) {
            case KIS_REAL  -> "KIS 실전";
            case KIS_PAPER -> "KIS 모의";
            case SELF_PAPER -> "페이퍼 트레이딩";
        };
    }
}
