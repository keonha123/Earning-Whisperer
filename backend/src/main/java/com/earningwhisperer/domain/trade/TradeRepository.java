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

    Page<Trade> findByUserIdAndCreatedAtGreaterThanEqual(Long userId, LocalDateTime startDate, Pageable pageable);

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
     * <p><b>자동 명령과 수동 주문에 서로 다른 TTL 을 적용한다.</b> 두 PENDING 은 성격이
     * 다르다. 자동 명령의 TTL 목적은 STOMP 로 내려보낸 명령이 미접속 사용자에게 silent
     * drop 되어 영원히 PENDING 으로 남는 것을 막는 것이므로 초 단위로 짧다. 수동 주문은
     * 터미널이 이미 증권사에 주문을 넣고 결과를 기록한 것이라 체결을 기다리는 중일 뿐이며,
     * 자동 TTL(30초) 로 만료시키면 살아 있는 지정가 주문이 화면에 "실패" 로 뜬다.
     *
     * <p>그래도 수동 주문을 만료 대상에서 <b>제외</b>하지는 않는다. 제외하면 영구 PENDING
     * 고아 row 가 된다 — {@code POST /trades/manual} 은 tradeId 를 돌려주지 않았고 수동
     * 주문에는 콜백 경로가 없어서, 한 번 PENDING 으로 기록되면 아무도 종결시킬 수 없었다.
     * 대신 긴 TTL(기본 24시간) 을 준다. KIS 당일 지정가 주문은 장 마감 시 자동 취소되므로
     * 하루가 지난 PENDING 은 실제로 죽은 주문이다. 사후에 KIS 체결이 확인되면
     * {@code Trade.executed} 의 EXPIRED → EXECUTED 정정 전이로 장부를 회복할 수 있다.
     *
     * <p>orderRatio 로 자동/수동을 구분한다 — {@code createPendingTrade} 는 항상 채우고
     * {@code createManualTrade} 는 null 로 둔다. orderRatio 가 null 인 레거시 자동 row 도
     * 수동 TTL 로 결국 정리된다.
     *
     * @return 만료 처리된 row 개수
     */
    @Modifying(clearAutomatically = true, flushAutomatically = true)
    @Query("UPDATE Trade t SET t.status = com.earningwhisperer.domain.trade.TradeStatus.EXPIRED " +
            "WHERE t.status = com.earningwhisperer.domain.trade.TradeStatus.PENDING " +
            "  AND ((t.orderRatio IS NOT NULL AND t.createdAt <= :autoThreshold) " +
            "    OR (t.orderRatio IS NULL AND t.createdAt <= :manualThreshold))")
    int expirePendingBefore(@Param("autoThreshold") LocalDateTime autoThreshold,
                            @Param("manualThreshold") LocalDateTime manualThreshold);
}
