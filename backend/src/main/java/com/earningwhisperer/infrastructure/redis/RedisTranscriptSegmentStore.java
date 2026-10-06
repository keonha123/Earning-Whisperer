package com.earningwhisperer.infrastructure.redis;

import com.earningwhisperer.domain.transcript.TranscriptSegment;
import com.earningwhisperer.domain.transcript.TranscriptSegmentStore;
import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.ObjectMapper;
import jakarta.annotation.PreDestroy;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.stereotype.Repository;

import java.io.UncheckedIOException;
import java.time.Duration;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.List;
import java.util.concurrent.ArrayBlockingQueue;
import java.util.concurrent.Executor;
import java.util.concurrent.RejectedExecutionException;
import java.util.concurrent.ThreadPoolExecutor;
import java.util.concurrent.TimeUnit;

/**
 * Redis LIST 기반 세그먼트 저장소.
 *
 * 키 구조:
 *   transcript:segments:{callId} → TranscriptSegment JSON 목록 (추가할 때마다 TTL 갱신)
 *
 * 레지스트리가 sequence 단조성을 보장한 뒤에만 append 되므로 목록은 대체로 정렬되어 있지만,
 * 조회 시 한 번 더 정렬해 순서를 보장한다.
 *
 * <p>append 는 인입·발행 경로에서 동기로 불리는데 Redis 가 응답하지 않으면 Lettuce 기본 타임아웃(60초)만큼 멈춘다.
 * 그래서 전용 단일 스레드 + 유한 큐(용량 {@value #QUEUE_CAPACITY})로 넘기고 바로 돌아온다. 큐가 차면 그 세그먼트는
 * 버리고 경고만 남긴다(근거 보관은 부가 기능이라 인입·발행·번역에 영향을 주지 않는다). 단일 스레드라 같은 콜의 순서는 유지된다.
 */
@Slf4j
@Repository
public class RedisTranscriptSegmentStore implements TranscriptSegmentStore {

    private static final String KEY_PREFIX = "transcript:segments:";
    static final int QUEUE_CAPACITY = 1000;

    private final StringRedisTemplate redisTemplate;
    private final ObjectMapper objectMapper;
    private final Duration ttl;
    private final Executor worker;
    private final ThreadPoolExecutor owned;

    @Autowired
    public RedisTranscriptSegmentStore(
            StringRedisTemplate redisTemplate,
            ObjectMapper objectMapper,
            @Value("${app.assistant.segment-ttl-hours:48}") long ttlHours) {
        this(redisTemplate, objectMapper, ttlHours, QUEUE_CAPACITY);
    }

    /** 테스트용. 큐 용량을 지정해 전용 스레드로 돌린다. */
    RedisTranscriptSegmentStore(StringRedisTemplate redisTemplate, ObjectMapper objectMapper, long ttlHours,
                                int queueCapacity) {
        this.redisTemplate = redisTemplate;
        this.objectMapper = objectMapper;
        this.ttl = Duration.ofHours(ttlHours);
        this.owned = new ThreadPoolExecutor(1, 1, 0L, TimeUnit.MILLISECONDS,
                new ArrayBlockingQueue<>(queueCapacity), r -> {
                    Thread t = new Thread(r, "transcript-segment-store");
                    t.setDaemon(true);
                    return t;
                });
        this.worker = owned;
    }

    /** 테스트용. 주어진 executor 로 append 를 돌린다(동기 executor 를 넣으면 호출 스레드에서 실행). */
    RedisTranscriptSegmentStore(StringRedisTemplate redisTemplate, ObjectMapper objectMapper, long ttlHours,
                                Executor worker) {
        this.redisTemplate = redisTemplate;
        this.objectMapper = objectMapper;
        this.ttl = Duration.ofHours(ttlHours);
        this.owned = null;
        this.worker = worker;
    }

    @Override
    public void append(TranscriptSegment segment) {
        try {
            worker.execute(() -> write(segment));
        } catch (RejectedExecutionException e) {
            log.warn("[TranscriptStore] 저장 대기열이 가득 차 세그먼트를 버림 - callId={} sequence={}",
                    segment.callId(), segment.sequence());
        }
    }

    @PreDestroy
    void shutdown() {
        if (owned != null) {
            owned.shutdownNow();
        }
    }

    private void write(TranscriptSegment segment) {
        try {
            doAppend(segment);
        } catch (RuntimeException e) {
            log.warn("[TranscriptStore] 세그먼트 저장 실패 - callId={} sequence={}",
                    segment.callId(), segment.sequence(), e);
        }
    }

    private void doAppend(TranscriptSegment segment) {
        String key = KEY_PREFIX + segment.callId();
        redisTemplate.opsForList().rightPush(key, toJson(segment));
        redisTemplate.expire(key, ttl);
    }

    @Override
    public List<TranscriptSegment> findUntil(String callId, int untilSequence) {
        List<String> raw = redisTemplate.opsForList().range(KEY_PREFIX + callId, 0, -1);
        if (raw == null || raw.isEmpty()) {
            return List.of();
        }
        List<TranscriptSegment> segments = new ArrayList<>(raw.size());
        for (String json : raw) {
            try {
                TranscriptSegment segment = objectMapper.readValue(json, TranscriptSegment.class);
                if (segment.sequence() <= untilSequence) {
                    segments.add(segment);
                }
            } catch (JsonProcessingException e) {
                log.warn("[TranscriptStore] 깨진 세그먼트 항목을 건너뜀 - callId={}", callId);
            }
        }
        segments.sort(Comparator.comparingInt(TranscriptSegment::sequence));
        return segments;
    }

    private String toJson(TranscriptSegment segment) {
        try {
            return objectMapper.writeValueAsString(segment);
        } catch (JsonProcessingException e) {
            throw new UncheckedIOException(e);
        }
    }
}
