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
@Table(name = "earnings_calendar",
        uniqueConstraints = @UniqueConstraint(columnNames = {"stock_id", "scheduled_at"}))
public class EarningsCalendar extends BaseEntity {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @ManyToOne(fetch = FetchType.LAZY)
    @JoinColumn(name = "stock_id", nullable = false)
    private Stock stock;

    @Column(nullable = false)
    private Instant scheduledAt;

    private boolean confirmed;

    @Column(name = "eps_estimate", precision = 10, scale = 4)
    private BigDecimal epsEstimate;

    @Column(name = "revenue_estimate", precision = 18, scale = 2)
    private BigDecimal revenueEstimate;

    @Builder
    public EarningsCalendar(Stock stock,
                            Instant scheduledAt,
                            boolean confirmed,
                            BigDecimal epsEstimate,
                            BigDecimal revenueEstimate) {
        this.stock = stock;
        this.scheduledAt = scheduledAt;
        this.confirmed = confirmed;
        this.epsEstimate = epsEstimate;
        this.revenueEstimate = revenueEstimate;
    }

    public void update(Instant scheduledAt, boolean confirmed) {
        this.scheduledAt = scheduledAt;
        this.confirmed = confirmed;
    }

    public void updateEstimates(BigDecimal epsEstimate, BigDecimal revenueEstimate) {
        this.epsEstimate = epsEstimate;
        this.revenueEstimate = revenueEstimate;
    }
}
