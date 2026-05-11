package com.earningwhisperer.infrastructure.fmp;

import jakarta.annotation.PreDestroy;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.autoconfigure.condition.ConditionalOnExpression;
import org.springframework.data.redis.core.RedisTemplate;
import org.springframework.data.redis.core.script.DefaultRedisScript;
import org.springframework.data.redis.core.script.RedisScript;
import org.springframework.stereotype.Component;

import java.time.Clock;
import java.time.LocalDate;
import java.time.ZoneOffset;
import java.time.format.DateTimeFormatter;
import java.util.ArrayDeque;
import java.util.Collections;
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

    /**
     * INCR + (첫 호출 시) EXPIRE 를 atomic 하게 수행하는 Lua script.
     *
     * <p>분리된 INCR/EXPIRE 호출은 자정 롤오버 직전 race 가 가능하다 — INCR 직후 다른 worker 가
     * 같은 키를 EXPIRE 갱신해버리면 어제 카운트가 25시간 동안 누적될 수 있다. Lua 는 단일 명령
     * 단위로 실행되므로 둘이 atomic 하게 묶인다.
     *
     * <p>스크립트는 새 카운터 값(Long)을 반환한다.
     */
    private static final String INCR_AND_EXPIRE_LUA =
            "local v = redis.call('INCR', KEYS[1]) " +
            "if v == 1 then " +
            "  redis.call('EXPIRE', KEYS[1], ARGV[1]) " +
            "end " +
            "return v";

    /** Spring Data Redis 가 권장하는 사전 컴파일 RedisScript 인스턴스. */
    private static final RedisScript<Long> INCR_AND_EXPIRE_SCRIPT =
            new DefaultRedisScript<>(INCR_AND_EXPIRE_LUA, Long.class);

    public enum Priority { HIGH, LOW }

    private final RedisTemplate<String, String> redisTemplate;
    private final Clock clock;
    private final ScheduledExecutorService scheduler;
    private final boolean ownsScheduler;

    private final Object lock = new Object();
    private double tokens = BUCKET_CAPACITY;
    private final Deque<CompletableFuture<Void>> hi = new ArrayDeque<>();
    private final Deque<CompletableFuture<Void>> lo = new ArrayDeque<>();

    /** shutdown() 이후 새 acquire 호출은 즉시 거부. waiter 영구 블록 회피. */
    private volatile boolean disposed = false;

    private final ScheduledFuture<?> refillTask;

    @Autowired
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
        // scheduleWithFixedDelay + try/catch 래퍼: refill task 가 unchecked exception 을 던져도
        // 스케줄러가 영구 멈추지 않도록 self-heal 한다. scheduleAtFixedRate 는 task 가 throw 하면
        // 향후 모든 실행이 중단된다 (Java doc 명시).
        this.refillTask = this.scheduler.scheduleWithFixedDelay(
                this::safeRefillAndDrain,
                REFILL_INTERVAL_MS,
                REFILL_INTERVAL_MS,
                TimeUnit.MILLISECONDS
        );
    }

    /**
     * refill task 의 self-heal 래퍼 — Exception 은 격리하고 다음 tick 진행.
     * Error (OOM/StackOverflow 등) 는 의도적으로 catch 하지 않는다 — JVM 이 빨리 죽어야 할 상황을
     * 100ms 마다 좀비 로그로 도배할 위험을 회피.
     */
    private void safeRefillAndDrain() {
        try {
            refillAndDrain();
        } catch (Exception e) {
            log.error("[FmpRateLimiter] refill task error (continuing)", e);
        }
    }

    /**
     * 토큰을 획득한다. 토큰 버킷이 비어있으면 우선순위 큐에 등록하고 대기(blocking).
     *
     * @throws RateLimitExceededException 일일 한도 초과 시
     */
    public void acquire(Priority priority) throws RateLimitExceededException {
        // shutdown 이후 진입한 acquire 는 큐에 등록되더라도 refill task 가 cancel 되어 깨어나지
        // 못한다 → 영구 블록. dispose 플래그로 즉시 거부하여 race 회피.
        if (disposed) {
            throw new RateLimitExceededException("FmpRateLimiter disposed");
        }
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

        // 일일 한도 검사 — Redis Lua atomic INCR + EXPIRE.
        // INCR 와 EXPIRE 를 별도 명령으로 보내면 자정 롤오버 직전 race 에서 EXPIRE 가 갱신되지 않아
        // 이미 만료된 어제 키에 카운트가 25시간 누적될 수 있다. Lua 로 둘을 atomic 하게 묶는다.
        String key = dailyKey();
        Long current;
        try {
            current = redisTemplate.execute(
                    INCR_AND_EXPIRE_SCRIPT,
                    Collections.singletonList(key),
                    String.valueOf(DAILY_TTL_SECONDS)
            );
        } catch (RuntimeException e) {
            // Redis 장애 시에도 호출 자체는 진행 — 분당 burst 안전선(in-process 토큰 버킷)이 이미
            // 적용되어 있어 폭주 위험이 낮고, 일일 카운터 누락보다 정상 트래픽 차단이 더 큰 손해다.
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
        // 플래그를 먼저 set 하여 이후 acquire 호출이 즉시 거부되도록 한다.
        disposed = true;
        if (refillTask != null) {
            refillTask.cancel(false);
        }
        if (ownsScheduler) {
            scheduler.shutdownNow();
        }
        // 대기 중인 모든 future 들을 cancel — 메모리 누수 + 데드락 방지
        synchronized (lock) {
            RuntimeException err = new RateLimitExceededException("FmpRateLimiter disposed");
            drainAndComplete(hi, err);
            drainAndComplete(lo, err);
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
