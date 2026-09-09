package com.earningwhisperer.domain.market;

import com.earningwhisperer.infrastructure.redis.MarketIndicesMessage;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * MarketIndicesCache + MarketIndexFormat + MarketIndexTrend 단위 테스트.
 * - put / getAll 알파벳 정렬
 * - 동일 symbol 덮어쓰기
 * - trend (up/down/neutral) 산출
 * - format 매핑 (ETF 5종은 모두 index)
 */
@DisplayName("MarketIndicesCache + 가공 유틸 단위 테스트")
class MarketIndicesCacheTest {

    private final ObjectMapper objectMapper = new ObjectMapper();

    private MarketIndicesMessage parse(String symbol, double price, double changePercent, long timestamp) {
        try {
            String json = String.format(
                    "{\"symbol\":\"%s\",\"price\":%s,\"change_percent\":%s,\"timestamp\":%d}",
                    symbol, price, changePercent, timestamp);
            return objectMapper.readValue(json, MarketIndicesMessage.class);
        } catch (Exception e) {
            throw new RuntimeException(e);
        }
    }

    @Test
    @DisplayName("getAll — 비어 있으면 빈 리스트 반환")
    void getAll_빈_리스트_반환() {
        MarketIndicesCache cache = new MarketIndicesCache();
        assertThat(cache.getAll()).isEmpty();
    }

    @Test
    @DisplayName("put — 5종 입력 후 알파벳 순(DIA, IWM, QQQ, SPY, VIXY)으로 정렬되어 반환")
    void put_5종_알파벳_정렬() {
        MarketIndicesCache cache = new MarketIndicesCache();
        cache.put(parse("VIXY", 17.5, 1.2, 1L));
        cache.put(parse("SPY", 762.0, 0.85, 2L));
        cache.put(parse("DIA", 523.7, -0.30, 3L));
        cache.put(parse("QQQ", 716.0, 0.15, 4L));
        cache.put(parse("IWM", 291.2, -0.04, 5L));

        List<MarketIndexSnapshot> all = cache.getAll();
        assertThat(all).extracting(MarketIndexSnapshot::symbol)
                .containsExactly("DIA", "IWM", "QQQ", "SPY", "VIXY");
    }

    @Test
    @DisplayName("put — 동일 symbol 재발행 시 최신 값으로 덮어쓰여진다")
    void put_동일_symbol_덮어쓰기() {
        MarketIndicesCache cache = new MarketIndicesCache();
        cache.put(parse("SPY", 762.0, 0.85, 100L));
        cache.put(parse("SPY", 765.5, -0.20, 200L));

        List<MarketIndexSnapshot> all = cache.getAll();
        assertThat(all).hasSize(1);
        MarketIndexSnapshot latest = all.get(0);
        assertThat(latest.symbol()).isEqualTo("SPY");
        assertThat(latest.price()).isEqualTo(765.5);
        assertThat(latest.changePercent()).isEqualTo(-0.20);
        assertThat(latest.timestamp()).isEqualTo(200L);
    }

    @Test
    @DisplayName("trend — change_percent > +0.05 → up")
    void trend_up() {
        MarketIndicesCache cache = new MarketIndicesCache();
        cache.put(parse("SPY", 762.0, 0.06, 1L));
        assertThat(cache.getAll().get(0).trend()).isEqualTo("up");
    }

    @Test
    @DisplayName("trend — change_percent < -0.05 → down")
    void trend_down() {
        MarketIndicesCache cache = new MarketIndicesCache();
        cache.put(parse("SPY", 762.0, -0.06, 1L));
        assertThat(cache.getAll().get(0).trend()).isEqualTo("down");
    }

    @Test
    @DisplayName("trend — 임계치 경계(±0.05) 정확히 = neutral")
    void trend_neutral_경계() {
        MarketIndicesCache cache = new MarketIndicesCache();
        cache.put(parse("SPY", 762.0, 0.05, 1L));
        assertThat(cache.getAll().get(0).trend()).isEqualTo("neutral");

        cache.put(parse("QQQ", 716.0, -0.05, 1L));
        // QQQ 추가 후 알파벳 순으로 QQQ, SPY
        assertThat(cache.getAll().stream().filter(s -> s.symbol().equals("QQQ")).findFirst().orElseThrow().trend())
                .isEqualTo("neutral");
    }

    @Test
    @DisplayName("trend — 0.0 → neutral")
    void trend_neutral_zero() {
        MarketIndicesCache cache = new MarketIndicesCache();
        cache.put(parse("VIXY", 17.5, 0.0, 1L));
        assertThat(cache.getAll().get(0).trend()).isEqualTo("neutral");
    }

    @Test
    @DisplayName("trend — 임계 바로 위/바로 아래 핀고정 (±0.05 경계 부동소수 안정성)")
    void trend_임계_바로_위_바로_아래_핀고정() {
        // +0.0500001 → up (양수 임계 바로 위)
        MarketIndicesCache cache1 = new MarketIndicesCache();
        cache1.put(parse("SPY", 762.0, 0.0500001, 1L));
        assertThat(cache1.getAll().get(0).trend()).isEqualTo("up");

        // +0.0499999 → neutral (양수 임계 바로 아래)
        MarketIndicesCache cache2 = new MarketIndicesCache();
        cache2.put(parse("SPY", 762.0, 0.0499999, 1L));
        assertThat(cache2.getAll().get(0).trend()).isEqualTo("neutral");

        // -0.0500001 → down (음수 임계 바로 아래)
        MarketIndicesCache cache3 = new MarketIndicesCache();
        cache3.put(parse("SPY", 762.0, -0.0500001, 1L));
        assertThat(cache3.getAll().get(0).trend()).isEqualTo("down");

        // -0.0499999 → neutral (음수 임계 바로 위)
        MarketIndicesCache cache4 = new MarketIndicesCache();
        cache4.put(parse("SPY", 762.0, -0.0499999, 1L));
        assertThat(cache4.getAll().get(0).trend()).isEqualTo("neutral");
    }

    @Test
    @DisplayName("format — ETF 5종은 모두 index")
    void format_매핑_검증() {
        MarketIndicesCache cache = new MarketIndicesCache();
        cache.put(parse("SPY", 762.0, 0.0, 1L));
        cache.put(parse("QQQ", 716.0, 0.0, 1L));
        cache.put(parse("VIXY", 17.5, 0.0, 1L));
        cache.put(parse("DIA", 523.7, 0.0, 1L));
        cache.put(parse("IWM", 291.2, 0.0, 1L));

        assertThat(cache.getAll()).allSatisfy(s -> assertThat(s.format()).isEqualTo("index"));
    }

    @Test
    @DisplayName("MarketIndexFormat.isSupported — 5종만 true")
    void isSupported_5종_검증() {
        assertThat(MarketIndexFormat.isSupported("SPY")).isTrue();
        assertThat(MarketIndexFormat.isSupported("QQQ")).isTrue();
        assertThat(MarketIndexFormat.isSupported("VIXY")).isTrue();
        assertThat(MarketIndexFormat.isSupported("DIA")).isTrue();
        assertThat(MarketIndexFormat.isSupported("IWM")).isTrue();

        assertThat(MarketIndexFormat.isSupported("AAPL")).isFalse();
        assertThat(MarketIndexFormat.isSupported("spy")).isFalse(); // 대소문자 구분
        assertThat(MarketIndexFormat.isSupported("")).isFalse();
    }
}
