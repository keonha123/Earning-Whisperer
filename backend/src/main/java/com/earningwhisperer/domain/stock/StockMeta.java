package com.earningwhisperer.domain.stock;

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
@Table(name = "stock_meta",
        uniqueConstraints = @UniqueConstraint(columnNames = "stock_id"))
public class StockMeta extends BaseEntity {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @OneToOne(fetch = FetchType.LAZY)
    @JoinColumn(name = "stock_id", nullable = false)
    private Stock stock;

    @Column(name = "market_cap_usd", precision = 20, scale = 2)
    private BigDecimal marketCapUsd;

    @Column(name = "high_52w", precision = 12, scale = 4)
    private BigDecimal high52w;

    @Column(name = "low_52w", precision = 12, scale = 4)
    private BigDecimal low52w;

    @Column(name = "dividend_yield", precision = 8, scale = 6)
    private BigDecimal dividendYield;

    @Column(name = "last_synced_at", nullable = false)
    private Instant lastSyncedAt;

    @Builder
    public StockMeta(Stock stock,
                     BigDecimal marketCapUsd,
                     BigDecimal high52w,
                     BigDecimal low52w,
                     BigDecimal dividendYield,
                     Instant lastSyncedAt) {
        this.stock = stock;
        this.marketCapUsd = marketCapUsd;
        this.high52w = high52w;
        this.low52w = low52w;
        this.dividendYield = dividendYield;
        this.lastSyncedAt = lastSyncedAt != null ? lastSyncedAt : Instant.now();
    }

    public void updateMeta(BigDecimal marketCapUsd,
                           BigDecimal high52w,
                           BigDecimal low52w,
                           BigDecimal dividendYield) {
        this.marketCapUsd = marketCapUsd;
        this.high52w = high52w;
        this.low52w = low52w;
        this.dividendYield = dividendYield;
        this.lastSyncedAt = Instant.now();
    }
}
