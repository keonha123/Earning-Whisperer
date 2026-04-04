package com.earningwhisperer.presentation.trade;

import com.earningwhisperer.domain.trade.TradeService;
import jakarta.validation.Valid;
import lombok.RequiredArgsConstructor;
import org.springframework.data.domain.Page;
import org.springframework.data.domain.PageRequest;
import org.springframework.data.domain.Sort;
import org.springframework.http.ResponseEntity;
import org.springframework.security.core.Authentication;
import org.springframework.web.bind.annotation.*;

/**
 * Contract 4 — Trading Terminal 체결 콜백 수신 컨트롤러.
 *
 * Trading Terminal이 KIS API로 주문 실행 후 결과를 이 엔드포인트로 전송한다.
 * Trade 상태를 PENDING → EXECUTED / FAILED 로 업데이트한다.
 */
@RestController
@RequestMapping("/api/v1/trades")
@RequiredArgsConstructor
public class TradeController {

    private final TradeService tradeService;

    /**
     * 거래 내역 페이지네이션 조회 (마이페이지용).
     * createdAt 내림차순 정렬.
     */
    @GetMapping
    public ResponseEntity<Page<TradeResponse>> getMyTrades(
            Authentication auth,
            @RequestParam(defaultValue = "0") int page,
            @RequestParam(defaultValue = "20") int size) {
        Long userId = (Long) auth.getPrincipal();
        PageRequest pageable = PageRequest.of(page, size, Sort.by("createdAt").descending());
        Page<TradeResponse> result = tradeService.getMyTrades(userId, pageable);
        return ResponseEntity.ok(result);
    }

    @PostMapping("/{tradeId}/callback")
    public ResponseEntity<Void> callback(
            Authentication auth,
            @PathVariable Long tradeId,
            @Valid @RequestBody TradeCallbackRequest request) {
        Long callerId = (Long) auth.getPrincipal();
        tradeService.processCallback(tradeId, callerId, request);
        return ResponseEntity.ok().build();
    }
}
