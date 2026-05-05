package com.earningwhisperer.presentation.portfolio;

import com.earningwhisperer.domain.portfolio.PortfolioSettings;
import com.earningwhisperer.domain.portfolio.PortfolioSettingsService;
import com.earningwhisperer.domain.portfolio.PositionService;
import com.earningwhisperer.domain.portfolio.TradingMode;
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
    private final PositionService positionService;

    @GetMapping("/settings")
    public ResponseEntity<PortfolioSettingsResponse> getSettings(Authentication auth) {
        Long userId = (Long) auth.getPrincipal();
        return ResponseEntity.ok(PortfolioSettingsResponse.from(portfolioSettingsService.getSettings(userId)));
    }

    @PutMapping("/settings")
    public ResponseEntity<PortfolioSettingsResponse> updateSettings(
            Authentication auth,
            @Valid @RequestBody PortfolioSettingsUpdateRequest request) {
        Long userId = (Long) auth.getPrincipal();
        PortfolioSettings updated = portfolioSettingsService.updateSettings(
                userId,
                request.getBuyAmountRatio(),
                request.getMaxPositionRatio(),
                request.getCooldownMinutes(),
                request.getAiScoreThreshold(),
                request.getTradingMode()
        );
        return ResponseEntity.ok(PortfolioSettingsResponse.from(updated));
    }

    /**
     * 응답 DTO — entity 의 user 가 LAZY proxy 라 Jackson 직렬화 실패하던 문제 회피.
     * 또한 client 가 user 정보를 응답에서 받을 필요가 없다 (Authentication 으로 이미 식별됨).
     */
    public record PortfolioSettingsResponse(
            Double buyAmountRatio,
            Double maxPositionRatio,
            Integer cooldownMinutes,
            Double aiScoreThreshold,
            TradingMode tradingMode,
            Double cashBalance
    ) {
        static PortfolioSettingsResponse from(PortfolioSettings s) {
            return new PortfolioSettingsResponse(
                    s.getBuyAmountRatio(),
                    s.getMaxPositionRatio(),
                    s.getCooldownMinutes(),
                    s.getAiScoreThreshold(),
                    s.getTradingMode(),
                    s.getCashBalance()
            );
        }
    }

    /**
     * Contract 4b — Trading Terminal 실계좌 잔고 동기화.
     * cashBalance 와 보유종목(positions) 모두 영속화. positions 는 RuleEngine 의
     * maxPositionRatio 검증에 사용된다 (snapshot — 누락 ticker 는 삭제).
     */
    @PostMapping("/sync")
    public ResponseEntity<Void> sync(
            Authentication auth,
            @Valid @RequestBody PortfolioSyncRequest request) {
        Long userId = (Long) auth.getPrincipal();
        portfolioSettingsService.syncCashBalance(userId, request.getCashBalance());
        int upserted = positionService.syncSnapshot(userId, request.getPositions());
        log.info("[PortfolioSync] 동기화 - userId={} cashBalance={} positions(received)={} positions(upserted)={}",
                userId, request.getCashBalance(),
                request.getPositions() == null ? 0 : request.getPositions().size(),
                upserted);
        return ResponseEntity.ok().build();
    }
}
