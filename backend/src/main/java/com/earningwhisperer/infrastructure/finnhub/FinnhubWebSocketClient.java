package com.earningwhisperer.infrastructure.finnhub;

import com.earningwhisperer.infrastructure.websocket.StockPriceCache;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import lombok.extern.slf4j.Slf4j;

import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.WebSocket;
import java.util.List;
import java.util.concurrent.CompletionStage;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;

/**
 * 단일 Finnhub API 키로 최대 50 심볼을 구독하는 WebSocket 클라이언트.
 * Spring 빈이 아닌 Runnable — FinnhubWebSocketManager 가 키당 하나씩 스레드로 실행.
 */
@Slf4j
public class FinnhubWebSocketClient implements Runnable {

    private static final String WS_BASE = "wss://ws.finnhub.io?token=";
    private static final int[] BACKOFF_SECONDS = {2, 4, 8, 16, 30};

    private final String apiKey;
    private final List<String> tickers;
    private final StockPriceCache priceCache;
    private final ObjectMapper objectMapper;
    private final String label;

    private volatile WebSocket webSocket;

    public FinnhubWebSocketClient(String apiKey, List<String> tickers,
                                  StockPriceCache priceCache, ObjectMapper objectMapper,
                                  String label) {
        this.apiKey = apiKey;
        this.tickers = tickers;
        this.priceCache = priceCache;
        this.objectMapper = objectMapper;
        this.label = label;
    }

    @Override
    public void run() {
        int attempt = 0;
        while (!Thread.currentThread().isInterrupted()) {
            try {
                connect();
                attempt = 0;
            } catch (InterruptedException e) {
                Thread.currentThread().interrupt();
                break;
            } catch (Exception e) {
                int delay = BACKOFF_SECONDS[Math.min(attempt, BACKOFF_SECONDS.length - 1)];
                log.warn("[Finnhub-{}] 연결 실패 — {}초 후 재시도 (시도 {})", label, delay, attempt + 1, e);
                attempt++;
                sleep(delay);
            }
        }
    }

    private void connect() throws Exception {
        CountDownLatch closeLatch = new CountDownLatch(1);
        HttpClient httpClient = HttpClient.newHttpClient();

        webSocket = httpClient.newWebSocketBuilder()
                .buildAsync(URI.create(WS_BASE + apiKey), new Listener(closeLatch))
                .get(15, TimeUnit.SECONDS);

        closeLatch.await();
        log.info("[Finnhub-{}] 연결 종료 — 재연결 준비", label);
    }

    private void sendJson(String json) {
        if (webSocket != null) {
            webSocket.sendText(json, true);
        }
    }

    private void sleep(int seconds) {
        try { TimeUnit.SECONDS.sleep(seconds); } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
        }
    }

    private class Listener implements WebSocket.Listener {

        private final CountDownLatch closeLatch;
        private final StringBuilder buffer = new StringBuilder();

        Listener(CountDownLatch closeLatch) {
            this.closeLatch = closeLatch;
        }

        @Override
        public void onOpen(WebSocket ws) {
            log.info("[Finnhub-{}] 연결됨 — {}개 심볼 구독 시작", label, tickers.size());
            ws.request(1);
            for (String ticker : tickers) {
                ws.sendText("{\"type\":\"subscribe\",\"symbol\":\"" + ticker + "\"}", true);
            }
        }

        @Override
        public CompletionStage<?> onText(WebSocket ws, CharSequence data, boolean last) {
            buffer.append(data);
            if (last) {
                handleMessage(buffer.toString());
                buffer.setLength(0);
            }
            ws.request(1);
            return null;
        }

        @Override
        public CompletionStage<?> onClose(WebSocket ws, int statusCode, String reason) {
            log.info("[Finnhub-{}] 연결 닫힘 — code={} reason={}", label, statusCode, reason);
            closeLatch.countDown();
            return null;
        }

        @Override
        public void onError(WebSocket ws, Throwable error) {
            log.warn("[Finnhub-{}] 오류 발생", label, error);
            closeLatch.countDown();
        }

        private void handleMessage(String raw) {
            try {
                JsonNode root = objectMapper.readTree(raw);
                String type = root.path("type").asText();
                switch (type) {
                    case "trade" -> handleTrades(root.path("data"));
                    case "ping" -> sendJson("{\"type\":\"pong\"}");
                    case "error" -> log.error("[Finnhub-{}] 서버 오류: {}", label, root.path("msg").asText());
                }
            } catch (Exception e) {
                log.warn("[Finnhub-{}] 메시지 파싱 실패: {}", label, raw, e);
            }
        }

        private void handleTrades(JsonNode data) {
            if (!data.isArray()) return;
            for (JsonNode trade : data) {
                String ticker = trade.path("s").asText();
                double price = trade.path("p").asDouble();
                if (!ticker.isEmpty() && price > 0) {
                    priceCache.update(ticker, price);
                }
            }
        }
    }
}
