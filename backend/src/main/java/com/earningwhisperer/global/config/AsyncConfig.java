package com.earningwhisperer.global.config;

import org.springframework.context.annotation.Configuration;
import org.springframework.scheduling.annotation.EnableAsync;

/**
 * 비동기 처리 설정.
 *
 * @EnableAsync: @Async 어노테이션 활성화.
 * DemoReplayService, DemoPriceService 등 백그라운드 루프 서비스에서 사용.
 */
@Configuration
@EnableAsync
public class AsyncConfig {
}
