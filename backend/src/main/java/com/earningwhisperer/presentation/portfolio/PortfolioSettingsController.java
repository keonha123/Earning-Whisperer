package com.earningwhisperer.presentation.portfolio;

import com.earningwhisperer.domain.portfolio.Broker;
import com.earningwhisperer.domain.portfolio.BrokerAccount;
import com.earningwhisperer.domain.portfolio.BrokerAccountService;
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

import java.util.List;

@Slf4j
@RestController
@RequestMapping("/api/v1/portfolio")
@RequiredArgsConstructor
public class PortfolioSettingsController {

    private final PortfolioSettingsService portfolioSettingsService;
    private final PositionService positionService;
    private final BrokerAccountService brokerAccountService;

    @GetMapping("/settings")
    public ResponseEntity<PortfolioSettingsResponse> getSettings(Authentication auth) {
        Long userId = (Long) auth.getPrincipal();
        Double activeCash = brokerAccountService.getActive(userId)
                .map(BrokerAccount::getCashBalance)
                .orElse(null);
        return ResponseEntity.ok(PortfolioSettingsResponse.from(
                portfolioSettingsService.getSettings(userId), activeCash));
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
        Double activeCash = brokerAccountService.getActive(userId)
                .map(BrokerAccount::getCashBalance)
                .orElse(null);
        return ResponseEntity.ok(PortfolioSettingsResponse.from(updated, activeCash));
    }

    /**
     * 응답 DTO — entity 의 user 가 LAZY proxy 라 Jackson 직렬화 실패하던 문제 회피.
     * cashBalance 는 활성 BrokerAccount 의 값을 노출 (사용자 단위 룰 설정 + 활성 계정 잔고 합쳐서 표시).
     */
    public record PortfolioSettingsResponse(
            Double buyAmountRatio,
            Double maxPositionRatio,
            Integer cooldownMinutes,
            Double aiScoreThreshold,
            TradingMode tradingMode,
            Double cashBalance
    ) {
        static PortfolioSettingsResponse from(PortfolioSettings s, Double activeCashBalance) {
            return new PortfolioSettingsResponse(
                    s.getBuyAmountRatio(),
                    s.getMaxPositionRatio(),
                    s.getCooldownMinutes(),
                    s.getAiScoreThreshold(),
                    s.getTradingMode(),
                    activeCashBalance
            );
        }
    }

    /**
     * Contract 4b — Trading Terminal 실계좌 잔고 동기화.
     * Terminal 이 명시한 BrokerAccount 의 cashBalance + positions 모두 영속화.
     *
     * <p>brokerAccountId 가 활성 BrokerAccount 와 다르면 거부 (409). Terminal 의 활성 broker 와
     * 백엔드 활성 broker 가 어긋나면 데이터 정합성 손상되므로 명시 거부 — 사용자가 활성 전환 후 재시도.
     * 누락 시 활성 BrokerAccount 로 폴백.
     */
    @PostMapping("/sync")
    public ResponseEntity<Void> sync(
            Authentication auth,
            @Valid @RequestBody PortfolioSyncRequest request) {
        Long userId = (Long) auth.getPrincipal();

        Long activeId = brokerAccountService.getActive(userId)
                .map(BrokerAccount::getId)
                .orElseGet(() -> brokerAccountService
                        .ensure(userId, Broker.KIS, true).getId()); // 신규 사용자 디폴트

        Long brokerAccountId = request.getBrokerAccountId();
        if (brokerAccountId != null && !brokerAccountId.equals(activeId)) {
            log.warn("[PortfolioSync] 비활성 BrokerAccount 로 sync 시도 거부 - userId={} requested={} active={}",
                    userId, brokerAccountId, activeId);
            return ResponseEntity.status(org.springframework.http.HttpStatus.CONFLICT).build();
        }
        if (brokerAccountId == null) {
            brokerAccountId = activeId;
        }

        brokerAccountService.syncCashBalance(userId, brokerAccountId, request.getCashBalance());
        int upserted = positionService.syncSnapshot(
                userId, brokerAccountId, request.getPositions());
        log.info("[PortfolioSync] 동기화 - userId={} brokerAccountId={} cashBalance={} positions(received)={} positions(upserted)={}",
                userId, brokerAccountId, request.getCashBalance(),
                request.getPositions() == null ? 0 : request.getPositions().size(),
                upserted);
        return ResponseEntity.ok().build();
    }

    /**
     * 사용자가 보유한 BrokerAccount 목록 조회.
     */
    @GetMapping("/broker-accounts")
    public ResponseEntity<List<BrokerAccountResponse>> listBrokerAccounts(Authentication auth) {
        Long userId = (Long) auth.getPrincipal();
        Long activeId = brokerAccountService.getActive(userId).map(BrokerAccount::getId).orElse(null);
        List<BrokerAccountResponse> body = brokerAccountService.listByUser(userId).stream()
                .map(acc -> BrokerAccountResponse.of(acc, acc.getId().equals(activeId)))
                .toList();
        return ResponseEntity.ok(body);
    }

    /**
     * 활성 BrokerAccount 전환.
     */
    @PutMapping("/broker-accounts/{brokerAccountId}/activate")
    public ResponseEntity<Void> activateBrokerAccount(
            Authentication auth,
            @PathVariable Long brokerAccountId) {
        Long userId = (Long) auth.getPrincipal();
        brokerAccountService.switchActive(userId, brokerAccountId);
        return ResponseEntity.ok().build();
    }

    public record BrokerAccountResponse(
            Long id, String broker, Boolean isPaper, String alias, Double cashBalance, boolean active
    ) {
        static BrokerAccountResponse of(BrokerAccount a, boolean active) {
            return new BrokerAccountResponse(
                    a.getId(), a.getBroker().name(), a.getIsPaper(),
                    a.getAlias(), a.getCashBalance(), active);
        }
    }
}
