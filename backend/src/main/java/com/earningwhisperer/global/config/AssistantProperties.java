package com.earningwhisperer.global.config;

import org.springframework.boot.context.properties.ConfigurationProperties;

/**
 * 질의응답(#112) 설정. 값이 비어 있으면(테스트 설정 등) 기본값을 쓴다.
 *
 * @param baseUrl              logothea-assistant 주소(같은 호스트 루프백)
 * @param dailyLimit           사용자별 하루 질문 수
 * @param streamTimeoutSeconds 답변 스트림 전체 상한
 */
@ConfigurationProperties(prefix = "app.assistant")
public record AssistantProperties(String baseUrl, int dailyLimit, int streamTimeoutSeconds) {

    public AssistantProperties {
        if (baseUrl == null || baseUrl.isBlank()) {
            baseUrl = "http://127.0.0.1:8100";
        }
        if (dailyLimit <= 0) {
            dailyLimit = 50;
        }
        if (streamTimeoutSeconds <= 0) {
            streamTimeoutSeconds = 60;
        }
    }
}
