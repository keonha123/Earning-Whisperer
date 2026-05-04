package com.earningwhisperer.infrastructure.sync;

import com.earningwhisperer.domain.earnings.EarningsCalendarRepository;
import com.earningwhisperer.domain.earnings.EarningsResult;
import com.earningwhisperer.domain.earnings.EarningsResultRepository;
import com.earningwhisperer.domain.stock.DailyBar;
import com.earningwhisperer.domain.stock.DailyBarRepository;
import com.earningwhisperer.domain.stock.Stock;
import com.earningwhisperer.domain.stock.StockMetaRepository;
import com.earningwhisperer.domain.stock.StockRepository;
import com.earningwhisperer.infrastructure.finnhub.EarningsResultSyncService;
import com.earningwhisperer.infrastructure.finnhub.FinnhubClient;
import com.earningwhisperer.infrastructure.finnhub.FinnhubEarningsSyncService;
import com.earningwhisperer.infrastructure.fmp.DailyBarSyncService;
import com.earningwhisperer.infrastructure.fmp.FmpClient;
import com.earningwhisperer.infrastructure.fmp.StockMetaSyncService;
import org.springframework.boot.SpringBootConfiguration;
import org.springframework.boot.actuate.autoconfigure.security.servlet.ManagementWebSecurityAutoConfiguration;
import org.springframework.boot.autoconfigure.EnableAutoConfiguration;
import org.springframework.boot.autoconfigure.data.redis.RedisAutoConfiguration;
import org.springframework.boot.autoconfigure.data.redis.RedisRepositoriesAutoConfiguration;
import org.springframework.boot.autoconfigure.domain.EntityScan;
import org.springframework.boot.autoconfigure.security.servlet.SecurityAutoConfiguration;
import org.springframework.boot.autoconfigure.security.servlet.UserDetailsServiceAutoConfiguration;
import org.springframework.context.annotation.Bean;
import org.springframework.data.jpa.repository.config.EnableJpaAuditing;
import org.springframework.data.jpa.repository.config.EnableJpaRepositories;

/**
 * Sync Service 들의 ticker 단위 트랜잭션 격리 통합 테스트용 minimal Spring Boot 설정.
 *
 * <p>전체 {@code EarningWhispererApplication} 부팅을 회피하는 사유:
 * <ul>
 *     <li>Redis / WebSocket / Security 등 인프라 의존성 부담</li>
 *     <li>{@code @ConditionalOnExpression("!'${fmp.api-key:}'.isBlank()")} 충족 시
 *         {@code FmpRateLimiter}, {@code FmpClient} 등이 함께 부팅되며 Redis 의존 체인 형성</li>
 * </ul>
 *
 * <p>대신 이 config 는 Spring Boot 자동 설정으로 JPA/트랜잭션 매니저만 부팅하고,
 * 검증 대상 Service 3개를 직접 {@code @Bean} 등록한다. {@code @Service} 빈 분리 패턴이
 * Spring AOP 트랜잭션 프록시를 통해 정상 동작하는지 — 이게 본 테스트의 검증 핵심.
 *
 * <p>{@link FmpClient} / {@link FinnhubClient} 는 production 코드에서 ConditionalOnExpression
 * 으로 미등록 상태이므로 각 테스트 클래스가 {@code @MockBean} 으로 주입한다.
 *
 * <p>{@link ComponentScan} 의 excludeFilters 는 production 의 Sync Service 들이 자체
 * ConditionalOnExpression 으로 미등록되도록 두고, 본 config 의 명시적 {@code @Bean} 을
 * 사용하기 위함이다 (양쪽 등록 시 빈 충돌 회피).
 */
@SpringBootConfiguration
@EnableAutoConfiguration(exclude = {
        // Redis 자동 부팅 제외 — 본 테스트는 DB 만 사용
        RedisAutoConfiguration.class,
        RedisRepositoriesAutoConfiguration.class,
        // Security 필터 체인은 Service 트랜잭션 검증과 무관 — 부팅 비용 회피.
        // Actuator 의 ManagementWebSecurityAutoConfiguration 도 SecurityAutoConfiguration 미존재 시
        // HttpSecurity 빈을 요구하며 부팅 실패하므로 함께 제외.
        SecurityAutoConfiguration.class,
        UserDetailsServiceAutoConfiguration.class,
        ManagementWebSecurityAutoConfiguration.class
})
@EnableJpaAuditing
@EnableJpaRepositories(basePackageClasses = {
        StockRepository.class,
        StockMetaRepository.class,
        DailyBarRepository.class,
        EarningsResultRepository.class,
        EarningsCalendarRepository.class
})
// 엔티티 메타모델 등록 — 도메인 패키지만 한정. 운영 ComponentScan 의 ConditionalOnExpression
// 빈들 (Service / Scheduler / Client / RateLimiter) 은 끌려오지 않는다.
@EntityScan(basePackageClasses = {Stock.class, DailyBar.class, EarningsResult.class})
public class SyncServiceTxIsolationTestConfig {

    /**
     * production 의 {@code @Service} + {@code @Transactional} 메타데이터를 그대로 사용하기 위해
     * 빈 등록만 직접 수행한다. Spring 의 {@code @Transactional} AOP advisor 는 어떤 등록 경로든
     * 빈 후처리 시점에 transactional 클래스를 감지해 프록시를 생성하므로,
     * 명시 {@code @Bean} 등록도 production 의 component scan 등록과 동일하게 격리 동작을 보장한다.
     */
    @Bean
    public StockMetaSyncService stockMetaSyncService(FmpClient fmpClient,
                                                    StockRepository stockRepository,
                                                    StockMetaRepository stockMetaRepository) {
        return new StockMetaSyncService(fmpClient, stockRepository, stockMetaRepository);
    }

    @Bean
    public DailyBarSyncService dailyBarSyncService(FmpClient fmpClient,
                                                   StockRepository stockRepository,
                                                   DailyBarRepository dailyBarRepository) {
        return new DailyBarSyncService(fmpClient, stockRepository, dailyBarRepository);
    }

    @Bean
    public EarningsResultSyncService earningsResultSyncService(FinnhubClient finnhubClient,
                                                               StockRepository stockRepository,
                                                               EarningsResultRepository earningsResultRepository) {
        return new EarningsResultSyncService(finnhubClient, stockRepository, earningsResultRepository);
    }

    @Bean
    public FinnhubEarningsSyncService finnhubEarningsSyncService(StockRepository stockRepository,
                                                                 EarningsCalendarRepository earningsCalendarRepository) {
        return new FinnhubEarningsSyncService(stockRepository, earningsCalendarRepository);
    }
}
