package com.earningwhisperer.presentation.stock;

import com.earningwhisperer.domain.stock.Stock;
import com.earningwhisperer.domain.stock.StockMeta;
import com.earningwhisperer.domain.stock.StockPriceSnapshot;
import com.earningwhisperer.domain.stock.StockRepository;
import com.earningwhisperer.infrastructure.websocket.StockPriceCache;
import lombok.RequiredArgsConstructor;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.List;
import java.util.Map;

/**
 * S&P 500 종목 리스트 엔드포인트.
 * GET /api/v1/stocks/sp500 — JWT 불필요 (Market Screen 초기 로딩용)
 */
@RestController
@RequestMapping("/api/v1/stocks")
@RequiredArgsConstructor
public class StockListController {

    private final StockRepository stockRepository;
    private final StockPriceCache priceCache;

    @GetMapping("/sp500")
    public ResponseEntity<List<StockSummaryDto>> getSp500() {
        Map<String, StockPriceSnapshot> prices = priceCache.getAllAsMap();

        List<StockSummaryDto> result = stockRepository.findAllActiveWithMetaSorted()
                .stream()
                .map(row -> {
                    Stock s = (Stock) row[0];
                    StockMeta sm = row[1] != null ? (StockMeta) row[1] : null;
                    StockPriceSnapshot snap = prices.get(s.getTicker());

                    Double currentPrice = snap != null ? snap.currentPrice() : null;
                    Double changePercent = snap != null ? snap.changePercent() : null;
                    Double marketCap = sm != null && sm.getMarketCapUsd() != null
                            ? sm.getMarketCapUsd().doubleValue()
                            : null;

                    return new StockSummaryDto(
                            s.getTicker(),
                            s.getCompanyName(),
                            s.getSector(),
                            marketCap,
                            currentPrice,
                            changePercent
                    );
                })
                .toList();

        return ResponseEntity.ok(result);
    }
}
