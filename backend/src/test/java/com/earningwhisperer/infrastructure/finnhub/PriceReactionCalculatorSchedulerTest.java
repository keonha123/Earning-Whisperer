package com.earningwhisperer.infrastructure.finnhub;

import ch.qos.logback.classic.Level;
import ch.qos.logback.classic.Logger;
import ch.qos.logback.classic.spi.ILoggingEvent;
import ch.qos.logback.core.read.ListAppender;
import com.earningwhisperer.domain.earnings.EarningsResult;
import com.earningwhisperer.domain.earnings.EarningsResultRepository;
import com.earningwhisperer.domain.stock.Stock;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.slf4j.LoggerFactory;

import java.lang.reflect.Field;
import java.time.Instant;
import java.time.LocalDate;
import java.time.ZoneOffset;
import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyLong;
import static org.mockito.BDDMockito.given;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;

/**
 * {@link PriceReactionCalculatorScheduler} 단위 테스트.
 *
 * <p>{@link PriceReactionCalculatorService} mock — 계산 로직은 별도 테스트.
 */
@ExtendWith(MockitoExtension.class)
@DisplayName("PriceReactionCalculatorScheduler 단위 테스트")
class PriceReactionCalculatorSchedulerTest {

    @Mock private EarningsResultRepository earningsResultRepository;
    @Mock private PriceReactionCalculatorService priceReactionCalculatorService;

    @InjectMocks
    private PriceReactionCalculatorScheduler scheduler;

    private Logger schedulerLogger;
    private ListAppender<ILoggingEvent> appender;

    @BeforeEach
    void setUp() {
        schedulerLogger = (Logger) LoggerFactory.getLogger(PriceReactionCalculatorScheduler.class);
        appender = new ListAppender<>();
        appender.start();
        schedulerLogger.addAppender(appender);
    }

    @AfterEach
    void tearDown() {
        schedulerLogger.detachAppender(appender);
    }

    @Test
    @DisplayName("정상 사이클 — success/dataMissing/dataError 카운트 분기, INFO 로그")
    void 정상_INFO() {
        Stock aapl = stockOf(1L, "AAPL");
        EarningsResult er1 = earningsResultOf(11L, aapl);
        EarningsResult er2 = earningsResultOf(12L, aapl);
        EarningsResult er3 = earningsResultOf(13L, aapl);
        given(earningsResultRepository.findByPriceReactionPercentIsNullAndAnnouncedAtAfter(any(Instant.class)))
                .willReturn(List.of(er1, er2, er3));
        given(priceReactionCalculatorService.computeAndUpdate(11L)).willReturn(PriceReactionResult.COMPUTED);
        given(priceReactionCalculatorService.computeAndUpdate(12L)).willReturn(PriceReactionResult.DATA_MISSING);
        given(priceReactionCalculatorService.computeAndUpdate(13L)).willReturn(PriceReactionResult.COMPUTED);

        scheduler.calculatePriceReactions();

        ILoggingEvent last = latestEvent();
        // dataMissing 만 있으면 ERROR 승격 X (재시도 가능 — 정상 흐름)
        assertThat(last.getLevel()).isEqualTo(Level.INFO);
        assertThat(last.getFormattedMessage())
                .contains("total=3", "success=2", "dataMissing=1", "dataError=0", "failed=0");
    }

    @Test
    @DisplayName("service throw → catch 후 다음 row 진행, stacktrace 로그")
    void service_throw_caught() {
        Stock aapl = stockOf(1L, "AAPL");
        EarningsResult er1 = earningsResultOf(11L, aapl);
        EarningsResult er2 = earningsResultOf(12L, aapl);
        given(earningsResultRepository.findByPriceReactionPercentIsNullAndAnnouncedAtAfter(any(Instant.class)))
                .willReturn(List.of(er1, er2));
        given(priceReactionCalculatorService.computeAndUpdate(11L))
                .willThrow(new RuntimeException("boom"));
        given(priceReactionCalculatorService.computeAndUpdate(12L)).willReturn(PriceReactionResult.COMPUTED);

        scheduler.calculatePriceReactions();

        verify(priceReactionCalculatorService).computeAndUpdate(12L);
        boolean hasWarnWithThrowable = appender.list.stream()
                .anyMatch(e -> e.getLevel() == Level.WARN
                        && e.getFormattedMessage().contains("11")
                        && e.getThrowableProxy() != null);
        assertThat(hasWarnWithThrowable).isTrue();
    }

    @Test
    @DisplayName("오류율 ≥ 30% (failed + dataError) — ERROR 로그 승격")
    void 오류율_초과_ERROR() {
        Stock aapl = stockOf(1L, "AAPL");
        // 3 row 중 1 throw + 1 DATA_ERROR = 66% ≥ 30%
        EarningsResult er1 = earningsResultOf(11L, aapl);
        EarningsResult er2 = earningsResultOf(12L, aapl);
        EarningsResult er3 = earningsResultOf(13L, aapl);
        given(earningsResultRepository.findByPriceReactionPercentIsNullAndAnnouncedAtAfter(any(Instant.class)))
                .willReturn(List.of(er1, er2, er3));
        given(priceReactionCalculatorService.computeAndUpdate(11L))
                .willThrow(new RuntimeException("boom"));
        given(priceReactionCalculatorService.computeAndUpdate(12L)).willReturn(PriceReactionResult.COMPUTED);
        given(priceReactionCalculatorService.computeAndUpdate(13L)).willReturn(PriceReactionResult.DATA_ERROR);

        scheduler.calculatePriceReactions();

        ILoggingEvent last = latestEvent();
        assertThat(last.getLevel()).isEqualTo(Level.ERROR);
        assertThat(last.getFormattedMessage()).contains("오류율 66%", "failed=1", "dataError=1");
    }

    @Test
    @DisplayName("DATA_MISSING 100% 라도 ERROR 승격 X (재시도 가능 흐름이라 INFO)")
    void dataMissing_전부여도_INFO() {
        Stock aapl = stockOf(1L, "AAPL");
        EarningsResult er1 = earningsResultOf(11L, aapl);
        EarningsResult er2 = earningsResultOf(12L, aapl);
        given(earningsResultRepository.findByPriceReactionPercentIsNullAndAnnouncedAtAfter(any(Instant.class)))
                .willReturn(List.of(er1, er2));
        given(priceReactionCalculatorService.computeAndUpdate(11L)).willReturn(PriceReactionResult.DATA_MISSING);
        given(priceReactionCalculatorService.computeAndUpdate(12L)).willReturn(PriceReactionResult.DATA_MISSING);

        scheduler.calculatePriceReactions();

        // failed=0, dataError=0 → errorRate=0 → INFO 유지
        assertThat(latestEvent().getLevel()).isEqualTo(Level.INFO);
        assertThat(latestEvent().getFormattedMessage()).contains("dataMissing=2", "dataError=0");
    }

    @Test
    @DisplayName("후보 비어있으면 service 호출 없이 INFO skip 로그")
    void 후보_없음_skip() {
        given(earningsResultRepository.findByPriceReactionPercentIsNullAndAnnouncedAtAfter(any(Instant.class)))
                .willReturn(List.of());

        scheduler.calculatePriceReactions();

        verify(priceReactionCalculatorService, never()).computeAndUpdate(anyLong());
        assertThat(latestEvent().getLevel()).isEqualTo(Level.INFO);
        assertThat(latestEvent().getFormattedMessage()).contains("백필 대상 없음");
    }

    // ─────────── helpers ───────────

    private ILoggingEvent latestEvent() {
        return appender.list.get(appender.list.size() - 1);
    }

    private static Stock stockOf(Long id, String ticker) {
        Stock s = Stock.builder().ticker(ticker).companyName("Co").sector("TECH").build();
        try {
            Field idField = Stock.class.getDeclaredField("id");
            idField.setAccessible(true);
            idField.set(s, id);
        } catch (Exception e) {
            throw new RuntimeException(e);
        }
        return s;
    }

    private static EarningsResult earningsResultOf(Long id, Stock stock) {
        Instant announcedAt = LocalDate.parse("2025-06-30")
                .atTime(13, 0).toInstant(ZoneOffset.UTC);
        EarningsResult er = EarningsResult.builder()
                .stock(stock)
                .announcedAt(announcedAt)
                .fiscalPeriodLabel("Q2 FY25")
                .build();
        try {
            Field idField = EarningsResult.class.getDeclaredField("id");
            idField.setAccessible(true);
            idField.set(er, id);
        } catch (Exception e) {
            throw new RuntimeException(e);
        }
        return er;
    }
}
