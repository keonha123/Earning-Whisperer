package com.earningwhisperer.domain.assistant;

import com.earningwhisperer.domain.earnings.EarningsCalendar;
import com.earningwhisperer.domain.earnings.EarningsCalendarRepository;
import com.earningwhisperer.domain.earnings.EarningsResult;
import com.earningwhisperer.domain.earnings.EarningsResultRepository;
import com.earningwhisperer.domain.stock.Stock;
import com.earningwhisperer.domain.stock.StockRepository;
import com.earningwhisperer.domain.transcript.TranscriptSegment;
import com.earningwhisperer.domain.transcript.TranscriptSegmentStore;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;

import java.math.BigDecimal;
import java.time.Instant;
import java.util.List;
import java.util.Optional;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

@ExtendWith(MockitoExtension.class)
@DisplayName("AssistantContextQueryService")
class AssistantContextQueryServiceTest {

    private static final long AS_OF = 1_787_227_200L; // 2026-08-20T12:00:00Z

    @Mock TranscriptSegmentStore segmentStore;
    @Mock StockRepository stockRepository;
    @Mock EarningsResultRepository resultRepository;
    @Mock EarningsCalendarRepository calendarRepository;
    @InjectMocks AssistantContextQueryService service;

    private static TranscriptSegment segment(int sequence) {
        return new TranscriptSegment("WMT", "call-1", sequence, 0, 1000, "text " + sequence, null, AS_OF + sequence, false);
    }

    private static EarningsResult result(Instant announcedAt, String label) {
        EarningsResult r = mock(EarningsResult.class);
        when(r.getAnnouncedAt()).thenReturn(announcedAt);
        org.mockito.Mockito.lenient().when(r.getFiscalPeriodLabel()).thenReturn(label);
        return r;
    }

    @Test
    @DisplayName("세그먼트는 저장소 결과와 마지막 sequence 를 함께 돌려준다")
    void segments() {
        when(segmentStore.findUntil("call-1", 99)).thenReturn(List.of(segment(0), segment(1)));

        AssistantContextQueryService.SegmentsView view = service.segments("call-1", 99).orElseThrow();

        assertThat(view.segments()).hasSize(2);
        assertThat(view.lastSequence()).isEqualTo(1);
    }

    @Test
    @DisplayName("저장된 세그먼트가 없으면 empty")
    void segments_empty() {
        when(segmentStore.findUntil("none", 5)).thenReturn(List.of());

        assertThat(service.segments("none", 5)).isEmpty();
    }

    @Test
    @DisplayName("실적은 as_of 하루 뒤까지 발표된 것만, 다음 일정은 as_of 하루 전 이후 가장 이른 것")
    void estimates_timeScope() {
        Stock stock = mock(Stock.class);
        when(stock.getId()).thenReturn(7L);
        when(stockRepository.findByTicker("WMT")).thenReturn(Optional.of(stock));
        EarningsResult past = result(Instant.ofEpochSecond(AS_OF - 90 * 86_400L), "Q1 FY27");
        EarningsResult sameDay = result(Instant.ofEpochSecond(AS_OF - 3600), "Q2 FY27");
        EarningsResult future = result(Instant.ofEpochSecond(AS_OF + 90 * 86_400L), "Q3 FY27");
        when(resultRepository.findTop4ByStock_IdOrderByAnnouncedAtDesc(7L)).thenReturn(List.of(future, sameDay, past));
        EarningsCalendar upcoming = mock(EarningsCalendar.class);
        when(calendarRepository.findFirstByStock_IdAndScheduledAtAfterOrderByScheduledAtAsc(
                7L, Instant.ofEpochSecond(AS_OF - 86_400L))).thenReturn(Optional.of(upcoming));

        AssistantContextQueryService.EstimatesView view = service.estimates("wmt", AS_OF).orElseThrow();

        assertThat(view.recentResults()).containsExactly(sameDay, past);
        assertThat(view.upcoming()).contains(upcoming);
    }

    @Test
    @DisplayName("모르는 종목이면 empty")
    void estimates_unknown() {
        when(stockRepository.findByTicker("ZZZ")).thenReturn(Optional.empty());

        assertThat(service.estimates("ZZZ", AS_OF)).isEmpty();
    }
}
