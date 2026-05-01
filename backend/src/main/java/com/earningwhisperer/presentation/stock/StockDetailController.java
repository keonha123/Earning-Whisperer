package com.earningwhisperer.presentation.stock;

import com.earningwhisperer.domain.stock.StockDetailService;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.http.ResponseEntity;
import org.springframework.security.core.Authentication;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.Map;
import java.util.regex.Pattern;

/**
 * Phase 3: 종목 상세 REST 엔드포인트.
 *
 * <p>경로: {@code GET /api/v1/stocks/{ticker}/detail}
 *
 * <p>인증: JWT 필수 (SecurityConfig 의 default {@code anyRequest().authenticated()} 적용).
 * userId 는 본 phase 에서 활용하지 않는다 — 모든 사용자가 동일한 데이터를 조회.
 *
 * <p>응답 코드:
 * <ul>
 *     <li>200: 정상 응답 (full 또는 partial — body 의 {@code partial} 필드로 구분)</li>
 *     <li>400: ticker 정규식 미통과</li>
 *     <li>503: 외부 의존성 장애로 Stock 자체가 없음 (LazyFetch 모든 시도 실패 + DB 미존재)</li>
 *     <li>500: 예상치 못한 RuntimeException</li>
 * </ul>
 */
@RestController
@RequestMapping("/api/v1/stocks")
@RequiredArgsConstructor
@Slf4j
public class StockDetailController {

    private static final Pattern TICKER_PATTERN = Pattern.compile("^[A-Z0-9.-]{1,10}$");

    private final StockDetailService stockDetailService;

    @GetMapping("/{ticker}/detail")
    public ResponseEntity<?> getDetail(@PathVariable String ticker, Authentication auth) {
        if (ticker == null || !TICKER_PATTERN.matcher(ticker).matches()) {
            return ResponseEntity.badRequest().body(Map.of("error", "invalid ticker"));
        }
        try {
            return stockDetailService.getDetail(ticker)
                    .<ResponseEntity<?>>map(ResponseEntity::ok)
                    .orElseGet(() -> ResponseEntity.status(503).body(
                            Map.of("error", "stock detail unavailable — external sync failed")));
        } catch (IllegalArgumentException iae) {
            // service 측 정규식 검증과 컨트롤러 정규식이 어긋난 경우 — 안전망
            return ResponseEntity.badRequest().body(Map.of("error", iae.getMessage()));
        } catch (RuntimeException e) {
            log.error("[StockDetail] {} 처리 실패", ticker, e);
            return ResponseEntity.status(500).body(Map.of("error", "internal error"));
        }
    }
}
