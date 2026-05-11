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

@DisplayName("TradeCallbackRequest 검증 테스트")
class TradeCallbackRequestTest {

    private static Validator validator;
    private static ObjectMapper mapper;

    @BeforeAll
    static void setUp() {
        validator = Validation.buildDefaultValidatorFactory().getValidator();
        mapper = new ObjectMapper();
    }

    @Test
    @DisplayName("EXECUTED + brokerOrderId 정상 입력은 위반이 없다")
    void EXECUTED_정상입력은_위반없음() throws Exception {
        TradeCallbackRequest req = mapper.readValue("""
                {"status":"EXECUTED","broker_order_id":"BROKER-1","executed_qty":3,"executed_price":125.50}
                """, TradeCallbackRequest.class);

        Set<ConstraintViolation<TradeCallbackRequest>> v = validator.validate(req);

        assertThat(v).isEmpty();
    }

    @Test
    @DisplayName("status 가 EXECUTED/FAILED 가 아니면 @Pattern 위반")
    void 잘못된_status는_Pattern_위반() throws Exception {
        TradeCallbackRequest req = mapper.readValue("""
                {"status":"PARTIAL","broker_order_id":"BROKER-1"}
                """, TradeCallbackRequest.class);

        Set<ConstraintViolation<TradeCallbackRequest>> v = validator.validate(req);

        assertThat(v).extracting(c -> c.getPropertyPath().toString()).contains("status");
    }

    @Test
    @DisplayName("status 가 소문자(executed) 면 위반")
    void 소문자_status는_Pattern_위반() throws Exception {
        TradeCallbackRequest req = mapper.readValue("""
                {"status":"executed","broker_order_id":"BROKER-1"}
                """, TradeCallbackRequest.class);

        Set<ConstraintViolation<TradeCallbackRequest>> v = validator.validate(req);

        assertThat(v).isNotEmpty();
    }

    @Test
    @DisplayName("EXECUTED 인데 brokerOrderId 누락이면 @AssertTrue 위반")
    void EXECUTED_brokerOrderId_누락은_위반() throws Exception {
        TradeCallbackRequest req = mapper.readValue("""
                {"status":"EXECUTED","executed_qty":3,"executed_price":125.50}
                """, TradeCallbackRequest.class);

        Set<ConstraintViolation<TradeCallbackRequest>> v = validator.validate(req);

        assertThat(v).isNotEmpty();
        assertThat(v).extracting(ConstraintViolation::getMessage)
                .anyMatch(m -> m.contains("broker_order_id"));
    }

    @Test
    @DisplayName("EXECUTED 인데 brokerOrderId 빈 문자열이면 @AssertTrue 위반")
    void EXECUTED_brokerOrderId_빈문자열은_위반() throws Exception {
        TradeCallbackRequest req = mapper.readValue("""
                {"status":"EXECUTED","broker_order_id":"  ","executed_qty":3}
                """, TradeCallbackRequest.class);

        Set<ConstraintViolation<TradeCallbackRequest>> v = validator.validate(req);

        assertThat(v).isNotEmpty();
    }

    @Test
    @DisplayName("FAILED 콜백은 brokerOrderId 누락이어도 정상")
    void FAILED는_brokerOrderId_생략_허용() throws Exception {
        TradeCallbackRequest req = mapper.readValue("""
                {"status":"FAILED","error_message":"잔고 부족"}
                """, TradeCallbackRequest.class);

        Set<ConstraintViolation<TradeCallbackRequest>> v = validator.validate(req);

        assertThat(v).isEmpty();
    }
}
