package com.earningwhisperer.presentation.internal;

import com.earningwhisperer.infrastructure.fmp.DailyBarSyncScheduler;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.context.annotation.Profile;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.Map;

/**
 * 로컬 개발 전용 어드민 트리거. 프로덕션 배포 시 Bean 미등록(@Profile("local")).
 */
@Profile("local")
@RestController
@RequestMapping("/api/v1/dev")
@RequiredArgsConstructor
@Slf4j
public class DevAdminController {

    private final DailyBarSyncScheduler dailyBarSyncScheduler;

    /** DailyBarSyncScheduler 수동 트리거 — POST /api/v1/dev/sync-daily-bars */
    @PostMapping("/sync-daily-bars")
    public ResponseEntity<Map<String, String>> syncDailyBars() {
        log.info("[DevAdmin] DailyBar 수동 트리거");
        dailyBarSyncScheduler.syncDailyBars();
        return ResponseEntity.ok(Map.of("result", "triggered"));
    }
}
