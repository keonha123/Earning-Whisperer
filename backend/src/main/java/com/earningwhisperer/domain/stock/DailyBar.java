package com.earningwhisperer.domain.stock;

import com.earningwhisperer.global.common.BaseEntity;
import jakarta.persistence.*;
import lombok.AccessLevel;
import lombok.Builder;
import lombok.Getter;
import lombok.NoArgsConstructor;

import java.math.BigDecimal;
import java.time.LocalDate;

@Getter
@NoArgsConstructor(access = AccessLevel.PROTECTED)
@Entity
@Table(name = "daily_bar",
        uniqueConstraints = @UniqueConstraint(columnNames = {"stock_id", "bar_date"}))
public class DailyBar extends BaseEntity {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @ManyToOne(fetch = FetchType.LAZY)
    @JoinColumn(name = "stock_id", nullable = false)
    private Stock stock;

    @Column(name = "bar_date", nullable = false)
    private LocalDate barDate;

    @Column(name = "close_price", nullable = false, precision = 12, scale = 4)
    private BigDecimal closePrice;

    @Column(name = "volume")
    private Long volume;

    @Builder
    public DailyBar(Stock stock, LocalDate barDate, BigDecimal closePrice, Long volume) {
        this.stock = stock;
        this.barDate = barDate;
        this.closePrice = closePrice;
        this.volume = volume;
    }

    public void updateClose(BigDecimal closePrice, Long volume) {
        this.closePrice = closePrice;
        this.volume = volume;
    }
}
