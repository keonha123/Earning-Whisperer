package com.earningwhisperer.domain.watchlist;

import com.earningwhisperer.domain.stock.Stock;
import com.earningwhisperer.domain.stock.StockRepository;
import com.earningwhisperer.domain.user.User;
import com.earningwhisperer.domain.user.UserRepository;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.util.List;

@Service
@RequiredArgsConstructor
public class WatchlistService {

    private final WatchlistRepository watchlistRepository;
    private final StockRepository stockRepository;
    private final UserRepository userRepository;

    @Transactional(readOnly = true)
    public List<WatchlistItem> getWatchlist(Long userId) {
        return watchlistRepository.findByUserIdWithStock(userId);
    }

    @Transactional
    public WatchlistItem addToWatchlist(Long userId, String ticker) {
        if (watchlistRepository.existsByUserIdAndStockTicker(userId, ticker)) {
            throw new IllegalArgumentException("이미 관심종목에 추가된 종목입니다.");
        }

        Stock stock = stockRepository.findByTicker(ticker.toUpperCase())
                .orElseThrow(() -> new IllegalArgumentException("지원하지 않는 종목입니다: " + ticker));

        User user = userRepository.getReferenceById(userId);
        return watchlistRepository.save(WatchlistItem.builder().user(user).stock(stock).build());
    }

    @Transactional
    public void removeFromWatchlist(Long userId, String ticker) {
        WatchlistItem item = watchlistRepository.findByUserIdAndStockTicker(userId, ticker)
                .orElseThrow(() -> new IllegalArgumentException("관심종목에 없는 종목입니다: " + ticker));
        watchlistRepository.delete(item);
    }

    @Transactional(readOnly = true)
    public List<Stock> searchStocks(String query) {
        if (query == null || query.isBlank()) {
            return List.of();
        }
        return stockRepository
                .findByActiveTrueAndTickerContainingIgnoreCaseOrActiveTrueAndCompanyNameContainingIgnoreCase(
                        query, query);
    }
}
