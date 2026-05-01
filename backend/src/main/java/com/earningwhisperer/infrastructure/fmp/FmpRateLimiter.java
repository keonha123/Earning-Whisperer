package com.earningwhisperer.infrastructure.fmp;

import jakarta.annotation.PreDestroy;
import lombok.extern.slf4j.Slf4j;
import org.springframework.boot.autoconfigure.condition.ConditionalOnExpression;
import org.springframework.data.redis.core.RedisTemplate;
import org.springframework.stereotype.Component;

import java.time.Clock;
import java.time.LocalDate;
import java.time.ZoneOffset;
import java.time.format.DateTimeFormatter;
import java.util.ArrayDeque;
import java.util.Deque;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.ExecutionException;
import java.util.concurrent.Executors;
import java.util.concurrent.ScheduledExecutorService;
import java.util.concurrent.ScheduledFuture;
import java.util.concurrent.TimeUnit;

/**
 * FMP 외부 호출 rate limiter.
 *
 * <p>두 단계로 호출을 제어한다.
 * <ol>
 *     <li><b>분당 burst 제어 (in-process 토큰 버킷):</b> capacity 1.0, 100ms 마다 0.05 token refill
 *         → 0.5 req/s 안전선. HIGH 우선순위 큐가 LOW 보다 항상 먼저 drain 된다.</li>
 *     <li><b>일일 한도 (Redis 카운터):</b> 키 {@code fmp:rate:daily:{yyyyMMdd}} (UTC 일자) INCR.
 *         결과가 {@link #DAILY_LIMIT} 이상이면 DECR 롤백 후 {@link RateLimitExceededException} throw.</li>
 * </ol>
 *
 * <p>분당 한도는 단일 인스턴스 가정(in-process). 멀티 인스턴스 배포 시에도 일일 한도는 Redis 로 보호된다.
 *
 * <p>FMP_API_KEY 미설정 시 Bean 미등록(@ConditionalOnExpression).
 */
@Component
@ConditionalOnExpression("!'${fmp.api-key:}'.isBlank()")
@Slf4j
public class FmpRateLimiter {

    /** FMP 무료 티어 일일 한도 250 - 안전마진 10. */
    static final int DAILY_LIMIT = 240;

    /** Redis 카운터 TTL — 25시간(자정 롤오버 + 1시간 버퍼). */
    static final long DAILY_TTL_SECONDS = 90_000L;

    /** 토큰 버킷 capacity (burst 허용 적게). */
    static final double BUCKET_CAPACITY = 1.0;

    /** 100ms 당 추가될 토큰 수 → 0.5 req/s. */
    static final double REFILL_PER_TICK = 0.05;

    /** Refill scheduler 주기 (ms). */
    static final long REFILL_INTERVAL_MS = 100L;

    /** 부동소수점 누적 오차 보정 epsilon. */
    private static final double TOKEN_EPSILON = 1e-9;

    /** Redis 키 일자 포맷 (UTC). */
    private static final DateTimeFormatter DAILY_KEY_FMT = DateTimeFormatter.ofPattern("yyyyMMdd");

    public enum Priority { HIGH, LOW }

    private final RedisTemplate<String, String> redisTemplate;
    private final Clock clock;
    private final ScheduledExecutorService scheduler;
    private final boolean ownsScheduler;

    private final Object lock = new Object();
    private double tokens = BUCKET_CAPACITY;
    private final Deque<CompletableFuture<Void>> hi = new ArrayDeque<>();
    private final Deque<CompletableFuture<Void>> lo = new ArrayDeque<>();

    private final ScheduledFuture<?> refillTask;

    public FmpRateLimiter(RedisTemplate<String, String> redisTemplate) {
        this(redisTemplate, Clock.systemUTC(), null);
    }

    /**
     * 테스트용 생성자. scheduler 가 null 이면 내부 단일 스레드 scheduler 를 생성한다.
     */
    FmpRateLimiter(RedisTemplate<String, String> redisTemplate,
                   Clock clock,
                   ScheduledExecutorService scheduler) {
        this.redisTemplate = redisTemplate;
        this.clock = clock;
        if (scheduler == null) {
            this.scheduler = Executors.newSingleThreadScheduledExecutor(r -> {
                Thread t = new Thread(r, "fmp-rate-limiter");
                t.setDaemon(true);
                return t;
            });
            this.ownsScheduler = true;
        } else {
            this.scheduler = scheduler;
            this.ownsScheduler = false;
        }
        this.refillTask = this.scheduler.scheduleAtFixedRate(
                this::refillAndDrain,
                REFILL_INTERVAL_MS,
                REFILL_INTERVAL_MS,
                TimeUnit.MILLISECONDS
        );
    }

    /**
     * 토큰을 획득한다. 토큰 버킷이 비어있으면 우선순위 큐에 등록하고 대기(blocking).
     *
     * @throws RateLimitExceededException 일일 한도 초과 시
     */
    public void acquire(Priority priority) throws RateLimitExceededException {
        CompletableFuture<Void> waiter = new CompletableFuture<>();
        synchronized (lock) {
            (priority == Priority.HIGH ? hi : lo).addLast(waiter);
        }
        // drain 시도 — 이미 토큰이 있으면 즉시 resolve
        refillAndDrain();

        try {
            waiter.get();
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
            // 큐에 남아있을 수 있으니 제거 (이미 resolved 라면 no-op)
            removeWaiter(waiter);
            throw new RateLimitExceededException("FMP rate limiter wait interrupted", e);
        } catch (ExecutionException e) {
            // dispose() 등으로 cancel 된 경우
            throw new RateLimitExceededException("FMP rate limiter cancelled", e.getCause());
        }

        // 일일 한도 검사 — Redis INCR
        String key = dailyKey();
        Long current;
        try {
            current = redisTemplate.opsForValue().increment(key);
            if (current != null && current == 1L) {
                redisTemplate.expire(key, DAILY_TTL_SECONDS, TimeUnit.SECONDS);
            }
        } catch (RuntimeException e) {
            // Redis 장애 시에도 호출 자체는 진행 (안전선이 분당 burst 로 이미 적용됨)
            log.warn("[FmpRateLimiter] Redis 카운터 INCR 실패, 일일 한도 검사 skip: {}", e.getMessage());
            return;
        }

        if (current != null && current > DAILY_LIMIT) {
            // 다른 호출자 영향 회피: 자신이 올린 1만 롤백
            try {
                redisTemplate.opsForValue().decrement(key);
            } catch (RuntimeException ex) {
                log.warn("[FmpRateLimiter] Redis 카운터 DECR 롤백 실패: {}", ex.getMessage());
            }
            throw new RateLimitExceededException(
                    "FMP daily quota exceeded: limit=" + DAILY_LIMIT + " current=" + current);
        }
    }

    /**
     * Redis 카운터 기준 남은 일일 quota. Redis 미연결/키 없음일 경우 {@link #DAILY_LIMIT}.
     */
    public int getRemainingDailyQuota() {
        try {
            String value = redisTemplate.opsForValue().get(dailyKey());
            if (value == null) return DAILY_LIMIT;
            int used = Integer.parseInt(value);
            return Math.max(0, DAILY_LIMIT - used);
        } catch (RuntimeException e) {
            // NumberFormatException 도 RuntimeException 서브클래스이므로 함께 캐치된다.
            log.warn("[FmpRateLimiter] Redis 카운터 조회 실패: {}", e.getMessage());
            return DAILY_LIMIT;
        }
    }

    @PreDestroy
    void shutdown() {
        if (refillTask != null) {
            refillTask.cancel(false);
        }
        if (ownsScheduler) {
            scheduler.shutdownNow();
        }
        // 대기 중인 모든 future 들을 cancel — 메모리 누수 + 데드락 방지
        synchronized (lock) {
            RuntimeException disposed = new RateLimitExceededException("FmpRateLimiter disposed");
            drainAndComplete(hi, disposed);
            drainAndComplete(lo, disposed);
        }
    }

    // ─────────── internal ───────────

    private void refillAndDrain() {
        synchronized (lock) {
            tokens = Math.min(BUCKET_CAPACITY, tokens + REFILL_PER_TICK);
            while (tokens >= 1.0 - TOKEN_EPSILON) {
                CompletableFuture<Void> next = pollNext();
                if (next == null) return;
                tokens -= 1.0;
                next.complete(null);
            }
        }
    }

    private CompletableFuture<Void> pollNext() {
        // HIGH 우선
        CompletableFuture<Void> next;
        while ((next = hi.pollFirst()) != null) {
            if (!next.isDone()) return next;
        }
        while ((next = lo.pollFirst()) != null) {
            if (!next.isDone()) return next;
        }
        return null;
    }

    private void removeWaiter(CompletableFuture<Void> waiter) {
        synchronized (lock) {
            hi.remove(waiter);
            lo.remove(waiter);
        }
    }

    private void drainAndComplete(Deque<CompletableFuture<Void>> q, RuntimeException err) {
        CompletableFuture<Void> w;
        while ((w = q.pollFirst()) != null) {
            w.completeExceptionally(err);
        }
    }

    private String dailyKey() {
        LocalDate today = LocalDate.now(clock.withZone(ZoneOffset.UTC));
        return "fmp:rate:daily:" + today.format(DAILY_KEY_FMT);
    }
}
