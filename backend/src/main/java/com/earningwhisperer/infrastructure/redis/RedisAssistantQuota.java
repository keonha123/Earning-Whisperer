package com.earningwhisperer.infrastructure.redis;

import com.earningwhisperer.domain.assistant.AssistantQuota;
import lombok.RequiredArgsConstructor;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.stereotype.Component;

import java.time.Duration;
import java.time.LocalDate;

@Component
@RequiredArgsConstructor
public class RedisAssistantQuota implements AssistantQuota {

    // 날짜가 바뀐 뒤에도 하루 정도는 남겨 두었다가 지운다. 키에 날짜가 들어 있어 남아 있어도 다음 날 횟수와 섞이지 않는다.
    private static final Duration DAILY_KEY_TTL = Duration.ofHours(48);

    private final StringRedisTemplate redisTemplate;

    @Override
    public boolean tryConsumeDaily(Long userId, LocalDate day, int limit) {
        String key = "assistant:daily:" + day + ":" + userId;
        Long count = redisTemplate.opsForValue().increment(key);
        if (count == null) {
            return false;
        }
        if (count == 1L) {
            redisTemplate.expire(key, DAILY_KEY_TTL);
        }
        return count <= limit;
    }

    @Override
    public boolean tryLock(Long userId, Duration ttl) {
        return Boolean.TRUE.equals(redisTemplate.opsForValue().setIfAbsent(lockKey(userId), "1", ttl));
    }

    @Override
    public void unlock(Long userId) {
        redisTemplate.delete(lockKey(userId));
    }

    private static String lockKey(Long userId) {
        return "assistant:lock:" + userId;
    }
}
