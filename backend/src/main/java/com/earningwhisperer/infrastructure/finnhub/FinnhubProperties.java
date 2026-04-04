package com.earningwhisperer.infrastructure.finnhub;

import org.springframework.boot.context.properties.ConfigurationProperties;

@ConfigurationProperties(prefix = "finnhub")
public record FinnhubProperties(String baseUrl, String apiKey) {}
