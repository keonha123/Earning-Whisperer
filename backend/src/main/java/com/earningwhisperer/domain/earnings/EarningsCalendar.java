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

    /**
     * 일정/컨센서스를 한번에 갱신 — Finnhub 응답 한 row 의 모든 mutable 필드를 한번에 반영하기 위한 헬퍼.
     * estimate 가 null 인 케이스(Finnhub 미제공)는 그대로 null 로 덮어쓴다.
     */
    public void updateAll(Instant scheduledAt,
                          boolean confirmed,
                          BigDecimal epsEstimate,
                          BigDecimal revenueEstimate) {
        this.scheduledAt = scheduledAt;
        this.confirmed = confirmed;
        this.epsEstimate = epsEstimate;
        this.revenueEstimate = revenueEstimate;
    }
}
