package com.earningwhisperer.infrastructure.migration;

import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.boot.ApplicationRunner;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.context.annotation.Profile;

/**
 * BrokerAccount 도입 시 1회 실행되는 backfill 마이그레이션 진입점.
 *
 * <p>실제 backfill 로직은 {@link BrokerAccountBackfillService} 가 담당하며,
 * 본 클래스는 ApplicationRunner 등록만 한다 (self-invocation 으로 인한 @Transactional 우회 회피).
 *
 * <p>실행 정책:
 * <ul>
 *   <li>"local" 또는 default(prod) 프로파일에서만 실행. CI/test 프로파일은 skip — 슬라이스 테스트에 영향 없음.</li>
 *   <li>멀티 인스턴스 동시 부팅 시 race 가능 — 운영 시 한 인스턴스에서만 실행되도록 운영팀이 통제 필요.
 *       backfill 자체는 idempotent (NOT EXISTS / NULL 가드) 하므로 race 발생해도 unique 제약 위반은 한쪽 실패 후 정상.</li>
 *   <li>기존 portfolio_settings.cash_balance 컬럼 / positions 의 기존 unique 제약은 IF-EXISTS 패턴으로 best-effort drop.</li>
 * </ul>
 *
 * <p>backfill 정책 (모든 기존 사용자가 모의 단계라는 전제):
 * <ol>
 *   <li>users 의 모든 row 에 대해 KIS-paper BrokerAccount 1개씩 자동 생성 (이미 있으면 skip)</li>
 *   <li>users.active_broker_account_id 미설정이면 그 BrokerAccount 로 set</li>
 *   <li>Trade.broker_account_id 가 NULL 인 row 는 user 의 KIS-paper BrokerAccount id 로 채움</li>
 *   <li>Position.broker_account_id 가 NULL 인 row 도 동일 처리</li>
 * </ol>
 */
@Slf4j
@Configuration
@RequiredArgsConstructor
@Profile("!test")
public class BrokerAccountMigration {

    private final BrokerAccountBackfillService backfillService;

    @Bean
    public ApplicationRunner brokerAccountBackfillRunner() {
        return args -> {
            log.info("[BrokerAccountMigration] backfill 시작");
            try {
                backfillService.backfill();
                log.info("[BrokerAccountMigration] backfill 완료");
            } catch (Exception e) {
                log.error("[BrokerAccountMigration] backfill 실패 — 운영팀 확인 필요", e);
                // 부팅 자체는 막지 않음 (멀티 인스턴스 race 가능성). 단 운영 모니터링 필요.
            }
        };
    }
}
