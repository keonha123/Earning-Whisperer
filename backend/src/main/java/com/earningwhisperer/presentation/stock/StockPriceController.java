package com.earningwhisperer.presentation.stock;

import com.earningwhisperer.domain.stock.StockPriceSnapshot;
import com.earningwhisperer.infrastructure.websocket.StockPriceCache;
import lombok.RequiredArgsConstructor;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.Collection;

/**
 * 실시간 주가 스냅샷 엔드포인트.
 * GET /api/v1/stocks/prices — Trading Terminal 초기 마운트 시 전체 캐시 로딩용
 */
@RestController
@RequestMapping("/api/v1/stocks")
@RequiredArgsConstructor
public class StockPriceController {

    private final StockPriceCache priceCache;

    @GetMapping("/prices")
    public ResponseEntity<Collection<StockPriceSnapshot>> getPrices() {
        return ResponseEntity.ok(priceCache.getAll());
    }
}
