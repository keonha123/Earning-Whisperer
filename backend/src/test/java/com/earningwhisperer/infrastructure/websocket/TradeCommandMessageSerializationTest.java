package com.earningwhisperer.infrastructure.websocket;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * Terminal validateSignal 의 typeof === 'string' 가드와 일관되도록
 * trade_id 는 반드시 JSON string 으로 직렬화되어야 한다 (number 가 되면 명령 100% 폐기).
 * STOMP 메시지와 GET /api/v1/trades/pending 응답이 동일 형식임을 보장하기 위한 회귀 가드.
 */
@DisplayName("TradeCommandMessage 직렬화 회귀 테스트")
class TradeCommandMessageSerializationTest {

    @Test
    @DisplayName("trade_id 는 JSON string 으로 직렬화된다")
    void tradeId_string으로_직렬화() throws Exception {
        TradeCommandMessage msg = TradeCommandMessage.builder()
                .tradeId(7L)
                .action("BUY")
                .orderRatio(0.1)
                .ticker("NVDA")
                .aiScore(0.85)
                .build();

        ObjectMapper mapper = new ObjectMapper();
        JsonNode tree = mapper.valueToTree(msg);

        assertThat(tree.get("trade_id").isTextual()).isTrue();
        assertThat(tree.get("trade_id").asText()).isEqualTo("7");
    }
}
