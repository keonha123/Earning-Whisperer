package com.earningwhisperer.infrastructure.websocket;

import com.fasterxml.jackson.annotation.JsonProperty;
import lombok.Builder;
import lombok.Getter;

/**
 * 데모룸 주가 틱 메시지 포맷.
 * Topic: /topic/live/demo/price
 *
 * DemoPriceService가 1초 간격으로 브로드캐스트한다.
 * price, change, change_percent는 DemoPriceService가 랜덤 워크로 생성한다.
 */
@Getter
@Builder
public class DemoPriceMessage {

    private String ticker;
    private double price;
    private double change;

    @JsonProperty("change_percent")
    private double changePercent;

    private long timestamp;
}
