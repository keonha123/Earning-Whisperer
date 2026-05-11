package com.earningwhisperer.domain.user;

/**
 * JWT 토큰 생성 인터페이스.
 *
 * domain 레이어가 infrastructure(JwtProvider)에 직접 의존하지 않도록
 * 의존성 역전(DIP)을 적용한다.
 * 구현체: infrastructure/security/JwtProvider
 */
public interface TokenProvider {

    String generateToken(Long userId);

    String generateRefreshToken();
}
