package com.earningwhisperer.infrastructure.security;

import com.earningwhisperer.domain.user.TokenProvider;
import io.jsonwebtoken.JwtException;
import io.jsonwebtoken.Jwts;
import io.jsonwebtoken.security.Keys;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;

import javax.crypto.SecretKey;
import java.nio.charset.StandardCharsets;
import java.util.Date;
import java.util.UUID;

/**
 * JWT 토큰 생성·검증·파싱 컴포넌트.
 *
 * domain/user/TokenProvider 인터페이스를 구현하여
 * AuthService가 infrastructure에 직접 의존하지 않도록 한다.
 *
 * 알고리즘: HMAC-SHA256 (HS256)
 * Payload subject: userId (Long → String)
 *
 * issuer/audience 클레임을 발행 시 박고 검증 시 require 한다.
 * 환경별로 다른 issuer 를 쓰면 dev/staging/prod 시크릿 공유 사고가 나도 토큰 교차 통용을 차단한다.
 */
@Slf4j
@Component
public class JwtProvider implements TokenProvider {

    /** 발행 시 박고 검증 시 require 하는 클레임. 환경별 분리는 issuer 만 환경변수로 외부화하면 된다. */
    public static final String DEFAULT_ISSUER = "earning-whisperer";
    public static final String DEFAULT_AUDIENCE = "earning-whisperer-api";

    private static final int MIN_SECRET_LENGTH = 32;

    private final SecretKey secretKey;
    private final long expirationMs;
    private final String issuer;
    private final String audience;

    public JwtProvider(
            @Value("${jwt.secret}") String secret,
            @Value("${jwt.expiration-ms}") long expirationMs,
            @Value("${jwt.issuer:" + DEFAULT_ISSUER + "}") String issuer,
            @Value("${jwt.audience:" + DEFAULT_AUDIENCE + "}") String audience) {
        if (secret == null || secret.length() < MIN_SECRET_LENGTH) {
            throw new IllegalStateException(
                    "jwt.secret 은 최소 " + MIN_SECRET_LENGTH + "자 이상이어야 합니다 (HS256 요구사항).");
        }
        this.secretKey = Keys.hmacShaKeyFor(secret.getBytes(StandardCharsets.UTF_8));
        this.expirationMs = expirationMs;
        this.issuer = issuer;
        this.audience = audience;
    }

    @Override
    public String generateToken(Long userId) {
        return Jwts.builder()
                .subject(userId.toString())
                .issuer(issuer)
                .audience().add(audience).and()
                .issuedAt(new Date())
                .expiration(new Date(System.currentTimeMillis() + expirationMs))
                .signWith(secretKey)
                .compact();
    }

    public boolean validateToken(String token) {
        try {
            parser().parseSignedClaims(token);
            return true;
        } catch (JwtException | IllegalArgumentException e) {
            log.debug("[JwtProvider] 토큰 검증 실패: {}", e.getMessage());
            return false;
        }
    }

    public Long getUserIdFromToken(String token) {
        String subject = parser()
                .parseSignedClaims(token)
                .getPayload()
                .getSubject();
        return Long.parseLong(subject);
    }

    @Override
    public String generateRefreshToken() {
        return UUID.randomUUID().toString();
    }

    private io.jsonwebtoken.JwtParser parser() {
        return Jwts.parser()
                .verifyWith(secretKey)
                .requireIssuer(issuer)
                .requireAudience(audience)
                .build();
    }
}
