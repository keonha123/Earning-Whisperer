package com.earningwhisperer.domain.trade;

import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;

/**
 * TTL 초과한 PENDING Trade 를 EXPIRED 로 전환하는 스케줄러.
 *
 * <p>STOMP convertAndSendToUser 는 미접속 사용자에게 silent drop 되므로 Trade 가
 * 영원히 PENDING 으로 남는 것을 방지한다. Terminal 재접속 시에는 GET /api/v1/trades/pending
 * 으로 미만료 PENDING 만 fetch 하여 복구 가능하다.
 *
 * <p>주기 30 초, TTL 30 초 (application.yml 의 app.trade.pending-ttl-seconds) 이면
 * 최대 60 초 (평균 45 초) 안에 만료가 반영된다. 멀티 인스턴스에서 중복 실행되어도
 * @Modifying UPDATE 의 WHERE status='PENDING' 조건으로 race / lost update 가 차단된다.
 *
 * <p>initialDelay 5 초: 배포 직후 레거시 PENDING (orderRatio/aiScore 없는 행 등) 이
 * 첫 사이클까지 stuck 되는 윈도우를 짧게 한다.
 */
@Slf4j
@Component
@RequiredArgsConstructor
public class TradePendingExpiryScheduler {

    private final TradeService tradeService;

    @Scheduled(fixedDelay = 30_000L, initialDelay = 5_000L)
    public void runExpirySweep() {
        try {
            tradeService.expireStalePending();
        } catch (RuntimeException e) {
            log.error("[TradePendingExpiry] 만료 전환 사이클 실패", e);
        }
    }
}
