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

import java.time.Instant;
import java.util.List;
import java.util.Optional;

/**
 * logothea-assistant 가 근거로 읽는 backend 데이터 조회 (#112).
 *
 * <p>근거 시점 규칙: 실적 발표문은 콜 당일 콜보다 먼저 나오므로 as_of 하루 뒤까지 발표된 결과를 포함하고,
 * 다음 일정은 as_of 하루 전 이후의 가장 이른 일정을 쓴다(진행 중인 콜 자신의 일정이 잡히도록).
 */
@Service
@RequiredArgsConstructor
public class AssistantContextQueryService {

    private static final long ONE_DAY_SECONDS = 86_400L;

    private final TranscriptSegmentStore segmentStore;
    private final StockRepository stockRepository;
    private final EarningsResultRepository resultRepository;
    private final EarningsCalendarRepository calendarRepository;

    public record SegmentsView(List<TranscriptSegment> segments, int lastSequence) {}

    public record EstimatesView(String ticker, Optional<EarningsCalendar> upcoming, List<EarningsResult> recentResults) {}

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
        List<EarningsResult> results = resultRepository.findTop4ByStock_IdOrderByAnnouncedAtDesc(stockId).stream()
                .filter(r -> !r.getAnnouncedAt().isAfter(resultCutoff))
                .toList();
        Optional<EarningsCalendar> upcoming = calendarRepository
                .findFirstByStock_IdAndScheduledAtAfterOrderByScheduledAtAsc(stockId, Instant.ofEpochSecond(asOfEpoch - ONE_DAY_SECONDS));
        return Optional.of(new EstimatesView(symbol, upcoming, results));
    }
}
