package com.earningwhisperer.domain.earnings;

import com.earningwhisperer.domain.stock.Stock;
import com.earningwhisperer.global.common.BaseEntity;
import jakarta.persistence.*;
import lombok.AccessLevel;
import lombok.Builder;
import lombok.Getter;
import lombok.NoArgsConstructor;

import java.math.BigDecimal;
import java.time.Instant;

@Getter
@NoArgsConstructor(access = AccessLevel.PROTECTED)
@Entity
@Table(name = "earnings_result",
        uniqueConstraints = @UniqueConstraint(columnNames = {"stock_id", "announced_at"}))
public class EarningsResult extends BaseEntity {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @ManyToOne(fetch = FetchType.LAZY)
    @JoinColumn(name = "stock_id", nullable = false)
    private Stock stock;

    @Column(name = "announced_at", nullable = false)
    private Instant announcedAt;

    @Column(name = "fiscal_period_label", nullable = false, length = 16)
    private String fiscalPeriodLabel;

    @Column(name = "eps_estimate", precision = 10, scale = 4)
    private BigDecimal epsEstimate;

    @Column(name = "eps_actual", precision = 10, scale = 4)
    private BigDecimal epsActual;

    @Column(name = "surprise_percent", precision = 8, scale = 4)
    private BigDecimal surprisePercent;

    @Column(name = "price_reaction_percent", precision = 8, scale = 4)
    private BigDecimal priceReactionPercent;

    @Builder
    public EarningsResult(Stock stock,
                          Instant announcedAt,
                          String fiscalPeriodLabel,
                          BigDecimal epsEstimate,
                          BigDecimal epsActual,
                          BigDecimal surprisePercent,
                          BigDecimal priceReactionPercent) {
        this.stock = stock;
        this.announcedAt = announcedAt;
        this.fiscalPeriodLabel = fiscalPeriodLabel;
        this.epsEstimate = epsEstimate;
        this.epsActual = epsActual;
        this.surprisePercent = surprisePercent;
        this.priceReactionPercent = priceReactionPercent;
    }

    public void updatePriceReaction(BigDecimal pct) {
        this.priceReactionPercent = pct;
    }

    public void updateActuals(BigDecimal epsEstimate, BigDecimal epsActual, BigDecimal surprisePercent) {
        this.epsEstimate = epsEstimate;
        this.epsActual = epsActual;
        this.surprisePercent = surprisePercent;
    }
}
