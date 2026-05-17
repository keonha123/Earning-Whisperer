package com.earningwhisperer.domain.user;

import java.util.Optional;

/**
 * Refresh Token 저장소 인터페이스 (DIP).
 *
 * 값 형식: "{userId}:{familyId}"
 * 구현체: infrastructure/redis/RedisRefreshTokenRepository
 */
public interface RefreshTokenRepository {

    void save(String token, String value, long ttlSeconds);

    Optional<String> findByToken(String token);

    void deleteByToken(String token);

    /** 삭제된 RT의 familyId를 일정 기간 보존 (재사용 감지용). */
    void markUsed(String token, String familyId, long ttlSeconds);

    /** 이미 사용(삭제)된 RT의 familyId를 조회. */
    Optional<String> findUsedFamily(String token);

    void blacklistFamily(String familyId, long ttlSeconds);

    boolean isFamilyBlacklisted(String familyId);

    boolean tryLock(String familyId, long ttlMillis);

    void releaseLock(String familyId);
}
