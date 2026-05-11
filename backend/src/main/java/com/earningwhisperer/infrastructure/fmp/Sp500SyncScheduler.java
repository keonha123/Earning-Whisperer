package com.earningwhisperer.infrastructure.fmp;

import com.earningwhisperer.domain.stock.Stock;
import com.earningwhisperer.domain.stock.StockRepository;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;

import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.util.*;
import java.util.stream.Collectors;

/**
 * 분기별 S&P 500 구성원 변경 자동 동기화.
 * 출처: github.com/datasets/s-and-p-500-companies (Symbol, Security, GICS Sector)
 */
@Slf4j
@Component
@RequiredArgsConstructor
public class Sp500SyncScheduler {

    private static final String SP500_CSV_URL =
            "https://raw.githubusercontent.com/datasets/s-and-p-500-companies/main/data/constituents.csv";

    private final StockRepository stockRepository;

    /** 분기 첫날 오전 9시 UTC 실행 (1·4·7·10월) */
    @Scheduled(cron = "0 0 9 1 1,4,7,10 *", zone = "UTC")
    public void syncSp500Constituents() {
        try {
            String csv = downloadCsv();
            List<Sp500Holding> holdings = parseCsv(csv);
            if (holdings.isEmpty()) {
                log.warn("[Sp500SyncScheduler] 파싱된 종목 없음 — CSV 형식 확인 필요");
                return;
            }
            upsert(holdings);
            log.info("[Sp500SyncScheduler] S&P 500 동기화 완료: {}개 종목", holdings.size());
        } catch (Exception e) {
            log.error("[Sp500SyncScheduler] CSV 다운로드/파싱 실패: {}", e.getMessage());
        }
    }

    private String downloadCsv() throws Exception {
        HttpClient client = HttpClient.newHttpClient();
        HttpRequest request = HttpRequest.newBuilder()
                .uri(URI.create(SP500_CSV_URL))
                .header("User-Agent", "Mozilla/5.0")
                .GET()
                .build();
        HttpResponse<String> response = client.send(request, HttpResponse.BodyHandlers.ofString());
        if (response.statusCode() != 200) {
            throw new IllegalStateException("HTTP " + response.statusCode() + " from S&P 500 CSV");
        }
        return response.body();
    }

    // GitHub CSV 헤더: Symbol,Security,GICS Sector,GICS Sub-Industry,...
    private List<Sp500Holding> parseCsv(String csv) {
        String[] lines = csv.split("\\r?\\n", -1);
        if (lines.length < 2) return Collections.emptyList();

        List<String> headers = splitCsvLine(lines[0]);
        int tickerCol = indexOfIgnoreCase(headers, "Symbol");
        int nameCol   = indexOfIgnoreCase(headers, "Security");
        int sectorCol = indexOfIgnoreCase(headers, "GICS Sector");

        if (tickerCol < 0 || nameCol < 0) return Collections.emptyList();

        List<Sp500Holding> result = new ArrayList<>();
        for (int i = 1; i < lines.length; i++) {
            String line = lines[i].trim();
            if (line.isEmpty()) continue;

            List<String> cols = splitCsvLine(line);
            if (cols.size() <= Math.max(tickerCol, nameCol)) continue;

            String ticker = cols.get(tickerCol).trim();
            String name   = cols.get(nameCol).trim();
            String sector = (sectorCol >= 0 && cols.size() > sectorCol) ? cols.get(sectorCol).trim() : null;

            if (ticker.isEmpty()) continue;
            result.add(new Sp500Holding(ticker, name, sector.isEmpty() ? null : sector));
        }
        return result;
    }

    private void upsert(List<Sp500Holding> holdings) {
        Map<String, Stock> existingByTicker = stockRepository.findAll().stream()
                .collect(Collectors.toMap(Stock::getTicker, s -> s));
        Set<String> incomingTickers = holdings.stream()
                .map(Sp500Holding::ticker)
                .collect(Collectors.toSet());

        for (Sp500Holding h : holdings) {
            Stock existing = existingByTicker.get(h.ticker());
            if (existing == null) {
                stockRepository.save(Stock.builder()
                        .ticker(h.ticker())
                        .companyName(h.name())
                        .sector(h.sector())
                        .build());
            } else if (!existing.isActive()) {
                existing.reactivate(h.name(), existing.getSector());
            }
        }

        existingByTicker.values().stream()
                .filter(s -> s.isActive() && !incomingTickers.contains(s.getTicker()))
                .forEach(Stock::deactivate);

        stockRepository.flush();
    }

    /** 따옴표로 감싼 필드를 처리하는 단순 CSV 행 분리기 */
    private List<String> splitCsvLine(String line) {
        List<String> result = new ArrayList<>();
        boolean inQuote = false;
        StringBuilder sb = new StringBuilder();
        for (int i = 0; i < line.length(); i++) {
            char c = line.charAt(i);
            if (c == '"') {
                inQuote = !inQuote;
            } else if (c == ',' && !inQuote) {
                result.add(sb.toString());
                sb.setLength(0);
            } else {
                sb.append(c);
            }
        }
        result.add(sb.toString());
        return result;
    }

    private int indexOfIgnoreCase(List<String> cols, String target) {
        for (int i = 0; i < cols.size(); i++) {
            if (cols.get(i).trim().equalsIgnoreCase(target)) return i;
        }
        return -1;
    }

    record Sp500Holding(String ticker, String name, String sector) {}
}
