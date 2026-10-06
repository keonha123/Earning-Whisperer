package com.earningwhisperer.infrastructure.assistant;

/** logothea-assistant 에 연결하지 못했거나 200 이 아닌 응답을 받았다. 메시지는 원인 코드. */
public class AssistantUnavailableException extends Exception {

    public AssistantUnavailableException(String reason) {
        super(reason);
    }

    public AssistantUnavailableException(String reason, Throwable cause) {
        super(reason, cause);
    }
}
