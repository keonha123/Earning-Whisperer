package com.earningwhisperer.presentation.earnings;

import com.earningwhisperer.domain.earnings.EarningsCalendar;
import com.earningwhisperer.domain.earnings.EarningsCalendarService;
import com.earningwhisperer.domain.watchlist.WatchlistService;
import com.earningwhisperer.infrastructure.finnhub.FinnhubEarningsScheduler;
import lombok.RequiredArgsConstructor;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.http.ResponseEntity;
import org.springframework.security.core.Authentication;
import org.springframework.web.bind.annotation.*;

import java.util.List;
import java.util.Optional;

@RestController
@RequestMapping("/api/v1/earnings-calendar")
@RequiredArgsConstructor
public class EarningsCalendarController {

    private final EarningsCalendarService earningsCalendarService;
    private final WatchlistService watchlistService;

    @Autowired(required = false)
    private FinnhubEarningsScheduler finnhubEarningsScheduler;

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

    /**
     * Trading Terminal용 어닝콜 타임라인 — S&P 500 전체 종목 대상.
     * 관심종목 필터 없이 향후 N일 일정을 flat list로 반환한다.
     * 그룹핑(live/today/tomorrow/week)은 Terminal main process에서 수행한다.
     *
     * @param days 조회 기간 (기본 7일, 최대 14일)
     */
    @GetMapping("/terminal-timeline")
    public ResponseEntity<List<TerminalEarningsItem>> getTerminalTimeline(
            @RequestParam(defaultValue = "7") int days) {
        int safeDays = Math.min(days, 30);
        List<TerminalEarningsItem> result = earningsCalendarService.getCalendar(safeDays).stream()
                .map(TerminalEarningsItem::from)
                .toList();
        return ResponseEntity.ok(result);
    }

    /** 개발/테스트용 수동 갱신. Finnhub 키 미설정 시 409 반환. */
    @PostMapping("/sync")
    public ResponseEntity<String> syncNow() {
        if (finnhubEarningsScheduler == null) {
            return ResponseEntity.status(409).body("FINNHUB_API_KEY가 설정되지 않았습니다.");
        }
        finnhubEarningsScheduler.syncEarningsCalendar();
        return ResponseEntity.ok("어닝 일정 갱신 요청 완료");
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

    record TerminalEarningsItem(
            String ticker,
            String companyName,
            long scheduledAt,
            boolean confirmed,
            String marketSession) {

        static TerminalEarningsItem from(EarningsCalendar e) {
            return new TerminalEarningsItem(
                    e.getStock().getTicker(),
                    e.getStock().getCompanyName(),
                    e.getScheduledAt().getEpochSecond(),
                    e.isConfirmed(),
                    e.getMarketSession());
        }
    }
}
