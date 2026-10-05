package com.earningwhisperer.domain.trade;

import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;

/**
 * TTL 초과한 PENDING Trade 를 EXPIRED 로 전환하는 스케줄러.
 *
 * <p>체결되지 않은 수동 주문이 영원히 PENDING 으로 남는 것을 막는다. TTL 은
 * application.yml 의 app.trade.manual-pending-ttl-seconds (기본 24시간).
 * 멀티 인스턴스에서 중복 실행되어도 @Modifying UPDATE 의 WHERE status='PENDING' 조건으로
 * race / lost update 가 차단된다.
 *
 * <p>주기 5분. TTL 이 24시간이라 만료 반영이 몇 분 늦어도 차이가 없다.
 */
@Slf4j
@Component
@RequiredArgsConstructor
public class TradePendingExpiryScheduler {

    private final TradeService tradeService;

    @Scheduled(fixedDelay = 300_000L, initialDelay = 5_000L)
    public void runExpirySweep() {
        try {
            tradeService.expireStalePending();
        } catch (RuntimeException e) {
            log.error("[TradePendingExpiry] 만료 전환 사이클 실패", e);
        }
    }
}
