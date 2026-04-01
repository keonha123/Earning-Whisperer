package com.earningwhisperer.presentation.portfolio;

import com.earningwhisperer.domain.portfolio.PortfolioSettings;
import com.earningwhisperer.domain.portfolio.PortfolioSettingsService;
import jakarta.validation.Valid;
import lombok.RequiredArgsConstructor;
import org.springframework.http.ResponseEntity;
import org.springframework.security.core.Authentication;
import org.springframework.web.bind.annotation.*;

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
                request.getEmaThreshold(),
                request.getTradingMode()
        ));
    }
}
