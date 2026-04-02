package com.earningwhisperer.presentation.portfolio;

import com.fasterxml.jackson.annotation.JsonProperty;
import jakarta.validation.constraints.NotNull;
import lombok.Getter;
import lombok.NoArgsConstructor;

import java.util.List;

/**
 * Contract 4b — Trading Terminal → 백엔드 실계좌 잔고 동기화 요청 DTO.
 *
 * Terminal이 KIS API에서 조회한 실계좌 데이터를 POST /api/v1/portfolio/sync 로 전송.
 * cashBalance는 룰 엔진의 매수 수량 계산(buyAmountRatio * cashBalance)에 활용된다.
 */
@Getter
@NoArgsConstructor
public class PortfolioSyncRequest {

    @NotNull
    @JsonProperty("cash_balance")
    private Double cashBalance;

    /** 보유 종목 목록 (룰엔진 장부 오차 교정용) */
    private List<PositionDto> positions;

    @JsonProperty("synced_at")
    private Long syncedAt; // UTC Unix Epoch Second

    @Getter
    @NoArgsConstructor
    public static class PositionDto {
        private String ticker;
        private Integer quantity;
        @JsonProperty("avg_price")
        private Double avgPrice;
    }
}
