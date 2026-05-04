package com.earningwhisperer.domain.trade;

import org.springframework.data.domain.Page;
import org.springframework.data.domain.Pageable;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Modifying;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;

import java.time.LocalDateTime;
import java.util.List;

public interface TradeRepository extends JpaRepository<Trade, Long> {

    List<Trade> findByUserIdOrderByCreatedAtDesc(Long userId);

    List<Trade> findByUserIdAndTickerOrderByCreatedAtDesc(Long userId, String ticker);

    Page<Trade> findByUserId(Long userId, Pageable pageable);

    /**
     * Terminal 재접속 시 미만료 PENDING 명령을 복원하기 위한 조회.
     * createdAt &gt; threshold 인 PENDING 만 반환한다 (TTL 내).
     */
    List<Trade> findByUserIdAndStatusAndCreatedAtAfter(
            Long userId, TradeStatus status, LocalDateTime threshold);

    /**
     * TTL 초과 PENDING 일괄 EXPIRED 전환 — 단일 UPDATE 로 race 차단.
     *
     * <p>WHERE status = 'PENDING' 절이 콜백 race 를 막는다: 같은 트랜잭션 사이에
     * 다른 인스턴스의 콜백이 EXECUTED 로 commit 했다면 status 가 더이상 PENDING 이 아니라
     * 이 UPDATE 는 0 row 영향. 멀티 인스턴스 scheduler 동시 실행 시에도
     * lost update / EXECUTED 덮어쓰기를 차단한다.
     *
     * @return 만료 처리된 row 개수
     */
    @Modifying(clearAutomatically = true, flushAutomatically = true)
    @Query("UPDATE Trade t SET t.status = com.earningwhisperer.domain.trade.TradeStatus.EXPIRED " +
            "WHERE t.status = com.earningwhisperer.domain.trade.TradeStatus.PENDING " +
            "  AND t.createdAt <= :threshold")
    int expirePendingBefore(@Param("threshold") LocalDateTime threshold);
}
