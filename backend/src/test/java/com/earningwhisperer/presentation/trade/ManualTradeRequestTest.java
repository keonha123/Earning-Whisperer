package com.earningwhisperer.presentation.trade;

import com.fasterxml.jackson.databind.ObjectMapper;
import jakarta.validation.ConstraintViolation;
import jakarta.validation.Validation;
import jakarta.validation.Validator;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.util.Set;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * 수동 주문 기록 요청 검증.
 *
 * <p>{@code PENDING} 을 거부하면 지정가 주문처럼 즉시 체결되지 않는 주문을 터미널이
 * 기록할 방법이 없다. 실제로 KIS 모의계좌에 주문(ODNO 0000045881)이 접수됐는데
 * 검증에서 거부되어 체결 내역에 아무것도 남지 않았다.
 */
@DisplayName("ManualTradeRequest 검증 테스트")
class ManualTradeRequestTest {

    private static Validator validator;
    private static ObjectMapper mapper;

    @BeforeAll
    static void setUp() {
        validator = Validation.buildDefaultValidatorFactory().getValidator();
        mapper = new ObjectMapper();
    }

    private static String body(String status, String brokerOrderId) {
        String broker = brokerOrderId == null ? "null" : "\"" + brokerOrderId + "\"";
        return """
                {
                  "ticker": "WMT",
                  "side": "BUY",
                  "order_type": "LIMIT",
                  "order_qty": 1,
                  "price": 112.0,
                  "executed_qty": 0,
                  "executed_price": null,
                  "broker_order_id": %s,
                  "status": "%s"
                }
                """.formatted(broker, status);
    }

    private Set<ConstraintViolation<ManualTradeRequest>> violations(String status, String brokerOrderId)
            throws Exception {
        return validator.validate(mapper.readValue(body(status, brokerOrderId), ManualTradeRequest.class));
    }

    @Test
    @DisplayName("PENDING — 증권사가 접수했지만 미체결인 주문도 기록할 수 있다")
    void PENDING_허용() throws Exception {
        assertThat(violations("PENDING", "0000045881")).isEmpty();
    }

    @Test
    @DisplayName("PENDING 은 broker_order_id 가 없어도 통과한다 — ODNO 미반환 케이스")
    void PENDING_주문번호_없어도_통과() throws Exception {
        assertThat(violations("PENDING", null)).isEmpty();
    }

    @Test
    @DisplayName("EXECUTED / FAILED 는 그대로 허용된다")
    void 기존_상태_유지() throws Exception {
        assertThat(violations("EXECUTED", "0000045881")).isEmpty();
        assertThat(violations("FAILED", null)).isEmpty();
    }

    @Test
    @DisplayName("EXECUTED 는 broker_order_id 가 없으면 거부된다")
    void EXECUTED_주문번호_필수() throws Exception {
        assertThat(violations("EXECUTED", null))
                .anyMatch(v -> v.getMessage().contains("broker_order_id"));
    }

    @Test
    @DisplayName("정의되지 않은 상태는 거부된다")
    void 알_수_없는_상태_거부() throws Exception {
        assertThat(violations("CANCELLED", null))
                .anyMatch(v -> v.getMessage().contains("status"));
    }
}
