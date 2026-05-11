package com.earningwhisperer.domain.user;

import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;

import java.util.Optional;
import java.util.UUID;

/**
 * Refresh Token 발급 / 로테이션 / 폐기 도메인 서비스.
 *
 * Token Family 패턴으로 재사용 감지:
 * - 정상 rotate: 이전 RT 삭제(used 마킹) → 새 RT 발급 (같은 familyId)
 * - 재사용 감지: 이미 삭제된 RT로 요청 → used 키에서 familyId 복원 → family 전체 블랙리스트
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class RefreshTokenService {

    private final RefreshTokenRepository refreshTokenRepository;
    private final TokenProvider tokenProvider;

    @Value("${jwt.refresh-expiration-seconds:604800}")
    private long refreshTtlSeconds;

    /**
     * 새 Refresh Token 발급 (로그인 시).
     */
    public TokenPair issue(Long userId) {
        String accessToken = tokenProvider.generateToken(userId);
        String refreshToken = tokenProvider.generateRefreshToken();
        String familyId = UUID.randomUUID().toString();

        refreshTokenRepository.save(refreshToken, userId + ":" + familyId, refreshTtlSeconds);
        return new TokenPair(accessToken, refreshToken);
    }

    /**
     * Refresh Token 로테이션 (갱신 시).
     *
     * @return 새 TokenPair
     * @throws InvalidRefreshTokenException RT 없음/만료/재사용 감지
     * @throws ConcurrentRefreshException 동시 갱신 경합
     */
    public TokenPair rotate(String oldRefreshToken) {
        Optional<String> stored = refreshTokenRepository.findByToken(oldRefreshToken);

        if (stored.isEmpty()) {
            // 재사용 감지: used 키에서 familyId를 복원하여 family 전체 블랙리스트
            Optional<String> usedFamily = refreshTokenRepository.findUsedFamily(oldRefreshToken);
            if (usedFamily.isPresent()) {
                String familyId = usedFamily.get();
                refreshTokenRepository.blacklistFamily(familyId, refreshTtlSeconds);
                log.warn("[RefreshTokenService] RT 재사용 감지! familyId={} 전체 블랙리스트", familyId);
            } else {
                log.warn("[RefreshTokenService] 존재하지 않는 RT로 갱신 시도");
            }
            throw new InvalidRefreshTokenException();
        }

        String[] parts = stored.get().split(":", 2);
        long userId = Long.parseLong(parts[0]);
        String familyId = parts[1];

        if (refreshTokenRepository.isFamilyBlacklisted(familyId)) {
            refreshTokenRepository.deleteByToken(oldRefreshToken);
            log.warn("[RefreshTokenService] 블랙리스트 family 감지 — userId={} familyId={}", userId, familyId);
            throw new InvalidRefreshTokenException();
        }

        if (!refreshTokenRepository.tryLock(familyId, 500)) {
            throw new ConcurrentRefreshException();
        }

        try {
            // 이전 토큰 삭제 + used 마킹 (재사용 감지용)
            refreshTokenRepository.deleteByToken(oldRefreshToken);
            refreshTokenRepository.markUsed(oldRefreshToken, familyId, refreshTtlSeconds);

            String newRefreshToken = tokenProvider.generateRefreshToken();
            String newAccessToken = tokenProvider.generateToken(userId);
            refreshTokenRepository.save(newRefreshToken, userId + ":" + familyId, refreshTtlSeconds);

            return new TokenPair(newAccessToken, newRefreshToken);
        } finally {
            refreshTokenRepository.releaseLock(familyId);
        }
    }

    /**
     * Refresh Token 폐기 (로그아웃 시).
     * family 블랙리스트로 해당 세션의 모든 RT를 무효화한다.
     */
    public void revoke(String refreshToken) {
        Optional<String> stored = refreshTokenRepository.findByToken(refreshToken);
        if (stored.isPresent()) {
            String familyId = stored.get().split(":", 2)[1];
            refreshTokenRepository.blacklistFamily(familyId, refreshTtlSeconds);
        }
        refreshTokenRepository.deleteByToken(refreshToken);
    }

    public static class InvalidRefreshTokenException extends RuntimeException {
        public InvalidRefreshTokenException() {
            super("유효하지 않은 Refresh Token");
        }
    }

    public static class ConcurrentRefreshException extends RuntimeException {
        public ConcurrentRefreshException() {
            super("동시 갱신 요청 — 잠시 후 재시도");
        }
    }
}
