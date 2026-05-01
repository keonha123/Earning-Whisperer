package com.earningwhisperer.domain.earnings;

import org.springframework.data.jpa.repository.JpaRepository;

import java.time.Instant;
import java.util.List;
import java.util.Optional;

public interface EarningsResultRepository extends JpaRepository<EarningsResult, Long> {

    List<EarningsResult> findTop4ByStock_IdOrderByAnnouncedAtDesc(Long stockId);

    /**
     * Phase 2-C: 가격반응 백필 대상 후보 조회.
     *
     * <p>{@code priceReactionPercent IS NULL} 인 row 중 최근 발표분만 추린다.
     * 30일 이상 지난 row 는 가격반응 계산 가치가 적고(시장 노이즈/이벤트 누적),
     * {@code announced_at} 인덱스 활용도 높이기 위해 윈도 좁힘.
     */
    List<EarningsResult> findByPriceReactionPercentIsNullAndAnnouncedAtAfter(Instant threshold);

    /** Upsert 용 — (stock_id, announced_at) unique constraint 매칭. */
    Optional<EarningsResult> findByStock_IdAndAnnouncedAt(Long stockId, Instant announcedAt);
}
