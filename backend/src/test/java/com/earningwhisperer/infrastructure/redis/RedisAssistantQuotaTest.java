package com.earningwhisperer.infrastructure.redis;

import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.data.redis.core.ValueOperations;

import java.time.Duration;
import java.time.LocalDate;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

@ExtendWith(MockitoExtension.class)
@DisplayName("RedisAssistantQuota")
class RedisAssistantQuotaTest {

    @Mock StringRedisTemplate redisTemplate;
    @Mock ValueOperations<String, String> valueOps;

    private RedisAssistantQuota quota;
    private static final LocalDate DAY = LocalDate.of(2026, 10, 7);
    private static final String DAILY_KEY = "assistant:daily:2026-10-07:7";

    @BeforeEach
    void setUp() {
        quota = new RedisAssistantQuota(redisTemplate);
    }

    @Test
    @DisplayName("첫 사용이면 키에 TTL 을 걸고 허용한다")
    void firstUseSetsTtl() {
        when(redisTemplate.opsForValue()).thenReturn(valueOps);
        when(valueOps.increment(DAILY_KEY)).thenReturn(1L);

        assertThat(quota.tryConsumeDaily(7L, DAY, 50)).isTrue();
        verify(redisTemplate).expire(DAILY_KEY, Duration.ofHours(48));
    }

    @Test
    @DisplayName("한도까지는 허용하고 넘으면 거부한다")
    void limit() {
        when(redisTemplate.opsForValue()).thenReturn(valueOps);
        when(valueOps.increment(DAILY_KEY)).thenReturn(50L, 51L);

        assertThat(quota.tryConsumeDaily(7L, DAY, 50)).isTrue();
        assertThat(quota.tryConsumeDaily(7L, DAY, 50)).isFalse();
        verify(redisTemplate, never()).expire(anyString(), org.mockito.ArgumentMatchers.any(Duration.class));
    }

    @Test
    @DisplayName("잠금은 SET NX 로 잡고 이미 있으면 거부한다")
    void lock() {
        when(redisTemplate.opsForValue()).thenReturn(valueOps);
        when(valueOps.setIfAbsent("assistant:lock:7", "1", Duration.ofSeconds(70))).thenReturn(true, false);

        assertThat(quota.tryLock(7L, Duration.ofSeconds(70))).isTrue();
        assertThat(quota.tryLock(7L, Duration.ofSeconds(70))).isFalse();
    }

    @Test
    @DisplayName("잠금 해제는 키를 지운다")
    void unlock() {
        quota.unlock(7L);
        verify(redisTemplate).delete("assistant:lock:7");
    }

    @Test
    @DisplayName("Redis 가 null 을 돌려주면 거부한다")
    void nullReplies() {
        when(redisTemplate.opsForValue()).thenReturn(valueOps);
        when(valueOps.increment(DAILY_KEY)).thenReturn(null);
        when(valueOps.setIfAbsent("assistant:lock:7", "1", Duration.ofSeconds(70))).thenReturn(null);

        assertThat(quota.tryConsumeDaily(7L, DAY, 50)).isFalse();
        assertThat(quota.tryLock(7L, Duration.ofSeconds(70))).isFalse();
    }
}
