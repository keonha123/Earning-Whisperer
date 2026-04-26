package com.earningwhisperer.presentation.portfolio;

import com.earningwhisperer.domain.portfolio.PortfolioSettings;
import com.earningwhisperer.domain.portfolio.PortfolioSettingsService;
import jakarta.validation.Valid;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.http.ResponseEntity;
import org.springframework.security.core.Authentication;
import org.springframework.web.bind.annotation.*;

@Slf4j
@RestController
@RequestMapping("/api/v1/portfolio")
@RequiredArgsConstructor
public class PortfolioSettingsController {

    private final PortfolioSettingsService portfolioSettingsService;

    @GetMapping("/settings")
    public ResponseEntity<PortfolioSettings> getSettings(Authentication auth) {
        Long userId = (Long) auth.getPrincipal();
        return ResponseEntity.ok(portfolioSettingsService.getSettings(userId));
    }

    @PutMapping("/settings")
    public ResponseEntity<PortfolioSettings> updateSettings(
            Authentication auth,
            @Valid @RequestBody PortfolioSettingsUpdateRequest request) {
        Long userId = (Long) auth.getPrincipal();
        return ResponseEntity.ok(portfolioSettingsService.updateSettings(
                userId,
                request.getBuyAmountRatio(),
                request.getMaxPositionRatio(),
                request.getCooldownMinutes(),
                request.getAiScoreThreshold(),
                request.getTradingMode()
        ));
    }

    /**
     * Contract 4b — Trading Terminal 실계좌 잔고 동기화.
     * cashBalance를 저장하여 룰 엔진의 동적 수량 계산에 활용한다.
     */
    @PostMapping("/sync")
    public ResponseEntity<Void> sync(
            Authentication auth,
            @Valid @RequestBody PortfolioSyncRequest request) {
        Long userId = (Long) auth.getPrincipal();
        portfolioSettingsService.syncCashBalance(userId, request.getCashBalance());
        log.info("[PortfolioSync] 잔고 동기화 - userId={} cashBalance={} positions={}",
                userId, request.getCashBalance(),
                request.getPositions() == null ? 0 : request.getPositions().size());
        return ResponseEntity.ok().build();
    }
}
