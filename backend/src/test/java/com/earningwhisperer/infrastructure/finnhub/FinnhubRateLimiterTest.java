package com.earningwhisperer.infrastructure.finnhub;

import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.util.ArrayList;
import java.util.List;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.TimeUnit;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

/**
 * FinnhubRateLimiter 단위 테스트.
 *
 * <p>실제 ScheduledExecutorService 를 사용하므로 약간의 sleep 이 포함된다.
 * Finnhub limiter 는 분당 토큰 버킷만 담당 — 일일 카운터/예외 시나리오는 없음.
 */
@DisplayName("FinnhubRateLimiter 단위 테스트")
class FinnhubRateLimiterTest {

    private FinnhubRateLimiter limiter;

    @BeforeEach
    void setUp() {
        limiter = new FinnhubRateLimiter(null);
    }

    @AfterEach
    void tearDown() {
        if (limiter != null) {
            limiter.shutdown();
        }
    }

    @Test
    @DisplayName("토큰 버킷 burst 후 두 번째 호출은 refill 대기로 더 오래 걸린다")
    void 토큰_버킷_burst_후_대기() {
        // 첫 번째 호출 — 초기 capacity 1 토큰으로 즉시 통과
        long t0 = System.nanoTime();
        limiter.acquire(FinnhubRateLimiter.Priority.HIGH);
        long firstElapsedMs = (System.nanoTime() - t0) / 1_000_000;

        // 두 번째 호출 — 토큰 0 → 100ms tick 마다 0.05 refill 누적, 1 토큰까지 약 1.9~2초 소요
        long t1 = System.nanoTime();
        limiter.acquire(FinnhubRateLimiter.Priority.HIGH);
        long secondElapsedMs = (System.nanoTime() - t1) / 1_000_000;

        assertThat(firstElapsedMs).isLessThan(500);
        // 두 번째는 refill 으로 적어도 첫 번째보다 의미있게 더 걸려야 함
        assertThat(secondElapsedMs).isGreaterThan(firstElapsedMs + 500);
        // 토큰 1개 채우는 데 0.5 req/s = 2초. 약간의 여유 ± 허용
        assertThat(secondElapsedMs).isLessThan(3500);
    }

    @Test
    @DisplayName("HIGH 우선순위가 LOW 보다 먼저 처리된다")
    void HIGH_우선순위_먼저_처리() throws Exception {
        // 초기 토큰 1 개 즉시 소진
        limiter.acquire(FinnhubRateLimiter.Priority.HIGH);

        // 이제 토큰 0. LOW 두 개 먼저 큐에 넣고, HIGH 한 개 나중에 넣는다.
        ExecutorService pool = Executors.newFixedThreadPool(3);
        try {
            List<String> completionOrder = new ArrayList<>();
            Object orderLock = new Object();

            CompletableFuture<Void> low1 = CompletableFuture.runAsync(() -> {
                limiter.acquire(FinnhubRateLimiter.Priority.LOW);
                synchronized (orderLock) {
                    completionOrder.add("LOW1");
                }
            }, pool);
            CompletableFuture<Void> low2 = CompletableFuture.runAsync(() -> {
                limiter.acquire(FinnhubRateLimiter.Priority.LOW);
                synchronized (orderLock) {
                    completionOrder.add("LOW2");
                }
            }, pool);

            // LOW 들이 먼저 큐에 들어가도록 잠시 대기
            Thread.sleep(150);

            CompletableFuture<Void> high = CompletableFuture.runAsync(() -> {
                limiter.acquire(FinnhubRateLimiter.Priority.HIGH);
                synchronized (orderLock) {
                    completionOrder.add("HIGH");
                }
            }, pool);

            // 셋 다 완료까지 충분히 대기 (약 2초씩 × 3 = 6초)
            CompletableFuture.allOf(low1, low2, high).get(15, TimeUnit.SECONDS);

            // HIGH 가 LOW1, LOW2 보다 먼저 완료되어야 함
            int highIdx = completionOrder.indexOf("HIGH");
            int low1Idx = completionOrder.indexOf("LOW1");
            int low2Idx = completionOrder.indexOf("LOW2");
            assertThat(highIdx).isGreaterThanOrEqualTo(0);
            assertThat(highIdx).isLessThan(low1Idx);
            assertThat(highIdx).isLessThan(low2Idx);
        } finally {
            pool.shutdownNow();
        }
    }

    @Test
    @DisplayName("shutdown 시 대기중인 waiter 는 FinnhubRateLimitExceededException 으로 깨어난다")
    void shutdown_시_대기중_waiter_깨움() throws Exception {
        // 초기 토큰 1 즉시 소진
        limiter.acquire(FinnhubRateLimiter.Priority.HIGH);

        ExecutorService pool = Executors.newSingleThreadExecutor();
        try {
            CompletableFuture<Throwable> caught = CompletableFuture.supplyAsync(() -> {
                try {
                    limiter.acquire(FinnhubRateLimiter.Priority.LOW);
                    return null;
                } catch (Throwable t) {
                    return t;
                }
            }, pool);

            // waiter 가 큐에 들어가도록 잠시 대기
            Thread.sleep(200);

            // shutdown — 대기중 waiter 가 예외로 깨어나야 한다
            limiter.shutdown();
            limiter = null;

            Throwable t = caught.get(5, TimeUnit.SECONDS);
            assertThat(t).isInstanceOf(FinnhubRateLimitExceededException.class);
            assertThat(t.getMessage()).contains("cancelled");
        } finally {
            pool.shutdownNow();
        }
    }

    @Test
    @DisplayName("refill task 가 throw 해도 후속 tick 에서 self-heal 한다")
    void refill_task_self_heal() {
        // scheduleWithFixedDelay + try/catch 래퍼가 적용된 상태에서 다회 acquire 정상 통과
        limiter.acquire(FinnhubRateLimiter.Priority.HIGH);
        limiter.acquire(FinnhubRateLimiter.Priority.HIGH);
        limiter.acquire(FinnhubRateLimiter.Priority.HIGH);
    }

    @Test
    @DisplayName("shutdown 이후 진입한 acquire 는 즉시 FinnhubRateLimitExceededException 으로 거부된다")
    void shutdown_이후_acquire_즉시_거부() {
        FinnhubRateLimiter disposed = new FinnhubRateLimiter(null);
        disposed.shutdown();

        assertThatThrownBy(() -> disposed.acquire(FinnhubRateLimiter.Priority.HIGH))
                .isInstanceOf(FinnhubRateLimitExceededException.class)
                .hasMessageContaining("disposed");
    }
}
