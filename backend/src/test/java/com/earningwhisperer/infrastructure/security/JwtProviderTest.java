package com.earningwhisperer.infrastructure.security;

import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;

class JwtProviderTest {

    private JwtProvider jwtProvider;

    @BeforeEach
    void setUp() {
        // 테스트용 고정 시크릿 (운영 환경에서는 환경변수로 주입)
        String secret = "test-secret-key-minimum-32-characters-long";
        long expirationMs = 3600_000L; // 1시간
        jwtProvider = new JwtProvider(secret, expirationMs, "test-issuer", "test-audience");
    }

    @Test
    void generateToken_userId로_토큰_생성_후_동일_userId_추출_성공() {
        // Arrange
        Long userId = 42L;

        // Act
        String token = jwtProvider.generateToken(userId);
        Long extracted = jwtProvider.getUserIdFromToken(token);

        // Assert
        assertThat(extracted).isEqualTo(userId);
    }

    @Test
    void validateToken_유효한_토큰_true_반환() {
        // Arrange
        String token = jwtProvider.generateToken(1L);

        // Act & Assert
        assertThat(jwtProvider.validateToken(token)).isTrue();
    }

    @Test
    void validateToken_만료된_토큰_false_반환() {
        // Arrange: 만료 시간 0ms (즉시 만료)
        JwtProvider expiredProvider = new JwtProvider(
                "test-secret-key-minimum-32-characters-long", 0L,
                "test-issuer", "test-audience");
        String token = expiredProvider.generateToken(1L);

        // Act & Assert
        assertThat(jwtProvider.validateToken(token)).isFalse();
    }

    @Test
    void validateToken_변조된_토큰_false_반환() {
        // Arrange
        String validToken = jwtProvider.generateToken(1L);
        String tampered = validToken + "tampered";

        // Act & Assert
        assertThat(jwtProvider.validateToken(tampered)).isFalse();
    }

    @Test
    void validateToken_빈_문자열_false_반환() {
        assertThat(jwtProvider.validateToken("")).isFalse();
    }

    @Test
    void 다른_issuer로_발행된_토큰은_검증_실패() {
        // 다른 환경에서 발행된 것처럼 issuer 가 다른 provider 로 토큰 생성
        JwtProvider otherProvider = new JwtProvider(
                "test-secret-key-minimum-32-characters-long", 3600_000L,
                "other-env-issuer", "test-audience");
        String token = otherProvider.generateToken(1L);

        // 본 provider 의 issuer 와 다르므로 검증 실패
        assertThat(jwtProvider.validateToken(token)).isFalse();
    }

    @Test
    void 다른_audience로_발행된_토큰은_검증_실패() {
        JwtProvider otherProvider = new JwtProvider(
                "test-secret-key-minimum-32-characters-long", 3600_000L,
                "test-issuer", "other-audience");
        String token = otherProvider.generateToken(1L);

        assertThat(jwtProvider.validateToken(token)).isFalse();
    }

    @Test
    void secret_길이_32미만이면_생성자에서_거부() {
        org.junit.jupiter.api.Assertions.assertThrows(IllegalStateException.class,
                () -> new JwtProvider("short", 3600_000L, "i", "a"));
    }
}
