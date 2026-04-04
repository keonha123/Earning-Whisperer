package com.earningwhisperer.infrastructure.fmp;

import org.springframework.boot.context.properties.ConfigurationProperties;

@ConfigurationProperties(prefix = "fmp")
public record FmpProperties(String baseUrl, String apiKey) {}
