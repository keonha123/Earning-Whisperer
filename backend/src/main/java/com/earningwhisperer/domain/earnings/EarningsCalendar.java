package com.earningwhisperer.domain.earnings;

import com.earningwhisperer.domain.stock.Stock;
import com.earningwhisperer.global.common.BaseEntity;
import jakarta.persistence.*;
import lombok.AccessLevel;
import lombok.Builder;
import lombok.Getter;
import lombok.NoArgsConstructor;

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

    @Builder
    public EarningsCalendar(Stock stock, Instant scheduledAt, boolean confirmed) {
        this.stock = stock;
        this.scheduledAt = scheduledAt;
        this.confirmed = confirmed;
    }

    public void update(Instant scheduledAt, boolean confirmed) {
        this.scheduledAt = scheduledAt;
        this.confirmed = confirmed;
    }
}
