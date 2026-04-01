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
        jwtProvider = new JwtProvider(secret, expirationMs);
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
                "test-secret-key-minimum-32-characters-long", 0L);
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
}
