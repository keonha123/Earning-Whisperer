package com.earningwhisperer.infrastructure.stock;

import com.earningwhisperer.domain.stock.Stock;
import com.earningwhisperer.domain.stock.StockRepository;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.boot.ApplicationArguments;
import org.springframework.boot.ApplicationRunner;
import org.springframework.core.io.ClassPathResource;
import org.springframework.stereotype.Component;
import org.springframework.transaction.annotation.Transactional;

import java.io.BufferedReader;
import java.io.InputStreamReader;
import java.nio.charset.StandardCharsets;

/**
 * 앱 시작 시 sp500.csv에서 종목 데이터를 MySQL에 적재.
 * 이미 존재하는 ticker는 건너뜀 (idempotent).
 */
@Slf4j
@Component
@RequiredArgsConstructor
public class StockDataInitializer implements ApplicationRunner {

    private final StockRepository stockRepository;

    @Override
    @Transactional
    public void run(ApplicationArguments args) throws Exception {
        ClassPathResource resource = new ClassPathResource("data/sp500.csv");
        if (!resource.exists()) {
            log.warn("[StockDataInitializer] sp500.csv 파일을 찾을 수 없습니다.");
            return;
        }

        int inserted = 0;
        try (BufferedReader reader = new BufferedReader(
                new InputStreamReader(resource.getInputStream(), StandardCharsets.UTF_8))) {

            String line;
            boolean firstLine = true;
            while ((line = reader.readLine()) != null) {
                if (firstLine) { firstLine = false; continue; } // 헤더 스킵
                String[] parts = line.split(",", 3);
                if (parts.length < 2) continue;

                String ticker = parts[0].trim();
                String companyName = parts[1].trim();
                String sector = parts.length > 2 ? parts[2].trim() : "";

                if (!stockRepository.existsByTicker(ticker)) {
                    stockRepository.save(Stock.builder()
                            .ticker(ticker)
                            .companyName(companyName)
                            .sector(sector)
                            .build());
                    inserted++;
                }
            }
        }
        log.info("[StockDataInitializer] S&P 500 종목 {}개 적재 완료", inserted);
    }
}
