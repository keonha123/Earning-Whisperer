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

import java.time.Clock;
import java.util.ArrayList;
import java.util.List;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.concurrent.atomic.AtomicLong;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyLong;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.lenient;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

/**
 * FmpRateLimiter 단위 테스트.
 *
 * <p>실제 ScheduledExecutorService 와 in-process 시계를 사용하므로 약간의 sleep 이 포함된다.
 * Redis 는 mockito 로 stub.
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

    @BeforeEach
    void setUp() {
        // ValueOperations stub — INCR 시 in-memory counter 증가, DECR 시 감소
        lenient().when(redisTemplate.opsForValue()).thenReturn(valueOps);
        lenient().when(valueOps.increment(anyString())).thenAnswer(inv -> counter.incrementAndGet());
        lenient().when(valueOps.decrement(anyString())).thenAnswer(inv -> counter.decrementAndGet());
        lenient().when(valueOps.get(anyString())).thenAnswer(inv -> String.valueOf(counter.get()));
        lenient().when(redisTemplate.expire(anyString(), anyLong(), any(TimeUnit.class))).thenReturn(true);

        limiter = new FmpRateLimiter(redisTemplate, Clock.systemUTC(), null);
    }

    @AfterEach
    void tearDown() {
        limiter.shutdown();
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
    @DisplayName("첫 INCR 시 EXPIRE 가 호출된다 (TTL 설정)")
    void 첫_INCR_시_EXPIRE_호출() {
        // counter 0 → INCR 결과 1 → EXPIRE 호출 트리거
        AtomicInteger expireCalls = new AtomicInteger(0);
        when(redisTemplate.expire(anyString(), eq(FmpRateLimiter.DAILY_TTL_SECONDS), eq(TimeUnit.SECONDS)))
                .thenAnswer(inv -> {
                    expireCalls.incrementAndGet();
                    return true;
                });

        limiter.acquire(FmpRateLimiter.Priority.HIGH);
        assertThat(expireCalls.get()).isEqualTo(1);

        // 두 번째 호출 (counter=2) 은 EXPIRE 호출 없음
        // 단, 토큰 refill 대기 필요 — burst 후 약 2초 대기
        limiter.acquire(FmpRateLimiter.Priority.HIGH);
        assertThat(expireCalls.get()).isEqualTo(1);
    }
}
