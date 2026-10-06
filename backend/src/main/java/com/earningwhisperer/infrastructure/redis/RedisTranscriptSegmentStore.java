package com.earningwhisperer.infrastructure.redis;

import com.earningwhisperer.domain.transcript.TranscriptSegment;
import com.earningwhisperer.domain.transcript.TranscriptSegmentStore;
import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.ObjectMapper;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.stereotype.Repository;

import java.io.UncheckedIOException;
import java.time.Duration;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.List;

/**
 * Redis LIST 기반 세그먼트 저장소.
 *
 * 키 구조:
 *   transcript:segments:{callId} → TranscriptSegment JSON 목록 (추가할 때마다 TTL 갱신)
 *
 * 레지스트리가 sequence 단조성을 보장한 뒤에만 append 되므로 목록은 대체로 정렬되어 있지만,
 * 조회 시 한 번 더 정렬해 순서를 보장한다.
 */
@Slf4j
@Repository
public class RedisTranscriptSegmentStore implements TranscriptSegmentStore {

    private static final String KEY_PREFIX = "transcript:segments:";

    private final StringRedisTemplate redisTemplate;
    private final ObjectMapper objectMapper;
    private final Duration ttl;

    public RedisTranscriptSegmentStore(
            StringRedisTemplate redisTemplate,
            ObjectMapper objectMapper,
            @Value("${app.assistant.segment-ttl-hours:48}") long ttlHours) {
        this.redisTemplate = redisTemplate;
        this.objectMapper = objectMapper;
        this.ttl = Duration.ofHours(ttlHours);
    }

    @Override
    public void append(TranscriptSegment segment) {
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
