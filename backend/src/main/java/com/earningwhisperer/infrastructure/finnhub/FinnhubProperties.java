package com.earningwhisperer.infrastructure.finnhub;

import org.springframework.boot.context.properties.ConfigurationProperties;

import java.util.List;

@ConfigurationProperties(prefix = "finnhub")
public record FinnhubProperties(String baseUrl, String apiKey, List<String> wsKeys) {

    public List<String> activeWsKeys() {
        if (wsKeys == null) return List.of();
        return wsKeys.stream().filter(k -> k != null && !k.isBlank()).toList();
    }
}
