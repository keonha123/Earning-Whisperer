package com.earningwhisperer.domain.assistant;

import lombok.Getter;

/** 질의응답 요청을 assistant 로 넘기기 전에 거절하는 사유. */
@Getter
public class AssistantAskException extends RuntimeException {

    public enum Reason { SEGMENTS_NOT_FOUND, TICKER_MISMATCH }

    private final Reason reason;

    public AssistantAskException(Reason reason) {
        super(reason.name());
        this.reason = reason;
    }
}
