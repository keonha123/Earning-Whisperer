package com.earningwhisperer.infrastructure.websocket;

import com.earningwhisperer.domain.stock.DailyBarRepository;
import com.earningwhisperer.domain.stock.Stock;
import com.earningwhisperer.domain.stock.StockPriceSnapshot;
import com.earningwhisperer.domain.stock.StockRepository;
import com.earningwhisperer.domain.stock.TickerLatestClose;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;

import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.BDDMockito.given;

/**
 * 전일종가 재적재.
 *
 * <p>전일종가는 기동 시 한 번만 일봉에서 채워졌다. 그래서 일봉을 새로 동기화해도 앱을
 * 재시작할 때까지 옛 값이 남았고, 그 값으로 변동률을 계산하면 화면에 없던 폭락이 떴다 —
 * 실제로 WMT 가 4개월 전 종가(130.15)와 비교되어 -18.5% 로 표시됐다.
 */
@ExtendWith(MockitoExtension.class)
@DisplayName("StockPriceCache 전일종가 재적재")
class StockPriceCacheRefreshTest {

    @Mock private StockRepository stockRepository;
    @Mock private DailyBarRepository dailyBarRepository;

    @InjectMocks private StockPriceCache cache;

    private static Stock stockOf(String ticker) {
        return Stock.builder().ticker(ticker).companyName("Co").sector("STAPLES").build();
    }

    private StockPriceSnapshot snapshotOf(String ticker) {
        return cache.getAllAsMap().get(ticker);
    }

    @BeforeEach
    void 기동_초기화() {
        given(stockRepository.findByActiveTrue()).willReturn(List.of(stockOf("WMT")));
        given(dailyBarRepository.findLatestClosesByTickers(any()))
                .willReturn(List.of(new TickerLatestClose("WMT", 130.15)));
        cache.initialize();
    }

    @Test
    @DisplayName("일봉이 갱신되면 전일종가와 변동률이 새 값 기준으로 다시 계산된다")
    void 전일종가_갱신() {
        cache.update("WMT", 106.06);
        assertThat(snapshotOf("WMT").changePercent()).isLessThan(-18.0); // 옛 종가 기준

        given(dailyBarRepository.findLatestClosesByTickers(any()))
                .willReturn(List.of(new TickerLatestClose("WMT", 105.83)));

        assertThat(cache.refreshPreviousCloses()).isEqualTo(1);

        StockPriceSnapshot after = snapshotOf("WMT");
        assertThat(after.previousClose()).isEqualTo(105.83);
        // 현재가는 유지된다 — 실시간 시세를 일봉 종가로 덮어쓰면 안 된다.
        assertThat(after.currentPrice()).isEqualTo(106.06);
        assertThat(after.changePercent()).isBetween(0.0, 1.0);
    }

    @Test
    @DisplayName("값이 그대로면 아무것도 바꾸지 않는다")
    void 변화_없으면_무시() {
        given(dailyBarRepository.findLatestClosesByTickers(any()))
                .willReturn(List.of(new TickerLatestClose("WMT", 130.15)));

        assertThat(cache.refreshPreviousCloses()).isZero();
    }

    @Test
    @DisplayName("일봉이 0 이하로 오면 무시한다 — 멀쩡한 전일종가를 0 으로 덮지 않는다")
    void 비정상_종가_무시() {
        given(dailyBarRepository.findLatestClosesByTickers(any()))
                .willReturn(List.of(new TickerLatestClose("WMT", 0.0)));

        assertThat(cache.refreshPreviousCloses()).isZero();
        assertThat(snapshotOf("WMT").previousClose()).isEqualTo(130.15);
    }
}
