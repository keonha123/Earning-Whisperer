package com.earningwhisperer.infrastructure.finnhub;

import ch.qos.logback.classic.Level;
import ch.qos.logback.classic.Logger;
import ch.qos.logback.classic.spi.ILoggingEvent;
import ch.qos.logback.core.read.ListAppender;
import com.earningwhisperer.domain.earnings.EarningsResult;
import com.earningwhisperer.domain.earnings.EarningsResultRepository;
import com.earningwhisperer.domain.stock.DailyBar;
import com.earningwhisperer.domain.stock.DailyBarRepository;
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
import java.math.BigDecimal;
import java.time.Instant;
import java.time.LocalDate;
import java.time.ZoneOffset;
import java.util.List;
import java.util.Optional;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.BDDMockito.given;

/**
 * {@link PriceReactionCalculatorService} 단위 테스트.
 *
 * <p>Repository mock — DB 미접근.
 */
@ExtendWith(MockitoExtension.class)
@DisplayName("PriceReactionCalculatorService 단위 테스트")
class PriceReactionCalculatorServiceTest {

    @Mock private EarningsResultRepository earningsResultRepository;
    @Mock private DailyBarRepository dailyBarRepository;

    @InjectMocks
    private PriceReactionCalculatorService service;

    private Stock aapl;
    private Logger serviceLogger;
    private ListAppender<ILoggingEvent> appender;

    @BeforeEach
    void setUp() {
        aapl = stockOf(1L, "AAPL");
        serviceLogger = (Logger) LoggerFactory.getLogger(PriceReactionCalculatorService.class);
        appender = new ListAppender<>();
        appender.start();
        serviceLogger.addAppender(appender);
    }

    @AfterEach
    void tearDown() {
        serviceLogger.detachAppender(appender);
    }

    @Test
    @DisplayName("정상 케이스 — before/after 일봉 있음, pct 계산 + updatePriceReaction")
    void 정상_pct_계산() {
        EarningsResult er = earningsResultOf(10L, "2025-06-30");
        DailyBar before = barOf("2025-06-27", "100.00");
        DailyBar after = barOf("2025-07-01", "105.00");
        DailyBar earlier = barOf("2025-06-26", "99.00");

        given(earningsResultRepository.findById(10L)).willReturn(Optional.of(er));
        given(dailyBarRepository.findByStock_IdAndBarDateBetween(eq(1L), any(LocalDate.class), any(LocalDate.class)))
                .willReturn(List.of(earlier, before, after));

        PriceReactionResult ok = service.computeAndUpdate(10L);

        assertThat(ok).isEqualTo(PriceReactionResult.COMPUTED);
        // (105 - 100) / 100 * 100 = 5.0000
        assertThat(er.getPriceReactionPercent()).isEqualByComparingTo("5.0000");
    }

    @Test
    @DisplayName("EarningsResult 미존재 → false 반환, WARN 로그")
    void earningsResult_미존재_false() {
        given(earningsResultRepository.findById(99L)).willReturn(Optional.empty());

        PriceReactionResult ok = service.computeAndUpdate(99L);

        assertThat(ok).isEqualTo(PriceReactionResult.DATA_ERROR);
        assertThat(appender.list).anyMatch(e -> e.getLevel() == Level.WARN
                && e.getFormattedMessage().contains("미존재"));
    }

    @Test
    @DisplayName("윈도 내 일봉 1개 이하 → false")
    void 일봉_부족_false() {
        EarningsResult er = earningsResultOf(10L, "2025-06-30");
        given(earningsResultRepository.findById(10L)).willReturn(Optional.of(er));
        given(dailyBarRepository.findByStock_IdAndBarDateBetween(eq(1L), any(LocalDate.class), any(LocalDate.class)))
                .willReturn(List.of(barOf("2025-06-29", "100.00")));

        PriceReactionResult ok = service.computeAndUpdate(10L);

        assertThat(ok).isEqualTo(PriceReactionResult.DATA_MISSING);
        assertThat(er.getPriceReactionPercent()).isNull();
    }

    @Test
    @DisplayName("eventDate 이전 일봉만 있고 이후 일봉 없음 → DATA_MISSING")
    void after_일봉_없음_false() {
        EarningsResult er = earningsResultOf(10L, "2025-06-30");
        given(earningsResultRepository.findById(10L)).willReturn(Optional.of(er));
        given(dailyBarRepository.findByStock_IdAndBarDateBetween(eq(1L), any(LocalDate.class), any(LocalDate.class)))
                .willReturn(List.of(
                        barOf("2025-06-27", "100.00"),
                        barOf("2025-06-28", "101.00")));

        PriceReactionResult ok = service.computeAndUpdate(10L);

        assertThat(ok).isEqualTo(PriceReactionResult.DATA_MISSING);
        assertThat(er.getPriceReactionPercent()).isNull();
    }

    @Test
    @DisplayName("eventDate 이후 일봉만 있고 이전 일봉 없음 → false")
    void before_일봉_없음_false() {
        EarningsResult er = earningsResultOf(10L, "2025-06-30");
        given(earningsResultRepository.findById(10L)).willReturn(Optional.of(er));
        given(dailyBarRepository.findByStock_IdAndBarDateBetween(eq(1L), any(LocalDate.class), any(LocalDate.class)))
                .willReturn(List.of(
                        barOf("2025-07-01", "100.00"),
                        barOf("2025-07-02", "101.00")));

        PriceReactionResult ok = service.computeAndUpdate(10L);

        assertThat(ok).isEqualTo(PriceReactionResult.DATA_MISSING);
        assertThat(er.getPriceReactionPercent()).isNull();
    }

    @Test
    @DisplayName("before.closePrice = 0 → DATA_ERROR (0 가드)")
    void before_close_zero_dataError() {
        EarningsResult er = earningsResultOf(10L, "2025-06-30");
        DailyBar before = barOf("2025-06-27", "0.00");
        DailyBar after = barOf("2025-07-01", "105.00");

        given(earningsResultRepository.findById(10L)).willReturn(Optional.of(er));
        given(dailyBarRepository.findByStock_IdAndBarDateBetween(eq(1L), any(LocalDate.class), any(LocalDate.class)))
                .willReturn(List.of(before, after));

        PriceReactionResult ok = service.computeAndUpdate(10L);

        assertThat(ok).isEqualTo(PriceReactionResult.DATA_ERROR);
        assertThat(er.getPriceReactionPercent()).isNull();
    }

    @Test
    @DisplayName("가장 가까운 before/after 만 사용 — eventDate 같은 날 봉은 무시")
    void 가장_가까운_봉_사용() {
        EarningsResult er = earningsResultOf(10L, "2025-06-30");
        DailyBar farBefore = barOf("2025-06-25", "90.00");
        DailyBar nearBefore = barOf("2025-06-27", "100.00");
        DailyBar sameDate = barOf("2025-06-30", "200.00"); // 무시되어야
        DailyBar nearAfter = barOf("2025-07-01", "105.00");
        DailyBar farAfter = barOf("2025-07-03", "120.00");

        given(earningsResultRepository.findById(10L)).willReturn(Optional.of(er));
        given(dailyBarRepository.findByStock_IdAndBarDateBetween(eq(1L), any(LocalDate.class), any(LocalDate.class)))
                .willReturn(List.of(farBefore, nearBefore, sameDate, nearAfter, farAfter));

        PriceReactionResult ok = service.computeAndUpdate(10L);

        assertThat(ok).isEqualTo(PriceReactionResult.COMPUTED);
        // (105 - 100) / 100 * 100 = 5.0000 (sameDate 무시 — strictly before/after 사용)
        assertThat(er.getPriceReactionPercent()).isEqualByComparingTo("5.0000");
    }

    @Test
    @DisplayName("HALF_UP 반올림 정확성")
    void half_up_정확성() {
        EarningsResult er = earningsResultOf(10L, "2025-06-30");
        DailyBar before = barOf("2025-06-27", "33.00");
        DailyBar after = barOf("2025-07-01", "34.00");

        given(earningsResultRepository.findById(10L)).willReturn(Optional.of(er));
        given(dailyBarRepository.findByStock_IdAndBarDateBetween(eq(1L), any(LocalDate.class), any(LocalDate.class)))
                .willReturn(List.of(before, after));

        PriceReactionResult ok = service.computeAndUpdate(10L);

        assertThat(ok).isEqualTo(PriceReactionResult.COMPUTED);
        // 1/33 = 0.030303... → 6자리 HALF_UP = 0.030303 → *100 = 3.0303 (4자리 setScale)
        // 정확히는 0.030303 * 100 = 3.0303 (already 4자리)
        assertThat(er.getPriceReactionPercent()).isEqualByComparingTo("3.0303");
    }

    @Test
    @DisplayName("음수 가격반응 — after < before 정상 처리")
    void 음수_pct() {
        EarningsResult er = earningsResultOf(10L, "2025-06-30");
        DailyBar before = barOf("2025-06-27", "100.00");
        DailyBar after = barOf("2025-07-01", "92.50");

        given(earningsResultRepository.findById(10L)).willReturn(Optional.of(er));
        given(dailyBarRepository.findByStock_IdAndBarDateBetween(eq(1L), any(LocalDate.class), any(LocalDate.class)))
                .willReturn(List.of(before, after));

        PriceReactionResult ok = service.computeAndUpdate(10L);

        assertThat(ok).isEqualTo(PriceReactionResult.COMPUTED);
        // (92.50 - 100) / 100 * 100 = -7.5000
        assertThat(er.getPriceReactionPercent()).isEqualByComparingTo("-7.5000");
    }

    @Test
    @DisplayName("가격반응 한도 초과 (|pct| ≥ 9999) → false + WARN, 영속화 미진입")
    void 한도_초과_false() {
        EarningsResult er = earningsResultOf(10L, "2025-06-30");
        // 1 → 100000 = 9999900% → 한도 초과
        DailyBar before = barOf("2025-06-27", "1.0000");
        DailyBar after = barOf("2025-07-01", "100000.0000");

        given(earningsResultRepository.findById(10L)).willReturn(Optional.of(er));
        given(dailyBarRepository.findByStock_IdAndBarDateBetween(eq(1L), any(LocalDate.class), any(LocalDate.class)))
                .willReturn(List.of(before, after));

        PriceReactionResult ok = service.computeAndUpdate(10L);

        assertThat(ok).isEqualTo(PriceReactionResult.DATA_ERROR);
        assertThat(er.getPriceReactionPercent()).isNull();
        assertThat(appender.list).anyMatch(e -> e.getLevel() == Level.WARN
                && e.getFormattedMessage().contains("한도 초과"));
    }

    // ─────────── helpers ───────────

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

    private EarningsResult earningsResultOf(Long id, String periodIso) {
        Instant announcedAt = LocalDate.parse(periodIso)
                .atTime(13, 0).toInstant(ZoneOffset.UTC);
        EarningsResult er = EarningsResult.builder()
                .stock(aapl)
                .announcedAt(announcedAt)
                .fiscalPeriodLabel("Q? FY??")
                .priceReactionPercent(null)
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

    private DailyBar barOf(String date, String close) {
        return DailyBar.builder()
                .stock(aapl)
                .barDate(LocalDate.parse(date))
                .closePrice(new BigDecimal(close))
                .volume(1L)
                .build();
    }
}
