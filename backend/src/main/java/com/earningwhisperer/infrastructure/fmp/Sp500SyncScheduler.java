package com.earningwhisperer.infrastructure.fmp;

import com.earningwhisperer.domain.stock.Stock;
import com.earningwhisperer.domain.stock.StockRepository;
import com.fasterxml.jackson.annotation.JsonProperty;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Qualifier;
import org.springframework.boot.autoconfigure.condition.ConditionalOnExpression;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;
import org.springframework.web.client.RestClient;
import org.springframework.web.client.RestClientException;

import java.util.Arrays;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.stream.Collectors;

/**
 * 분기별 S&P 500 구성원 변경 자동 동기화.
 * FMP 무료 티어 /v3/sp500_constituent (250 req/day).
 * FMP_API_KEY 미설정 시 비활성화됨.
 */
@Slf4j
@Component
@ConditionalOnExpression("!'${fmp.api-key:}'.isBlank()")
public class Sp500SyncScheduler {

    private final RestClient restClient;
    private final FmpProperties properties;
    private final StockRepository stockRepository;

    public Sp500SyncScheduler(
            @Qualifier("fmpRestClient") RestClient restClient,
            FmpProperties properties,
            StockRepository stockRepository) {
        this.restClient = restClient;
        this.properties = properties;
        this.stockRepository = stockRepository;
    }

    /** 분기 첫날 오전 9시 UTC 실행 (1·4·7·10월) */
    @Scheduled(cron = "0 0 9 1 1,4,7,10 *", zone = "UTC")
    public void syncSp500Constituents() {
        try {
            FmpConstituent[] constituents = restClient.get()
                    .uri(uriBuilder -> uriBuilder
                            .path("/v3/sp500_constituent")
                            .queryParam("apikey", properties.apiKey())
                            .build())
                    .retrieve()
                    .body(FmpConstituent[].class);

            if (constituents == null || constituents.length == 0) return;

            List<FmpConstituent> list = Arrays.asList(constituents);
            Map<String, Stock> existingByTicker = stockRepository.findAll().stream()
                    .collect(Collectors.toMap(Stock::getTicker, s -> s));
            Set<String> incomingTickers = list.stream()
                    .map(FmpConstituent::symbol)
                    .collect(Collectors.toSet());

            // 신규 편입
            for (FmpConstituent c : list) {
                Stock existing = existingByTicker.get(c.symbol());
                if (existing == null) {
                    stockRepository.save(Stock.builder()
                            .ticker(c.symbol())
                            .companyName(c.name())
                            .sector(c.sector())
                            .build());
                } else if (!existing.isActive()) {
                    existing.reactivate(c.name(), c.sector());
                }
            }

            // 제외 종목 soft delete
            existingByTicker.values().stream()
                    .filter(s -> s.isActive() && !incomingTickers.contains(s.getTicker()))
                    .forEach(Stock::deactivate);

            stockRepository.flush();
            log.info("[Sp500SyncScheduler] S&P 500 동기화 완료: {}개 종목", incomingTickers.size());
        } catch (RestClientException e) {
            log.error("[Sp500SyncScheduler] FMP 호출 실패: {}", e.getMessage());
        }
    }

    record FmpConstituent(String symbol, String name, String sector,
                          @JsonProperty("subSector") String subSector) {}
}
