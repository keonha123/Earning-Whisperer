package com.earningwhisperer.domain.user;

/**
 * Access + Refresh 토큰 쌍.
 * AuthService → Controller 전달용 값 객체.
 */
public record TokenPair(String accessToken, String refreshToken) {
}
