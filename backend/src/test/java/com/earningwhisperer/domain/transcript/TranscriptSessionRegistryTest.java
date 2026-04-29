package com.earningwhisperer.domain.transcript;

import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicInteger;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * TranscriptSessionRegistry 단위 테스트.
 *
 * 검증 포인트:
 *   1) 단조 증가 sequence 허용 (OK)
 *   2) 동일 sequence 재인입 거부 (SEQ_REGRESS)
 *   3) 더 작은 sequence 재인입 거부 (SEQ_REGRESS)
 *   4) is_session_end=true 이후 동일 callId 재인입 거부 (SESSION_ENDED)
 *   5) call_id 격리 — 한 콜의 종료가 다른 콜에 영향 없음
 *   6) 동시성 — 같은 callId 다중 스레드 인입 시 단 한 번만 OK 수가 sequence 종 수와 일치
 */
@DisplayName("TranscriptSessionRegistry 단위 테스트")
class TranscriptSessionRegistryTest {

    private static TranscriptSegment seg(String callId, int sequence, boolean isSessionEnd) {
        return new TranscriptSegment(
                "NVDA", callId, sequence, sequence * 1000L, sequence * 1000L + 500,
                "hello world", null, 1745000000L + sequence, isSessionEnd);
    }

    @Test
    @DisplayName("단조 증가 sequence 는 OK 로 모두 허용된다")
    void 단조_증가_허용() {
        TranscriptSessionRegistry registry = new TranscriptSessionRegistry();

        assertThat(registry.validateAndAccept(seg("c1", 0, false))).isEqualTo(TranscriptSessionRegistry.Result.OK);
        assertThat(registry.validateAndAccept(seg("c1", 1, false))).isEqualTo(TranscriptSessionRegistry.Result.OK);
        assertThat(registry.validateAndAccept(seg("c1", 2, false))).isEqualTo(TranscriptSessionRegistry.Result.OK);
        assertThat(registry.validateAndAccept(seg("c1", 10, false))).isEqualTo(TranscriptSessionRegistry.Result.OK);
    }

    @Test
    @DisplayName("동일 sequence 재인입은 SEQ_REGRESS")
    void 동일_sequence_거부() {
        TranscriptSessionRegistry registry = new TranscriptSessionRegistry();

        assertThat(registry.validateAndAccept(seg("c1", 5, false))).isEqualTo(TranscriptSessionRegistry.Result.OK);
        assertThat(registry.validateAndAccept(seg("c1", 5, false))).isEqualTo(TranscriptSessionRegistry.Result.SEQ_REGRESS);
    }

    @Test
    @DisplayName("이전보다 작은 sequence 재인입은 SEQ_REGRESS")
    void 역행_sequence_거부() {
        TranscriptSessionRegistry registry = new TranscriptSessionRegistry();

        registry.validateAndAccept(seg("c1", 5, false));
        assertThat(registry.validateAndAccept(seg("c1", 4, false))).isEqualTo(TranscriptSessionRegistry.Result.SEQ_REGRESS);
        assertThat(registry.validateAndAccept(seg("c1", 0, false))).isEqualTo(TranscriptSessionRegistry.Result.SEQ_REGRESS);
    }

    @Test
    @DisplayName("is_session_end=true 처리 후 동일 callId 재인입은 SESSION_ENDED")
    void 세션_종료_후_재인입_거부() {
        TranscriptSessionRegistry registry = new TranscriptSessionRegistry();

        assertThat(registry.validateAndAccept(seg("c1", 0, false))).isEqualTo(TranscriptSessionRegistry.Result.OK);
        assertThat(registry.validateAndAccept(seg("c1", 1, true))).isEqualTo(TranscriptSessionRegistry.Result.OK);
        // 종료 후엔 어떤 sequence 라도 거부
        assertThat(registry.validateAndAccept(seg("c1", 2, false))).isEqualTo(TranscriptSessionRegistry.Result.SESSION_ENDED);
        assertThat(registry.validateAndAccept(seg("c1", 100, false))).isEqualTo(TranscriptSessionRegistry.Result.SESSION_ENDED);
        assertThat(registry.validateAndAccept(seg("c1", 100, true))).isEqualTo(TranscriptSessionRegistry.Result.SESSION_ENDED);
    }

    @Test
    @DisplayName("call_id 간 격리 — 한 콜 종료/단조성이 다른 콜에 영향 없음")
    void callId_격리() {
        TranscriptSessionRegistry registry = new TranscriptSessionRegistry();

        // c1 종료
        registry.validateAndAccept(seg("c1", 0, true));
        // c2 는 0부터 정상 시작 가능
        assertThat(registry.validateAndAccept(seg("c2", 0, false))).isEqualTo(TranscriptSessionRegistry.Result.OK);
        assertThat(registry.validateAndAccept(seg("c2", 1, false))).isEqualTo(TranscriptSessionRegistry.Result.OK);
        // c1 은 여전히 종료 상태
        assertThat(registry.validateAndAccept(seg("c1", 100, false))).isEqualTo(TranscriptSessionRegistry.Result.SESSION_ENDED);
    }

    @Test
    @DisplayName("동시성 — 같은 callId 에 동일 sequence 다중 스레드 인입 시 정확히 1건만 OK")
    void 동시성_단일_OK() throws InterruptedException {
        TranscriptSessionRegistry registry = new TranscriptSessionRegistry();
        int threads = 32;
        ExecutorService pool = Executors.newFixedThreadPool(threads);
        CountDownLatch ready = new CountDownLatch(threads);
        CountDownLatch start = new CountDownLatch(1);
        AtomicInteger okCount = new AtomicInteger();
        AtomicInteger regressCount = new AtomicInteger();

        for (int i = 0; i < threads; i++) {
            pool.submit(() -> {
                ready.countDown();
                try {
                    start.await();
                } catch (InterruptedException e) {
                    Thread.currentThread().interrupt();
                    return;
                }
                TranscriptSessionRegistry.Result r = registry.validateAndAccept(seg("c1", 7, false));
                if (r == TranscriptSessionRegistry.Result.OK) okCount.incrementAndGet();
                else if (r == TranscriptSessionRegistry.Result.SEQ_REGRESS) regressCount.incrementAndGet();
            });
        }

        ready.await(2, TimeUnit.SECONDS);
        start.countDown();
        pool.shutdown();
        assertThat(pool.awaitTermination(5, TimeUnit.SECONDS)).isTrue();

        // 정확히 1건만 OK, 나머지는 모두 SEQ_REGRESS
        assertThat(okCount.get()).isEqualTo(1);
        assertThat(regressCount.get()).isEqualTo(threads - 1);
    }

    @Test
    @DisplayName("동시성 — 서로 다른 callId 다중 스레드 인입은 모두 OK")
    void 동시성_callId_격리_모두_OK() throws InterruptedException {
        TranscriptSessionRegistry registry = new TranscriptSessionRegistry();
        int threads = 32;
        ExecutorService pool = Executors.newFixedThreadPool(threads);
        CountDownLatch start = new CountDownLatch(1);
        ConcurrentHashMap<String, TranscriptSessionRegistry.Result> results = new ConcurrentHashMap<>();

        for (int i = 0; i < threads; i++) {
            String callId = "call-" + i;
            pool.submit(() -> {
                try {
                    start.await();
                } catch (InterruptedException e) {
                    Thread.currentThread().interrupt();
                    return;
                }
                results.put(callId, registry.validateAndAccept(seg(callId, 0, false)));
            });
        }

        start.countDown();
        pool.shutdown();
        assertThat(pool.awaitTermination(5, TimeUnit.SECONDS)).isTrue();

        assertThat(results).hasSize(threads);
        assertThat(results.values()).allMatch(r -> r == TranscriptSessionRegistry.Result.OK);
    }
}
