package com.earningwhisperer.presentation.earnings;

import com.earningwhisperer.domain.earnings.EarningsCalendar;
import com.earningwhisperer.domain.earnings.EarningsCalendarService;
import com.earningwhisperer.domain.watchlist.WatchlistService;
import lombok.RequiredArgsConstructor;
import org.springframework.http.ResponseEntity;
import org.springframework.security.core.Authentication;
import org.springframework.web.bind.annotation.*;

import java.time.ZoneOffset;
import java.util.List;

@RestController
@RequestMapping("/api/v1/earnings-calendar")
@RequiredArgsConstructor
public class EarningsCalendarController {

    private final EarningsCalendarService earningsCalendarService;
    private final WatchlistService watchlistService;

    /**
     * 내 관심종목의 향후 어닝 일정 조회.
     * ?days=30 파라미터로 조회 기간 지정 (기본 60일).
     */
    @GetMapping
    public ResponseEntity<List<EarningsCalendarResponse>> getMyEarningsCalendar(
            @RequestParam(defaultValue = "60") int days,
            Authentication auth) {
        Long userId = (Long) auth.getPrincipal();

        List<String> tickers = watchlistService.getWatchlist(userId).stream()
                .map(item -> item.getStock().getTicker())
                .toList();

        List<EarningsCalendarResponse> result = earningsCalendarService
                .getUpcomingByTickers(tickers).stream()
                .map(EarningsCalendarResponse::from)
                .toList();

        return ResponseEntity.ok(result);
    }

    record EarningsCalendarResponse(
            String ticker,
            String companyName,
            long scheduledAt,
            boolean confirmed) {

        static EarningsCalendarResponse from(EarningsCalendar e) {
            return new EarningsCalendarResponse(
                    e.getStock().getTicker(),
                    e.getStock().getCompanyName(),
                    e.getScheduledAt().getEpochSecond(),
                    e.isConfirmed());
        }
    }
}
