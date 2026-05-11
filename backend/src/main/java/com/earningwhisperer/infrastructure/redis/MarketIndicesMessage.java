package com.earningwhisperer.infrastructure.redis;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;
import com.fasterxml.jackson.annotation.JsonProperty;
import lombok.Getter;
import lombok.NoArgsConstructor;

/**
 * Data Pipeline이 Redis market-indices 채널에 발행하는 메시지 포맷.
 * api-spec.md Contract 6.3 규격을 따른다.
 *
 * 발행자(Publisher)에 종속된 메타 필드(schema_version, source, published_at)는
 * 백엔드에서 클라이언트로 전달하지 않는다. (가공 책임은 백엔드)
 *
 * 알 수 없는 추가 필드는 무시한다.
 */
@Getter
@NoArgsConstructor
@JsonIgnoreProperties(ignoreUnknown = true)
public class MarketIndicesMessage {

    /** 페이로드 스키마 버전 (예: "1.0"). 클라이언트 전달 X. */
    @JsonProperty("schema_version")
    private String schemaVersion;

    /** 발행 출처 (예: "data-pipeline"). 클라이언트 전달 X. */
    private String source;

    /** 5종 고정: SPX / NDX / VIX / DXY / 10Y */
    private String symbol;

    /** 현재가 (지수 또는 % 단위). */
    private double price;

    /** 전일 대비 등락률 (%). 예: +0.85, -1.20 */
    @JsonProperty("change_percent")
    private double changePercent;

    /** 시세 기준 시각 (UTC Unix Epoch Second). */
    private long timestamp;

    /** 발행 시각. 옵셔널. 클라이언트 전달 X. */
    @JsonProperty("published_at")
    private Long publishedAt;
}
