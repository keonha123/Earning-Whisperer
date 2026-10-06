package com.earningwhisperer.global.config;

import org.springframework.boot.context.properties.EnableConfigurationProperties;
import org.springframework.context.annotation.Configuration;

/**
 * 질의응답(#112) 설정 활성화.
 *
 * <p>중계 스레드풀은 여기서 빈으로 만들지 않는다. {@code Executor} 빈이 하나라도 생기면 Spring Boot 가 기본
 * {@code applicationTaskExecutor} 를 만들지 않고, 기존 {@code @Async} 작업(시연 재생 루프 등)이 그 빈을 쓰게 되어
 * 질의응답 중계 스레드를 차지한다. 스레드풀은 {@link com.earningwhisperer.presentation.assistant.AssistantRelay} 가 직접 갖는다.
 */
@Configuration
@EnableConfigurationProperties(AssistantProperties.class)
public class AssistantConfig {
}
