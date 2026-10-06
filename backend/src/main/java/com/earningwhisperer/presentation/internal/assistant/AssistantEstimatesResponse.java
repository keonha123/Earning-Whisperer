package com.earningwhisperer.presentation.internal.assistant;

import com.earningwhisperer.domain.assistant.AssistantContextQueryService;
import com.earningwhisperer.domain.earnings.EarningsCalendar;
import com.earningwhisperer.domain.earnings.EarningsResult;
import com.fasterxml.jackson.databind.PropertyNamingStrategies;
import com.fasterxml.jackson.databind.annotation.JsonNaming;

import java.math.BigDecimal;
import java.time.Instant;
import java.util.List;

@JsonNaming(PropertyNamingStrategies.SnakeCaseStrategy.class)
public record AssistantEstimatesResponse(String ticker, long asOfEpoch, Upcoming upcoming, List<Result> recentResults) {

    @JsonNaming(PropertyNamingStrategies.SnakeCaseStrategy.class)
    public record Upcoming(Instant scheduledAt, BigDecimal epsEstimate, BigDecimal revenueEstimate) {
        static Upcoming from(EarningsCalendar c) {
            return new Upcoming(c.getScheduledAt(), c.getEpsEstimate(), c.getRevenueEstimate());
        }
    }

    @JsonNaming(PropertyNamingStrategies.SnakeCaseStrategy.class)
    public record Result(Instant announcedAt, String fiscalPeriodLabel, BigDecimal epsEstimate, BigDecimal epsActual,
                         BigDecimal surprisePercent, BigDecimal priceReactionPercent) {
        static Result from(EarningsResult r) {
            return new Result(r.getAnnouncedAt(), r.getFiscalPeriodLabel(), r.getEpsEstimate(), r.getEpsActual(),
                    r.getSurprisePercent(), r.getPriceReactionPercent());
        }
    }

    public static AssistantEstimatesResponse of(long asOfEpoch, AssistantContextQueryService.EstimatesView view) {
        return new AssistantEstimatesResponse(view.ticker(), asOfEpoch,
                view.upcoming().map(Upcoming::from).orElse(null),
                view.recentResults().stream().map(Result::from).toList());
    }
}
