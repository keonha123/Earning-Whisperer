package com.earningwhisperer.domain.assistant;

import com.earningwhisperer.domain.earnings.EarningsCalendar;
import com.earningwhisperer.domain.earnings.EarningsCalendarRepository;
import com.earningwhisperer.domain.earnings.EarningsResult;
import com.earningwhisperer.domain.earnings.EarningsResultRepository;
import com.earningwhisperer.domain.stock.Stock;
import com.earningwhisperer.domain.stock.StockRepository;
import com.earningwhisperer.domain.transcript.TranscriptSegment;
import com.earningwhisperer.domain.transcript.TranscriptSegmentStore;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.math.BigDecimal;
import java.time.Instant;
import java.time.temporal.ChronoUnit;
import java.util.List;
import java.util.Optional;

/**
 * logothea-assistant 가 근거로 읽는 backend 데이터 조회 (#112).
 *
 * <p>근거 시점 규칙: 실적 발표문은 콜 당일 콜보다 먼저 나오므로 as_of 하루 뒤까지 발표된 결과를 포함하고,
 * 다음 일정은 as_of 하루 전 이후의 가장 이른 일정을 쓴다(진행 중인 콜 자신의 일정이 잡히도록).
 *
 * <p>주가 반응은 발표 후 {@link #PRICE_REACTION_WINDOW_DAYS} 일 종가까지 반영해 계산되므로, 창이 as_of 까지
 * 닫히지 않은 결과의 반응값은 미래 정보라 내보내지 않는다(null).
 */
@Service
@RequiredArgsConstructor
public class AssistantContextQueryService {

    private static final long ONE_DAY_SECONDS = 86_400L;

    /** PriceReactionCalculatorService.WINDOW_DAYS(패키지 비공개)와 같은 의미의 값. 바꾸면 함께 바꾼다. */
    static final long PRICE_REACTION_WINDOW_DAYS = 7L;

    private final TranscriptSegmentStore segmentStore;
    private final StockRepository stockRepository;
    private final EarningsResultRepository resultRepository;
    private final EarningsCalendarRepository calendarRepository;

    public record SegmentsView(List<TranscriptSegment> segments, int lastSequence) {}

    /** 결과와, as_of 시점에 알 수 있는 주가 반응(창이 열려 있으면 null). */
    public record ResultView(EarningsResult result, BigDecimal priceReactionPercent) {}

    public record EstimatesView(String ticker, Optional<EarningsCalendar> upcoming, List<ResultView> recentResults) {}

    public Optional<SegmentsView> segments(String callId, int untilSequence) {
        List<TranscriptSegment> segments = segmentStore.findUntil(callId, untilSequence);
        if (segments.isEmpty()) {
            return Optional.empty();
        }
        return Optional.of(new SegmentsView(segments, segments.get(segments.size() - 1).sequence()));
    }

    @Transactional(readOnly = true)
    public Optional<EstimatesView> estimates(String ticker, long asOfEpoch) {
        String symbol = ticker.trim().toUpperCase();
        Optional<Stock> stock = stockRepository.findByTicker(symbol);
        if (stock.isEmpty()) {
            return Optional.empty();
        }
        Long stockId = stock.get().getId();
        Instant resultCutoff = Instant.ofEpochSecond(asOfEpoch + ONE_DAY_SECONDS);
        Instant asOf = Instant.ofEpochSecond(asOfEpoch);
        List<ResultView> results = resultRepository.findTop4ByStock_IdOrderByAnnouncedAtDesc(stockId).stream()
                .filter(r -> !r.getAnnouncedAt().isAfter(resultCutoff))
                .map(r -> new ResultView(r, r.getAnnouncedAt().plus(PRICE_REACTION_WINDOW_DAYS, ChronoUnit.DAYS).isAfter(asOf)
                        ? null : r.getPriceReactionPercent()))
                .toList();
        Optional<EarningsCalendar> upcoming = calendarRepository
                .findFirstByStock_IdAndScheduledAtAfterOrderByScheduledAtAsc(stockId, Instant.ofEpochSecond(asOfEpoch - ONE_DAY_SECONDS));
        return Optional.of(new EstimatesView(symbol, upcoming, results));
    }
}
