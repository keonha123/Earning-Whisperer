package com.earningwhisperer.infrastructure.fmp.dto;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;
import com.fasterxml.jackson.annotation.JsonProperty;

import java.math.BigDecimal;
import java.util.Optional;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/**
 * FMP `/v3/profile/{ticker}` 응답의 단일 항목.
 *
 * <p>FMP 는 항상 배열 형태(`[{...}]`)로 1건을 반환하므로 호출자는 첫 요소만 취해 이 record 로 매핑한다.
 * 알 수 없는 필드는 무시한다(스펙상 다수 필드 존재하나 본 도메인에서는 일부만 사용).
 */
@JsonIgnoreProperties(ignoreUnknown = true)
public record FmpProfile(
        @JsonProperty("symbol") String symbol,
        @JsonProperty("companyName") String companyName,
        @JsonProperty("sector") String sector,
        @JsonProperty("mktCap") BigDecimal mktCap,
        @JsonProperty("lastDiv") BigDecimal lastDiv,
        @JsonProperty("price") BigDecimal price,
        /** 예: "75.60-138.07" — 52주 최저-최고. 누락/포맷불일치시 low52w/high52w empty. */
        @JsonProperty("range") String range
) {

    /** "75.60-138.07" 형식의 range 문자열을 파싱하기 위한 정규식. */
    private static final Pattern RANGE_PATTERN = Pattern.compile("^([\\d.]+)-([\\d.]+)$");

    /** 52주 최저가. range 가 null/포맷 불일치이면 empty. */
    public Optional<BigDecimal> low52w() {
        return parseRangeAt(0);
    }

    /** 52주 최고가. range 가 null/포맷 불일치이면 empty. */
    public Optional<BigDecimal> high52w() {
        return parseRangeAt(1);
    }

    private Optional<BigDecimal> parseRangeAt(int groupIndex) {
        if (range == null || range.isBlank()) return Optional.empty();
        Matcher m = RANGE_PATTERN.matcher(range.trim());
        if (!m.matches()) return Optional.empty();
        try {
            // groupIndex 0 → group(1) (low), 1 → group(2) (high)
            return Optional.of(new BigDecimal(m.group(groupIndex + 1)));
        } catch (NumberFormatException e) {
            return Optional.empty();
        }
    }
}
