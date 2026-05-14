package com.earningwhisperer.domain.portfolio;

import jakarta.persistence.*;
import lombok.AccessLevel;
import lombok.Builder;
import lombok.Getter;
import lombok.NoArgsConstructor;

import java.time.LocalDate;

/**
 * 사용자의 일별 총자산 스냅샷.
 *
 * <p>매일 장 마감 후 스케줄러가 활성 BrokerAccount 의 cashBalance + 보유 포지션 평가금액(avgPrice * qty)을
 * 합산해 저장한다. 포지션 평가금액은 실시간 시세 없이 매입 평균가 기반으로 계산하므로
 * 참고용 근사치임을 주의.
 *
 * <p>(userId, snapshotDate) unique constraint 로 멱등 upsert 보장.
 */
@Getter
@NoArgsConstructor(access = AccessLevel.PROTECTED)
@Entity
@Table(
        name = "asset_daily_snapshots",
        uniqueConstraints = {
                @UniqueConstraint(
                        name = "uk_asset_snapshot_user_date",
                        columnNames = {"user_id", "snapshot_date"})
        },
        indexes = {
                @Index(name = "idx_asset_snapshot_user_date", columnList = "user_id, snapshot_date")
        })
public class AssetDailySnapshot {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @Column(name = "user_id", nullable = false)
    private Long userId;

    @Column(name = "snapshot_date", nullable = false)
    private LocalDate snapshotDate;

    /** 예수금 + 보유 포지션 매입가 기반 평가금액 합산. */
    @Column(nullable = false)
    private Double totalAsset;

    @Builder
    public AssetDailySnapshot(Long userId, LocalDate snapshotDate, Double totalAsset) {
        this.userId = userId;
        this.snapshotDate = snapshotDate;
        this.totalAsset = totalAsset;
    }

    public void update(Double totalAsset) {
        this.totalAsset = totalAsset;
    }
}
