package com.earningwhisperer.domain.portfolio;

import com.earningwhisperer.domain.user.User;
import com.earningwhisperer.global.common.BaseEntity;
import jakarta.persistence.*;
import lombok.AccessLevel;
import lombok.Builder;
import lombok.Getter;
import lombok.NoArgsConstructor;

@Getter
@NoArgsConstructor(access = AccessLevel.PROTECTED)
@Entity
@Table(name = "portfolio_settings")
public class PortfolioSettings extends BaseEntity {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @OneToOne(fetch = FetchType.LAZY)
    @JoinColumn(name = "user_id", nullable = false, unique = true)
    private User user;

    /**
     * 1회 매수 시 예수금 사용 비율 (0.0 ~ 1.0, 예: 0.1 = 10%)
     */
    @Column(nullable = false)
    private Double buyAmountRatio;

    /**
     * 특정 종목 최대 보유 비중 (0.0 ~ 1.0, 예: 0.3 = 30%)
     */
    @Column(nullable = false)
    private Double maxPositionRatio;

    /**
     * 매수 쿨다운 타임 (분 단위, 예: 5 = 5분 이내 중복 시그널 무시)
     */
    @Column(nullable = false)
    private Integer cooldownMinutes;

    /**
     * EMA 스코어 임계치 — 이 값을 초과해야 BUY/SELL 실행 (예: 0.6)
     */
    @Column(nullable = false)
    private Double emaThreshold;

    @Enumerated(EnumType.STRING)
    @Column(nullable = false, length = 20)
    private TradingMode tradingMode;

    /**
     * Trading Terminal 동기화 데이터 — 실계좌 예수금 잔고.
     * 룰 엔진의 매수 수량 계산(buyAmountRatio * cashBalance)에 활용된다.
     * null = 아직 동기화 미완료
     */
    @Column
    private Double cashBalance;

    @Builder
    public PortfolioSettings(User user, Double buyAmountRatio, Double maxPositionRatio,
                              Integer cooldownMinutes, Double emaThreshold, TradingMode tradingMode) {
        this.user = user;
        this.buyAmountRatio = buyAmountRatio;
        this.maxPositionRatio = maxPositionRatio;
        this.cooldownMinutes = cooldownMinutes;
        this.emaThreshold = emaThreshold;
        this.tradingMode = tradingMode;
    }

    public void update(Double buyAmountRatio, Double maxPositionRatio,
                       Integer cooldownMinutes, Double emaThreshold, TradingMode tradingMode) {
        this.buyAmountRatio = buyAmountRatio;
        this.maxPositionRatio = maxPositionRatio;
        this.cooldownMinutes = cooldownMinutes;
        this.emaThreshold = emaThreshold;
        this.tradingMode = tradingMode;
    }

    public void syncCashBalance(Double cashBalance) {
        this.cashBalance = cashBalance;
    }
}
