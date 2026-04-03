package com.earningwhisperer.presentation.watchlist;

import com.earningwhisperer.domain.stock.Stock;
import com.earningwhisperer.domain.watchlist.WatchlistItem;
import com.earningwhisperer.domain.watchlist.WatchlistService;
import lombok.RequiredArgsConstructor;
import org.springframework.http.ResponseEntity;
import org.springframework.security.core.Authentication;
import org.springframework.web.bind.annotation.*;

import java.util.List;

@RestController
@RequestMapping("/api/v1/watchlist")
@RequiredArgsConstructor
public class WatchlistController {

    private final WatchlistService watchlistService;

    @GetMapping
    public ResponseEntity<List<WatchlistItemResponse>> getWatchlist(Authentication auth) {
        Long userId = (Long) auth.getPrincipal();
        List<WatchlistItemResponse> items = watchlistService.getWatchlist(userId).stream()
                .map(WatchlistItemResponse::from)
                .toList();
        return ResponseEntity.ok(items);
    }

    @PostMapping
    public ResponseEntity<WatchlistItemResponse> addToWatchlist(
            @RequestBody AddWatchlistRequest request,
            Authentication auth) {
        Long userId = (Long) auth.getPrincipal();
        WatchlistItem item = watchlistService.addToWatchlist(userId, request.ticker());
        return ResponseEntity.ok(WatchlistItemResponse.from(item));
    }

    @DeleteMapping("/{ticker}")
    public ResponseEntity<Void> removeFromWatchlist(
            @PathVariable String ticker,
            Authentication auth) {
        Long userId = (Long) auth.getPrincipal();
        watchlistService.removeFromWatchlist(userId, ticker);
        return ResponseEntity.noContent().build();
    }

    @GetMapping("/search")
    public ResponseEntity<List<StockSearchResponse>> search(@RequestParam String q) {
        List<StockSearchResponse> results = watchlistService.searchStocks(q).stream()
                .limit(20)
                .map(StockSearchResponse::from)
                .toList();
        return ResponseEntity.ok(results);
    }

    record AddWatchlistRequest(String ticker) {}

    record WatchlistItemResponse(String ticker, String companyName, String sector) {
        static WatchlistItemResponse from(WatchlistItem item) {
            Stock s = item.getStock();
            return new WatchlistItemResponse(s.getTicker(), s.getCompanyName(), s.getSector());
        }
    }

    record StockSearchResponse(String ticker, String companyName, String sector) {
        static StockSearchResponse from(Stock s) {
            return new StockSearchResponse(s.getTicker(), s.getCompanyName(), s.getSector());
        }
    }
}
