package com.earningwhisperer.global.config;

import com.earningwhisperer.infrastructure.broker.KisBrokerProperties;
import org.springframework.boot.context.properties.EnableConfigurationProperties;
import org.springframework.context.annotation.Configuration;

/**
 * RestClient 및 외부 API 관련 설정.
 *
 * Spring Boot는 RestClient.Builder를 prototype 빈으로 자동 등록하므로
 * 각 컴포넌트(KisTokenManager, KisApiClient)가 독립적인 Builder 인스턴스를 주입받는다.
 */
@Configuration
@EnableConfigurationProperties(KisBrokerProperties.class)
public class RestClientConfig {
}
