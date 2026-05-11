package com.earningwhisperer.domain.trade;

import jakarta.persistence.LockModeType;
import jakarta.persistence.QueryHint;
import org.springframework.data.domain.Page;
import org.springframework.data.domain.Pageable;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Lock;
import org.springframework.data.jpa.repository.Modifying;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.jpa.repository.QueryHints;
import org.springframework.data.repository.query.Param;

import java.time.LocalDateTime;
import java.util.List;
import java.util.Optional;

public interface TradeRepository extends JpaRepository<Trade, Long> {

    List<Trade> findByUserIdOrderByCreatedAtDesc(Long userId);

    List<Trade> findByUserIdAndTickerOrderByCreatedAtDesc(Long userId, String ticker);

    Page<Trade> findByUserId(Long userId, Pageable pageable);

    /**
     * Trade 콜백 처리용 비관적 쓰기 락 조회 (SELECT ... FOR UPDATE).
     *
     * <p>같은 tradeId 의 다른 brokerOrderId 를 가진 두 콜백이 거의 동시에 도착하면
     * 두 트랜잭션이 모두 PENDING 을 읽고 모두 {@code Trade.executed()} 통과 →
     * 마지막 commit 이 덮어써 lost update 가 발생할 수 있다.
     * UNIQUE(broker_order_id) 제약은 같은 brokerOrderId 만 막으므로 다른 brokerOrderId 면 무력하다.
     *
     * <p>본 메서드는 {@code @Transactional} 내부에서 호출되어 commit 까지 row 를 잠근다.
     * 늦게 진입한 트랜잭션은 먼저 commit 된 EXECUTED/FAILED 를 읽고
     * {@link Trade#executed} / {@link Trade#failed} 의 멱등 분기로 200 OK 를 반환한다.
     *
     * <p>주의: {@code @Transactional} 외부에서 호출하면 락이 즉시 해제된다.
     *
     * <p>락 획득 타임아웃 3초 — MySQL 기본 {@code innodb_lock_wait_timeout=50s} 동안
     * 콜백 worker thread 가 묶이는 것을 방지한다. 타임아웃 시
     * {@link org.springframework.dao.PessimisticLockingFailureException} 또는
     * {@link org.springframework.dao.CannotAcquireLockException} 으로 변환되어
     * {@code GlobalExceptionHandler} 가 503 으로 응답한다.
     */
    @Lock(LockModeType.PESSIMISTIC_WRITE)
    @QueryHints({
            @QueryHint(name = "jakarta.persistence.lock.timeout", value = "3000")
    })
    @Query("SELECT t FROM Trade t WHERE t.id = :id")
    Optional<Trade> findByIdForUpdate(@Param("id") Long id);

    /**
     * Terminal 재접속 시 활성 BrokerAccount 의 미만료 PENDING 명령을 복원하기 위한 조회.
     * createdAt &gt; threshold 인 PENDING 만 반환한다 (TTL 내).
     */
    List<Trade> findByBrokerAccountIdAndStatusAndCreatedAtAfter(
            Long brokerAccountId, TradeStatus status, LocalDateTime threshold);

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
