package com.earningwhisperer.global.config;

import com.earningwhisperer.infrastructure.finnhub.FinnhubProperties;
import com.earningwhisperer.infrastructure.fmp.FmpProperties;
import org.springframework.boot.context.properties.EnableConfigurationProperties;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.scheduling.annotation.EnableScheduling;
import org.springframework.web.client.RestClient;

@Configuration
@EnableScheduling
@EnableConfigurationProperties({FinnhubProperties.class, FmpProperties.class})
public class ExternalApiConfig {

    @Bean("finnhubRestClient")
    public RestClient finnhubRestClient(FinnhubProperties props) {
        return RestClient.builder()
                .baseUrl(props.baseUrl())
                .build();
    }

    @Bean("fmpRestClient")
    public RestClient fmpRestClient(FmpProperties props) {
        return RestClient.builder()
                .baseUrl(props.baseUrl())
                .build();
    }
}
