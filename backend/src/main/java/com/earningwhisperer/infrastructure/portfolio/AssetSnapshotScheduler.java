package com.earningwhisperer.infrastructure.portfolio;

import com.earningwhisperer.domain.portfolio.AssetSnapshotService;
import com.earningwhisperer.domain.portfolio.BrokerAccount;
import com.earningwhisperer.domain.portfolio.BrokerAccountRepository;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;

import java.time.LocalDate;
import java.util.List;

/**
 * 매일 장 마감 후 전체 사용자의 총자산 스냅샷을 기록하는 스케줄러.
 *
 * <p>활성 BrokerAccount(user.activeBrokerAccountId) 기준으로만 스냅샷을 저장한다.
 * activeBrokerAccountId 가 null 인 사용자(아직 계좌 미등록)는 skip.
 *
 * <p>cashBalance 가 null 인 계좌(아직 Terminal sync 미완료)는 0 으로 처리한다.
 * N+1 방지를 위해 findAllWithUser() 로 User 를 함께 fetch 한다.
 */
@Component
@RequiredArgsConstructor
@Slf4j
public class AssetSnapshotScheduler {

    private final BrokerAccountRepository brokerAccountRepository;
    private final AssetSnapshotService assetSnapshotService;

    /** 매일 UTC 23:00 — 미국 주식 기준 장 마감(UTC 21:00) 후 여유를 두어 실행. */
    @Scheduled(cron = "0 0 23 * * *", zone = "UTC")
    public void takeSnapshots() {
        LocalDate today = LocalDate.now();
        List<BrokerAccount> accounts = brokerAccountRepository.findAllWithUser();

        int success = 0;
        int skipped = 0;
        int failed = 0;

        for (BrokerAccount account : accounts) {
            Long userId = account.getUser().getId();
            Long activeBrokerAccountId = account.getUser().getActiveBrokerAccountId();

            // 활성 BrokerAccount 가 아닌 계좌는 skip
            if (activeBrokerAccountId == null || !activeBrokerAccountId.equals(account.getId())) {
                skipped++;
                continue;
            }

            try {
                assetSnapshotService.upsert(userId, account.getId(), account.getCashBalance(), today);
                success++;
            } catch (Exception e) {
                failed++;
                log.warn("[AssetSnapshot] 스냅샷 저장 실패 - userId={} brokerAccountId={}",
                        userId, account.getId(), e);
            }
        }

        log.info("[AssetSnapshot] 일별 자산 스냅샷 완료 — date={} success={} skipped={} failed={}",
                today, success, skipped, failed);
    }
}
