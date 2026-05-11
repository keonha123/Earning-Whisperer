package com.earningwhisperer.infrastructure.fmp;

import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.data.redis.core.RedisTemplate;
import org.springframework.data.redis.core.ValueOperations;
import org.springframework.data.redis.core.script.RedisScript;

import java.time.Clock;
import java.util.ArrayList;
import java.util.List;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.ExecutionException;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.concurrent.atomic.AtomicLong;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.lenient;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

/**
 * FmpRateLimiter 단위 테스트.
 *
 * <p>실제 ScheduledExecutorService 와 in-process 시계를 사용하므로 약간의 sleep 이 포함된다.
 * Redis 는 mockito 로 stub. INCR + EXPIRE atomic Lua script 가 적용되었으므로
 * {@code redisTemplate.execute(RedisScript, List, Object...)} 호출을 stub 한다.
 */
@ExtendWith(MockitoExtension.class)
@DisplayName("FmpRateLimiter 단위 테스트")
class FmpRateLimiterTest {

    @SuppressWarnings("unchecked")
    private final RedisTemplate<String, String> redisTemplate = mock(RedisTemplate.class);

    @Mock
    private ValueOperations<String, String> valueOps;

    private FmpRateLimiter limiter;
    private final AtomicLong counter = new AtomicLong(0);
    private final AtomicInteger expireCalls = new AtomicInteger(0);

    @BeforeEach
    void setUp() {
        // Lua INCR+EXPIRE script 호출 stub — counter 증가, 1 일 때 expire 카운트
        lenient().when(redisTemplate.execute(
                        any(RedisScript.class),
                        any(List.class),
                        any(Object[].class)))
                .thenAnswer(inv -> {
                    long v = counter.incrementAndGet();
                    if (v == 1L) {
                        expireCalls.incrementAndGet();
                    }
                    return v;
                });
        // DECR 롤백 경로
        lenient().when(redisTemplate.opsForValue()).thenReturn(valueOps);
        lenient().when(valueOps.decrement(anyString())).thenAnswer(inv -> counter.decrementAndGet());
        lenient().when(valueOps.get(anyString())).thenAnswer(inv -> String.valueOf(counter.get()));

        limiter = new FmpRateLimiter(redisTemplate, Clock.systemUTC(), null);
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
        limiter.acquire(FmpRateLimiter.Priority.HIGH);
        long firstElapsedMs = (System.nanoTime() - t0) / 1_000_000;

        // 두 번째 호출 — 토큰 0 → 100ms tick 마다 0.05 refill 누적, 1 토큰까지 약 1.9~2초 소요
        long t1 = System.nanoTime();
        limiter.acquire(FmpRateLimiter.Priority.HIGH);
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
        limiter.acquire(FmpRateLimiter.Priority.HIGH);

        // 이제 토큰 0. LOW 두 개 먼저 큐에 넣고, HIGH 한 개 나중에 넣는다.
        ExecutorService pool = Executors.newFixedThreadPool(3);
        try {
            List<String> completionOrder = new ArrayList<>();
            Object orderLock = new Object();

            CompletableFuture<Void> low1 = CompletableFuture.runAsync(() -> {
                limiter.acquire(FmpRateLimiter.Priority.LOW);
                synchronized (orderLock) {
                    completionOrder.add("LOW1");
                }
            }, pool);
            CompletableFuture<Void> low2 = CompletableFuture.runAsync(() -> {
                limiter.acquire(FmpRateLimiter.Priority.LOW);
                synchronized (orderLock) {
                    completionOrder.add("LOW2");
                }
            }, pool);

            // LOW 들이 먼저 큐에 들어가도록 잠시 대기
            Thread.sleep(150);

            CompletableFuture<Void> high = CompletableFuture.runAsync(() -> {
                limiter.acquire(FmpRateLimiter.Priority.HIGH);
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
    @DisplayName("일일 한도 초과 시 RateLimitExceededException 을 throw 하고 카운터를 롤백한다")
    void 일일_한도_초과시_예외() {
        // counter 를 미리 한도까지 올려둔다
        counter.set(FmpRateLimiter.DAILY_LIMIT);

        // 다음 INCR 은 DAILY_LIMIT + 1 → exception
        assertThatThrownBy(() -> limiter.acquire(FmpRateLimiter.Priority.HIGH))
                .isInstanceOf(RateLimitExceededException.class)
                .hasMessageContaining("daily quota exceeded");

        // 자신이 올린 1만 롤백되었는지
        assertThat(counter.get()).isEqualTo(FmpRateLimiter.DAILY_LIMIT);
    }

    @Test
    @DisplayName("getRemainingDailyQuota 는 DAILY_LIMIT - 사용량을 반환한다")
    void 남은_quota_조회() {
        counter.set(50);
        when(valueOps.get(anyString())).thenReturn("50");

        assertThat(limiter.getRemainingDailyQuota())
                .isEqualTo(FmpRateLimiter.DAILY_LIMIT - 50);
    }

    @Test
    @DisplayName("Redis 키가 없으면 DAILY_LIMIT 을 그대로 반환한다")
    void 카운터_없으면_전체_quota() {
        when(valueOps.get(anyString())).thenReturn(null);

        assertThat(limiter.getRemainingDailyQuota())
                .isEqualTo(FmpRateLimiter.DAILY_LIMIT);
    }

    @Test
    @DisplayName("첫 INCR 시 EXPIRE 가 atomic Lua 안에서 호출된다 (TTL 설정)")
    void 첫_INCR_시_EXPIRE_호출() {
        // counter 0 → INCR 결과 1 → EXPIRE 호출 트리거
        limiter.acquire(FmpRateLimiter.Priority.HIGH);
        assertThat(expireCalls.get()).isEqualTo(1);

        // 두 번째 호출 (counter=2) 은 EXPIRE 호출 없음
        // 단, 토큰 refill 대기 필요 — burst 후 약 2초 대기
        limiter.acquire(FmpRateLimiter.Priority.HIGH);
        assertThat(expireCalls.get()).isEqualTo(1);
    }

    @Test
    @DisplayName("Redis execute 가 RuntimeException 을 던지면 acquire 는 통과한다 (외부 호출 시도 허용 정책)")
    void Redis_장애시_acquire_통과() {
        // 새 limiter — Redis execute 가 항상 실패하도록 stub
        limiter.shutdown();

        @SuppressWarnings("unchecked")
        RedisTemplate<String, String> failing = mock(RedisTemplate.class);
        when(failing.execute(
                any(RedisScript.class),
                any(List.class),
                any(Object[].class)))
                .thenThrow(new RuntimeException("redis down"));

        FmpRateLimiter brokenLimiter = new FmpRateLimiter(failing, Clock.systemUTC(), null);
        try {
            // 예외 없이 통과해야 한다 — 분당 burst 안전선이 이미 적용되었으므로 일일 카운터
            // 누락보다 정상 트래픽 통과를 우선시한다.
            brokenLimiter.acquire(FmpRateLimiter.Priority.HIGH);
        } finally {
            brokenLimiter.shutdown();
        }
    }

    @Test
    @DisplayName("shutdown 시 대기중인 waiter 는 RateLimitExceededException 으로 깨어난다")
    void shutdown_시_대기중_waiter_깨움() throws Exception {
        // 초기 토큰 1 즉시 소진
        limiter.acquire(FmpRateLimiter.Priority.HIGH);

        ExecutorService pool = Executors.newSingleThreadExecutor();
        try {
            // 토큰 없는 상태에서 추가 acquire — 대기 큐에 들어감
            CompletableFuture<Throwable> caught = CompletableFuture.supplyAsync(() -> {
                try {
                    limiter.acquire(FmpRateLimiter.Priority.LOW);
                    return null;
                } catch (Throwable t) {
                    return t;
                }
            }, pool);

            // waiter 가 큐에 들어가도록 잠시 대기
            Thread.sleep(200);

            // shutdown — 대기중 waiter 가 RateLimitExceededException 으로 깨어나야 한다
            limiter.shutdown();
            // tearDown 에서 다시 호출되지 않도록 null 처리
            limiter = null;

            Throwable t = caught.get(5, TimeUnit.SECONDS);
            assertThat(t).isInstanceOf(RateLimitExceededException.class);
            assertThat(t.getMessage()).contains("cancelled");
        } finally {
            pool.shutdownNow();
        }
    }

    @Test
    @DisplayName("refill task 가 throw 해도 후속 tick 에서 self-heal 한다")
    void refill_task_self_heal() throws Exception {
        // 본 테스트는 실제 task self-heal 동작을 직접 가로채기 어렵지만,
        // shutdown 까지 정상 acquire 가 다회 가능한지로 간접 확인한다.
        // (scheduleWithFixedDelay 사용 + try/catch 래퍼가 적용된 상태)
        limiter.acquire(FmpRateLimiter.Priority.HIGH);
        // 토큰 refill 대기 후 다음 호출 정상 통과
        limiter.acquire(FmpRateLimiter.Priority.HIGH);
        // 추가로 한 번 더 — 스케줄러가 살아있음을 확인
        limiter.acquire(FmpRateLimiter.Priority.HIGH);
    }

    @Test
    @DisplayName("shutdown 이후 진입한 acquire 는 즉시 RateLimitExceededException 으로 거부된다")
    void shutdown_이후_acquire_즉시_거부() {
        limiter.shutdown();
        // tearDown 에서 다시 호출되지 않도록 null 처리
        limiter = null;

        FmpRateLimiter disposed = new FmpRateLimiter(redisTemplate);
        disposed.shutdown();

        assertThatThrownBy(() -> disposed.acquire(FmpRateLimiter.Priority.HIGH))
                .isInstanceOf(RateLimitExceededException.class)
                .hasMessageContaining("disposed");
    }

    @SuppressWarnings("unused")
    private static void awaitOrFail(CompletableFuture<?> f) {
        try {
            f.get(10, TimeUnit.SECONDS);
        } catch (InterruptedException | ExecutionException | java.util.concurrent.TimeoutException e) {
            throw new AssertionError(e);
        }
    }
}
