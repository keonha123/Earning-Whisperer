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
 * - format (index/percent) 매핑
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
    @DisplayName("put — 5종 입력 후 알파벳 순(10Y, DXY, NDX, SPX, VIX)으로 정렬되어 반환")
    void put_5종_알파벳_정렬() {
        MarketIndicesCache cache = new MarketIndicesCache();
        cache.put(parse("VIX", 14.5, 1.2, 1L));
        cache.put(parse("SPX", 5300.0, 0.85, 2L));
        cache.put(parse("DXY", 104.2, -0.30, 3L));
        cache.put(parse("NDX", 18500.0, 0.15, 4L));
        cache.put(parse("10Y", 4.35, -0.04, 5L));

        List<MarketIndexSnapshot> all = cache.getAll();
        assertThat(all).extracting(MarketIndexSnapshot::symbol)
                .containsExactly("10Y", "DXY", "NDX", "SPX", "VIX");
    }

    @Test
    @DisplayName("put — 동일 symbol 재발행 시 최신 값으로 덮어쓰여진다")
    void put_동일_symbol_덮어쓰기() {
        MarketIndicesCache cache = new MarketIndicesCache();
        cache.put(parse("SPX", 5300.0, 0.85, 100L));
        cache.put(parse("SPX", 5310.5, -0.20, 200L));

        List<MarketIndexSnapshot> all = cache.getAll();
        assertThat(all).hasSize(1);
        MarketIndexSnapshot latest = all.get(0);
        assertThat(latest.symbol()).isEqualTo("SPX");
        assertThat(latest.price()).isEqualTo(5310.5);
        assertThat(latest.changePercent()).isEqualTo(-0.20);
        assertThat(latest.timestamp()).isEqualTo(200L);
    }

    @Test
    @DisplayName("trend — change_percent > +0.05 → up")
    void trend_up() {
        MarketIndicesCache cache = new MarketIndicesCache();
        cache.put(parse("SPX", 5300.0, 0.06, 1L));
        assertThat(cache.getAll().get(0).trend()).isEqualTo("up");
    }

    @Test
    @DisplayName("trend — change_percent < -0.05 → down")
    void trend_down() {
        MarketIndicesCache cache = new MarketIndicesCache();
        cache.put(parse("SPX", 5300.0, -0.06, 1L));
        assertThat(cache.getAll().get(0).trend()).isEqualTo("down");
    }

    @Test
    @DisplayName("trend — 임계치 경계(±0.05) 정확히 = neutral")
    void trend_neutral_경계() {
        MarketIndicesCache cache = new MarketIndicesCache();
        cache.put(parse("SPX", 5300.0, 0.05, 1L));
        assertThat(cache.getAll().get(0).trend()).isEqualTo("neutral");

        cache.put(parse("NDX", 18500.0, -0.05, 1L));
        // NDX 추가 후 알파벳 순으로 NDX, SPX
        assertThat(cache.getAll().stream().filter(s -> s.symbol().equals("NDX")).findFirst().orElseThrow().trend())
                .isEqualTo("neutral");
    }

    @Test
    @DisplayName("trend — 0.0 → neutral")
    void trend_neutral_zero() {
        MarketIndicesCache cache = new MarketIndicesCache();
        cache.put(parse("VIX", 14.5, 0.0, 1L));
        assertThat(cache.getAll().get(0).trend()).isEqualTo("neutral");
    }

    @Test
    @DisplayName("trend — 임계 바로 위/바로 아래 핀고정 (±0.05 경계 부동소수 안정성)")
    void trend_임계_바로_위_바로_아래_핀고정() {
        // +0.0500001 → up (양수 임계 바로 위)
        MarketIndicesCache cache1 = new MarketIndicesCache();
        cache1.put(parse("SPX", 5300.0, 0.0500001, 1L));
        assertThat(cache1.getAll().get(0).trend()).isEqualTo("up");

        // +0.0499999 → neutral (양수 임계 바로 아래)
        MarketIndicesCache cache2 = new MarketIndicesCache();
        cache2.put(parse("SPX", 5300.0, 0.0499999, 1L));
        assertThat(cache2.getAll().get(0).trend()).isEqualTo("neutral");

        // -0.0500001 → down (음수 임계 바로 아래)
        MarketIndicesCache cache3 = new MarketIndicesCache();
        cache3.put(parse("SPX", 5300.0, -0.0500001, 1L));
        assertThat(cache3.getAll().get(0).trend()).isEqualTo("down");

        // -0.0499999 → neutral (음수 임계 바로 위)
        MarketIndicesCache cache4 = new MarketIndicesCache();
        cache4.put(parse("SPX", 5300.0, -0.0499999, 1L));
        assertThat(cache4.getAll().get(0).trend()).isEqualTo("neutral");
    }

    @Test
    @DisplayName("format — SPX/NDX/VIX/DXY = index, 10Y = percent")
    void format_매핑_검증() {
        MarketIndicesCache cache = new MarketIndicesCache();
        cache.put(parse("SPX", 5300.0, 0.0, 1L));
        cache.put(parse("NDX", 18500.0, 0.0, 1L));
        cache.put(parse("VIX", 14.5, 0.0, 1L));
        cache.put(parse("DXY", 104.2, 0.0, 1L));
        cache.put(parse("10Y", 4.35, 0.0, 1L));

        for (MarketIndexSnapshot s : cache.getAll()) {
            if (s.symbol().equals("10Y")) {
                assertThat(s.format()).isEqualTo("percent");
            } else {
                assertThat(s.format()).isEqualTo("index");
            }
        }
    }

    @Test
    @DisplayName("MarketIndexFormat.isSupported — 5종만 true")
    void isSupported_5종_검증() {
        assertThat(MarketIndexFormat.isSupported("SPX")).isTrue();
        assertThat(MarketIndexFormat.isSupported("NDX")).isTrue();
        assertThat(MarketIndexFormat.isSupported("VIX")).isTrue();
        assertThat(MarketIndexFormat.isSupported("DXY")).isTrue();
        assertThat(MarketIndexFormat.isSupported("10Y")).isTrue();

        assertThat(MarketIndexFormat.isSupported("AAPL")).isFalse();
        assertThat(MarketIndexFormat.isSupported("spx")).isFalse(); // 대소문자 구분
        assertThat(MarketIndexFormat.isSupported("")).isFalse();
    }
}
