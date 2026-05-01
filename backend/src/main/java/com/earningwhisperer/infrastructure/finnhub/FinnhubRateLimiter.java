package com.earningwhisperer.infrastructure.finnhub;

import jakarta.annotation.PreDestroy;
import lombok.extern.slf4j.Slf4j;
import org.springframework.boot.autoconfigure.condition.ConditionalOnExpression;
import org.springframework.stereotype.Component;

import java.util.ArrayDeque;
import java.util.Deque;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.ExecutionException;
import java.util.concurrent.Executors;
import java.util.concurrent.ScheduledExecutorService;
import java.util.concurrent.ScheduledFuture;
import java.util.concurrent.TimeUnit;

/**
 * Finnhub 외부 호출 rate limiter.
 *
 * <p>Finnhub 무료 티어는 분당 60 calls 제한이 있고 명시적 일일 한도는 없다. 따라서 본 limiter 는
 * <b>분당 burst 제어 (in-process 토큰 버킷)</b> 만 담당한다.
 * <ul>
 *     <li>capacity 1.0, 100ms 마다 0.05 token refill → 0.5 req/s 안전선 (분당 30, 한도 60 의 절반)</li>
 *     <li>HIGH 우선순위 큐가 LOW 보다 항상 먼저 drain</li>
 * </ul>
 *
 * <p>FMP 와 달리 Redis 일일 카운터는 사용하지 않는다. 분당 60 한도를 안전선 0.5 req/s 으로 이미
 * 넉넉히 보호하며, 일일 한도가 따로 명시되지 않기 때문이다.
 *
 * <p>{@link #acquire(Priority)} 는 정상 경로에서는 토큰 보충을 단순히 await 한다. burst 거부로
 * exception 을 던지지 않으며, dispose / interrupt 등 비정상 종료 시에만
 * {@link FinnhubRateLimitExceededException} 을 throw 한다. 분당 한도 초과로 외부에서 429 가
 * 떨어지는 경우는 {@link FinnhubClient} 측에서 RestClientException 으로 받아 빈 결과 + WARN 처리.
 *
 * <p>FINNHUB_API_KEY 미설정 시 Bean 미등록(@ConditionalOnExpression).
 */
@Component
@ConditionalOnExpression("!'${finnhub.api-key:}'.isBlank()")
@Slf4j
public class FinnhubRateLimiter {

    /** 토큰 버킷 capacity (burst 허용 적게). */
    static final double BUCKET_CAPACITY = 1.0;

    /** 100ms 당 추가될 토큰 수 → 0.5 req/s. */
    static final double REFILL_PER_TICK = 0.05;

    /** Refill scheduler 주기 (ms). */
    static final long REFILL_INTERVAL_MS = 100L;

    /** 부동소수점 누적 오차 보정 epsilon. */
    private static final double TOKEN_EPSILON = 1e-9;

    public enum Priority { HIGH, LOW }

    private final ScheduledExecutorService scheduler;
    private final boolean ownsScheduler;

    private final Object lock = new Object();
    private double tokens = BUCKET_CAPACITY;
    private final Deque<CompletableFuture<Void>> hi = new ArrayDeque<>();
    private final Deque<CompletableFuture<Void>> lo = new ArrayDeque<>();

    private final ScheduledFuture<?> refillTask;

    public FinnhubRateLimiter() {
        this(null);
    }

    /**
     * 테스트용 생성자. scheduler 가 null 이면 내부 단일 스레드 scheduler 를 생성한다.
     */
    FinnhubRateLimiter(ScheduledExecutorService scheduler) {
        if (scheduler == null) {
            this.scheduler = Executors.newSingleThreadScheduledExecutor(r -> {
                Thread t = new Thread(r, "finnhub-rate-limiter");
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
     * <p>정상 경로에서는 예외를 던지지 않는다. shutdown / interrupt 등 비정상 종료 시에만
     * {@link FinnhubRateLimitExceededException} 을 throw.
     */
    public void acquire(Priority priority) {
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
            throw new FinnhubRateLimitExceededException("Finnhub rate limiter wait interrupted", e);
        } catch (ExecutionException e) {
            // dispose() 등으로 cancel 된 경우
            throw new FinnhubRateLimitExceededException("Finnhub rate limiter cancelled", e.getCause());
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
            RuntimeException disposed = new FinnhubRateLimitExceededException("FinnhubRateLimiter disposed");
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
}
