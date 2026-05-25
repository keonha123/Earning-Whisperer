package com.earningwhisperer.infrastructure.migration;

import jakarta.persistence.EntityManager;
import jakarta.persistence.PersistenceContext;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.util.List;

/**
 * BrokerAccount 도입 backfill 의 트랜잭션 경계 보장용 서비스.
 *
 * <p>ApplicationRunner 의 람다에서 backfill() 호출 시 self-invocation 회피를 위해 별도 빈으로 분리.
 * 본 서비스는 idempotent 하므로 여러 번 호출해도 부작용 없다.
 */
@Slf4j
@Service
public class BrokerAccountBackfillService {

    @PersistenceContext
    private EntityManager em;

    @Transactional
    public void backfill() {
        // 0. 운영 prod 잔존 컬럼/제약 정리 — 반드시 "존재할 때만" DROP 한다.
        // MySQL 에서는 SQL 예외가 발생하면 catch 하더라도 현재 트랜잭션이 rollback-only 로 마킹되어,
        // 아래 backfill 전체가 commit 시점에 UnexpectedRollbackException 으로 롤백된다.
        // 따라서 try-catch 대신 information_schema 로 사전 확인 후 존재할 때만 실행한다.
        dropColumnIfExists("portfolio_settings", "cash_balance");
        dropIndexIfExists("positions", "uk_position_user_ticker");

        // 1. 모든 사용자에 KIS-paper BrokerAccount 자동 생성 (없는 경우만)
        @SuppressWarnings("unchecked")
        List<Object> usersWithoutPaper = em.createNativeQuery("""
                SELECT u.id FROM users u
                WHERE NOT EXISTS (
                    SELECT 1 FROM broker_accounts ba
                    WHERE ba.user_id = u.id AND ba.broker = 'KIS' AND ba.is_paper = TRUE
                )
                """).getResultList();

        if (!usersWithoutPaper.isEmpty()) {
            for (Object idObj : usersWithoutPaper) {
                Long userId = ((Number) idObj).longValue();
                em.createNativeQuery("""
                        INSERT INTO broker_accounts
                            (user_id, broker, is_paper, alias, cash_balance, created_at, updated_at)
                        VALUES (:uid, 'KIS', TRUE, 'KIS 모의', NULL, NOW(), NOW())
                        """)
                        .setParameter("uid", userId)
                        .executeUpdate();
            }
            log.info("[BrokerAccountBackfill] {} 사용자에 KIS-paper BrokerAccount 자동 생성",
                    usersWithoutPaper.size());
        }

        // 2. 활성 BrokerAccount 미설정 사용자 자동 활성화
        int activated = em.createNativeQuery("""
                UPDATE users u
                JOIN broker_accounts ba ON ba.user_id = u.id AND ba.broker = 'KIS' AND ba.is_paper = TRUE
                SET u.active_broker_account_id = ba.id
                WHERE u.active_broker_account_id IS NULL
                """).executeUpdate();
        if (activated > 0) {
            log.info("[BrokerAccountBackfill] {} 사용자에 활성 BrokerAccount 자동 set", activated);
        }

        // 3. Trade.broker_account_id NULL row backfill
        int tradesUpdated = em.createNativeQuery("""
                UPDATE trades t
                JOIN broker_accounts ba ON ba.user_id = t.user_id AND ba.broker = 'KIS' AND ba.is_paper = TRUE
                SET t.broker_account_id = ba.id
                WHERE t.broker_account_id IS NULL
                """).executeUpdate();
        if (tradesUpdated > 0) {
            log.info("[BrokerAccountBackfill] {} Trade row backfill", tradesUpdated);
        }

        // 4. Position.broker_account_id NULL row backfill
        int positionsUpdated = em.createNativeQuery("""
                UPDATE positions p
                JOIN broker_accounts ba ON ba.user_id = p.user_id AND ba.broker = 'KIS' AND ba.is_paper = TRUE
                SET p.broker_account_id = ba.id
                WHERE p.broker_account_id IS NULL
                """).executeUpdate();
        if (positionsUpdated > 0) {
            log.info("[BrokerAccountBackfill] {} Position row backfill", positionsUpdated);
        }
    }

    private void dropColumnIfExists(String table, String column) {
        Number count = (Number) em.createNativeQuery("""
                SELECT COUNT(*) FROM information_schema.COLUMNS
                WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = :t AND COLUMN_NAME = :c
                """)
                .setParameter("t", table)
                .setParameter("c", column)
                .getSingleResult();
        if (count.intValue() > 0) {
            em.createNativeQuery("ALTER TABLE " + table + " DROP COLUMN " + column).executeUpdate();
            log.info("[BrokerAccountBackfill] 레거시 컬럼 제거: {}.{}", table, column);
        }
    }

    private void dropIndexIfExists(String table, String index) {
        Number count = (Number) em.createNativeQuery("""
                SELECT COUNT(*) FROM information_schema.STATISTICS
                WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = :t AND INDEX_NAME = :i
                """)
                .setParameter("t", table)
                .setParameter("i", index)
                .getSingleResult();
        if (count.intValue() > 0) {
            em.createNativeQuery("ALTER TABLE " + table + " DROP INDEX " + index).executeUpdate();
            log.info("[BrokerAccountBackfill] 레거시 인덱스 제거: {}.{}", table, index);
        }
    }
}
