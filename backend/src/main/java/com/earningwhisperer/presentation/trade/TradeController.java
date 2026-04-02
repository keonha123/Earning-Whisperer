package com.earningwhisperer.presentation.trade;

import com.earningwhisperer.domain.trade.TradeService;
import jakarta.validation.Valid;
import lombok.RequiredArgsConstructor;
import org.springframework.http.ResponseEntity;
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

    @PostMapping("/{tradeId}/callback")
    public ResponseEntity<Void> callback(
            @PathVariable Long tradeId,
            @Valid @RequestBody TradeCallbackRequest request) {
        tradeService.processCallback(tradeId, request);
        return ResponseEntity.ok().build();
    }
}
