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

        // M1 마이그레이션: broker + is_paper → account_type
        migrateToAccountType();

        // 1. 모든 사용자에 KIS_PAPER BrokerAccount 자동 생성 (없는 경우만)
        @SuppressWarnings("unchecked")
        List<Object> usersWithoutPaper = em.createNativeQuery("""
                SELECT u.id FROM users u
                WHERE NOT EXISTS (
                    SELECT 1 FROM broker_accounts ba
                    WHERE ba.user_id = u.id AND ba.account_type = 'KIS_PAPER'
                )
                """).getResultList();

        if (!usersWithoutPaper.isEmpty()) {
            for (Object idObj : usersWithoutPaper) {
                Long userId = ((Number) idObj).longValue();
                em.createNativeQuery("""
                        INSERT INTO broker_accounts
                            (user_id, account_type, alias, cash_balance, created_at, updated_at)
                        VALUES (:uid, 'KIS_PAPER', 'KIS 모의', NULL, NOW(), NOW())
                        """)
                        .setParameter("uid", userId)
                        .executeUpdate();
            }
            log.info("[BrokerAccountBackfill] {} 사용자에 KIS_PAPER BrokerAccount 자동 생성",
                    usersWithoutPaper.size());
        }

        // 2. 활성 BrokerAccount 미설정 사용자 자동 활성화
        int activated = em.createNativeQuery("""
                UPDATE users u
                JOIN broker_accounts ba ON ba.user_id = u.id AND ba.account_type = 'KIS_PAPER'
                SET u.active_broker_account_id = ba.id
                WHERE u.active_broker_account_id IS NULL
                """).executeUpdate();
        if (activated > 0) {
            log.info("[BrokerAccountBackfill] {} 사용자에 활성 BrokerAccount 자동 set", activated);
        }

        // 3. Trade.broker_account_id NULL row backfill
        int tradesUpdated = em.createNativeQuery("""
                UPDATE trades t
                JOIN broker_accounts ba ON ba.user_id = t.user_id AND ba.account_type = 'KIS_PAPER'
                SET t.broker_account_id = ba.id
                WHERE t.broker_account_id IS NULL
                """).executeUpdate();
        if (tradesUpdated > 0) {
            log.info("[BrokerAccountBackfill] {} Trade row backfill", tradesUpdated);
        }

        // 4. Position.broker_account_id NULL row backfill
        int positionsUpdated = em.createNativeQuery("""
                UPDATE positions p
                JOIN broker_accounts ba ON ba.user_id = p.user_id AND ba.account_type = 'KIS_PAPER'
                SET p.broker_account_id = ba.id
                WHERE p.broker_account_id IS NULL
                """).executeUpdate();
        if (positionsUpdated > 0) {
            log.info("[BrokerAccountBackfill] {} Position row backfill", positionsUpdated);
        }
    }

    /**
     * broker + is_paper 컬럼을 account_type 단일 컬럼으로 이전.
     * account_type 컬럼이 이미 존재하면 전체 skip (idempotent).
     */
    private void migrateToAccountType() {
        Number accountTypeExists = (Number) em.createNativeQuery("""
                SELECT COUNT(*) FROM information_schema.COLUMNS
                WHERE TABLE_SCHEMA = DATABASE()
                  AND TABLE_NAME = 'broker_accounts'
                  AND COLUMN_NAME = 'account_type'
                """).getSingleResult();
        if (accountTypeExists.intValue() > 0) {
            return; // 이미 마이그레이션 완료
        }

        // 1. account_type 컬럼 추가 (nullable — backfill 전)
        em.createNativeQuery(
                "ALTER TABLE broker_accounts ADD COLUMN account_type VARCHAR(20) NULL"
        ).executeUpdate();

        // 2. backfill: broker='KIS' + is_paper 기준으로 account_type 채우기
        em.createNativeQuery("""
                UPDATE broker_accounts
                SET account_type = CASE
                    WHEN is_paper = TRUE THEN 'KIS_PAPER'
                    ELSE 'KIS_REAL'
                END
                WHERE broker = 'KIS'
                """).executeUpdate();

        // 3. NOT NULL 제약 추가
        em.createNativeQuery(
                "ALTER TABLE broker_accounts MODIFY COLUMN account_type VARCHAR(20) NOT NULL"
        ).executeUpdate();

        // 4. 기존 unique 제약(user_id, broker, is_paper) 제거 후 신규 제약(user_id, account_type) 추가
        dropIndexIfExists("broker_accounts", "uk_broker_account_user_broker_paper");
        em.createNativeQuery(
                "ALTER TABLE broker_accounts ADD CONSTRAINT uk_broker_account_user_type UNIQUE (user_id, account_type)"
        ).executeUpdate();

        // 5. 구 컬럼 제거
        dropColumnIfExists("broker_accounts", "broker");
        dropColumnIfExists("broker_accounts", "is_paper");

        log.info("[BrokerAccountBackfill] account_type 마이그레이션 완료 (broker + is_paper → account_type)");
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
