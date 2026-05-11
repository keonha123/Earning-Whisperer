package com.earningwhisperer.presentation.market;

import com.earningwhisperer.domain.market.MarketIndicesCache;
import lombok.RequiredArgsConstructor;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.List;

/**
 * 5종 글로벌 시장 지수 REST 엔드포인트.
 *
 * Contract 7.7 — GET /api/v1/market/indices
 * - 인증 불필요 (SecurityConfig 에서 permitAll)
 * - 캐시가 비어 있으면 200 OK 와 함께 빈 배열을 반환한다 (404/503 X)
 * - 응답 필드는 STOMP /topic/market/indices 페이로드와 동일.
 */
@RestController
@RequestMapping("/api/v1/market/indices")
@RequiredArgsConstructor
public class MarketIndicesController {

    private final MarketIndicesCache cache;

    @GetMapping
    public ResponseEntity<List<MarketIndexResponse>> getAll() {
        List<MarketIndexResponse> body = cache.getAll().stream()
                .map(MarketIndexResponse::from)
                .toList();
        return ResponseEntity.ok(body);
    }
}
