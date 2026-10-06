package com.earningwhisperer.infrastructure.redis;

import com.earningwhisperer.domain.transcript.TranscriptSegment;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.data.redis.core.ListOperations;
import org.springframework.data.redis.core.StringRedisTemplate;

import java.time.Duration;
import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

@ExtendWith(MockitoExtension.class)
@DisplayName("RedisTranscriptSegmentStore")
class RedisTranscriptSegmentStoreTest {

    @Mock StringRedisTemplate redisTemplate;
    @Mock ListOperations<String, String> listOps;

    private final ObjectMapper objectMapper = new ObjectMapper();
    private RedisTranscriptSegmentStore store;

    @BeforeEach
    void setUp() {
        store = new RedisTranscriptSegmentStore(redisTemplate, objectMapper, 48);
    }

    private static TranscriptSegment segment(int sequence) {
        return new TranscriptSegment("WMT", "call-1", sequence, sequence * 6000L, sequence * 6000L + 5000,
                "Comp sales were 2.6%.", "CEO", 1_787_227_200L + sequence * 6L, false);
    }

    @Test
    @DisplayName("콜 단위 키에 JSON 으로 추가하고 TTL 을 갱신한다")
    void append() throws Exception {
        when(redisTemplate.opsForList()).thenReturn(listOps);

        store.append(segment(3));

        verify(listOps).rightPush("transcript:segments:call-1", objectMapper.writeValueAsString(segment(3)));
        verify(redisTemplate).expire("transcript:segments:call-1", Duration.ofHours(48));
    }

    @Test
    @DisplayName("until_sequence 이하만 sequence 순서로 돌려준다")
    void findUntil() throws Exception {
        when(redisTemplate.opsForList()).thenReturn(listOps);
        when(listOps.range("transcript:segments:call-1", 0, -1)).thenReturn(List.of(
                objectMapper.writeValueAsString(segment(0)),
                objectMapper.writeValueAsString(segment(2)),
                objectMapper.writeValueAsString(segment(1)),
                objectMapper.writeValueAsString(segment(3))));

        List<TranscriptSegment> found = store.findUntil("call-1", 2);

        assertThat(found).extracting(TranscriptSegment::sequence).containsExactly(0, 1, 2);
        assertThat(found.get(0)).isEqualTo(segment(0));
    }

    @Test
    @DisplayName("저장된 것이 없으면 빈 목록")
    void findUntil_empty() {
        when(redisTemplate.opsForList()).thenReturn(listOps);
        when(listOps.range(anyString(), org.mockito.ArgumentMatchers.eq(0L), org.mockito.ArgumentMatchers.eq(-1L)))
                .thenReturn(null);

        assertThat(store.findUntil("none", 10)).isEmpty();
    }

    @Test
    @DisplayName("깨진 항목은 건너뛴다")
    void findUntil_skipsMalformed() throws Exception {
        when(redisTemplate.opsForList()).thenReturn(listOps);
        when(listOps.range("transcript:segments:call-1", 0, -1)).thenReturn(List.of(
                "{not json", objectMapper.writeValueAsString(segment(1))));

        assertThat(store.findUntil("call-1", 5)).extracting(TranscriptSegment::sequence).containsExactly(1);
    }
}
