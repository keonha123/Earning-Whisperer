package com.earningwhisperer.infrastructure.redis;

import com.earningwhisperer.domain.user.RefreshTokenRepository;
import lombok.RequiredArgsConstructor;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.stereotype.Repository;

import java.time.Duration;
import java.util.Optional;

/**
 * Redis 기반 Refresh Token 저장소.
 *
 * 키 구조:
 *   rt:token:{uuid}             → "{userId}:{familyId}"  (TTL 7일)
 *   rt:blacklist:family:{uuid}  → "1"                    (TTL 7일)
 *   rt:lock:{familyId}          → "1"                    (TTL 500ms)
 */
@Repository
@RequiredArgsConstructor
public class RedisRefreshTokenRepository implements RefreshTokenRepository {

    private static final String TOKEN_PREFIX = "rt:token:";
    private static final String USED_PREFIX = "rt:used:";
    private static final String BLACKLIST_PREFIX = "rt:blacklist:family:";
    private static final String LOCK_PREFIX = "rt:lock:";

    private final StringRedisTemplate redisTemplate;

    @Override
    public void save(String token, String value, long ttlSeconds) {
        redisTemplate.opsForValue().set(TOKEN_PREFIX + token, value, Duration.ofSeconds(ttlSeconds));
    }

    @Override
    public Optional<String> findByToken(String token) {
        String value = redisTemplate.opsForValue().get(TOKEN_PREFIX + token);
        return Optional.ofNullable(value);
    }

    @Override
    public void deleteByToken(String token) {
        redisTemplate.delete(TOKEN_PREFIX + token);
    }

    @Override
    public void markUsed(String token, String familyId, long ttlSeconds) {
        redisTemplate.opsForValue().set(USED_PREFIX + token, familyId, Duration.ofSeconds(ttlSeconds));
    }

    @Override
    public Optional<String> findUsedFamily(String token) {
        String value = redisTemplate.opsForValue().get(USED_PREFIX + token);
        return Optional.ofNullable(value);
    }

    @Override
    public void blacklistFamily(String familyId, long ttlSeconds) {
        redisTemplate.opsForValue().set(BLACKLIST_PREFIX + familyId, "1", Duration.ofSeconds(ttlSeconds));
    }

    @Override
    public boolean isFamilyBlacklisted(String familyId) {
        return Boolean.TRUE.equals(redisTemplate.hasKey(BLACKLIST_PREFIX + familyId));
    }

    @Override
    public boolean tryLock(String familyId, long ttlMillis) {
        Boolean acquired = redisTemplate.opsForValue()
                .setIfAbsent(LOCK_PREFIX + familyId, "1", Duration.ofMillis(ttlMillis));
        return Boolean.TRUE.equals(acquired);
    }

    @Override
    public void releaseLock(String familyId) {
        redisTemplate.delete(LOCK_PREFIX + familyId);
    }
}
