package com.earningwhisperer.presentation.auth;

import com.earningwhisperer.domain.user.AuthService;
import com.earningwhisperer.domain.user.RefreshTokenService;
import com.earningwhisperer.domain.user.TokenPair;
import jakarta.servlet.http.Cookie;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.validation.Valid;
import lombok.RequiredArgsConstructor;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseCookie;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;

import java.util.Map;

/**
 * 인증 REST API.
 *
 * POST /api/v1/auth/signup  — 회원가입
 * POST /api/v1/auth/login   — 로그인 (Access + Refresh 토큰 발급)
 * POST /api/v1/auth/refresh — 토큰 갱신 (Refresh Token 로테이션)
 * POST /api/v1/auth/logout  — 로그아웃 (Refresh Token 폐기)
 *
 * Refresh Token 전송: Cookie(브라우저) / X-Refresh-Token 헤더(Electron) / Body(fallback)
 */
@RestController
@RequestMapping("/api/v1/auth")
@RequiredArgsConstructor
public class AuthController {

    private static final String REFRESH_COOKIE_NAME = "refresh_token";
    private static final String REFRESH_HEADER_NAME = "X-Refresh-Token";
    private static final String COOKIE_PATH = "/api/v1/auth";

    private final AuthService authService;

    @Value("${jwt.refresh-expiration-seconds:604800}")
    private long refreshTtlSeconds;

    @Value("${jwt.cookie-secure:false}")
    private boolean cookieSecure;

    @PostMapping("/signup")
    public ResponseEntity<Map<String, Long>> signup(@Valid @RequestBody SignupRequest request) {
        Long userId = authService.signup(request.getEmail(), request.getPassword(), request.getNickname());
        return ResponseEntity.status(HttpStatus.CREATED).body(Map.of("userId", userId));
    }

    @PostMapping("/login")
    public ResponseEntity<AuthResponse> login(@Valid @RequestBody LoginRequest request) {
        TokenPair pair = authService.login(request.getEmail(), request.getPassword());
        return buildTokenResponse(pair, HttpStatus.OK);
    }

    @PostMapping("/refresh")
    public ResponseEntity<AuthResponse> refresh(
            HttpServletRequest request,
            @RequestBody(required = false) RefreshRequest body) {

        String rt = extractRefreshToken(request, body);
        if (rt == null) {
            return ResponseEntity.status(HttpStatus.UNAUTHORIZED).build();
        }

        try {
            TokenPair pair = authService.refresh(rt);
            return buildTokenResponse(pair, HttpStatus.OK);
        } catch (RefreshTokenService.InvalidRefreshTokenException e) {
            return ResponseEntity.status(HttpStatus.UNAUTHORIZED).build();
        } catch (RefreshTokenService.ConcurrentRefreshException e) {
            return ResponseEntity.status(HttpStatus.TOO_MANY_REQUESTS).build();
        }
    }

    @PostMapping("/logout")
    public ResponseEntity<Void> logout(
            HttpServletRequest request,
            @RequestBody(required = false) RefreshRequest body) {

        String rt = extractRefreshToken(request, body);
        if (rt != null) {
            authService.logout(rt);
        }

        ResponseCookie clearCookie = ResponseCookie.from(REFRESH_COOKIE_NAME, "")
                .httpOnly(true)
                .path(COOKIE_PATH)
                .maxAge(0)
                .build();

        return ResponseEntity.noContent()
                .header(HttpHeaders.SET_COOKIE, clearCookie.toString())
                .build();
    }

    // --- private helpers ---

    private ResponseEntity<AuthResponse> buildTokenResponse(TokenPair pair, HttpStatus status) {
        ResponseCookie cookie = ResponseCookie.from(REFRESH_COOKIE_NAME, pair.refreshToken())
                .httpOnly(true)
                .secure(cookieSecure)
                .path(COOKIE_PATH)
                .maxAge(refreshTtlSeconds)
                .sameSite("Strict")
                .build();

        return ResponseEntity.status(status)
                .header(HttpHeaders.SET_COOKIE, cookie.toString())
                .header(REFRESH_HEADER_NAME, pair.refreshToken())
                .body(new AuthResponse(pair.accessToken(), pair.refreshToken()));
    }

    /**
     * Refresh Token 추출: Cookie -> X-Refresh-Token 헤더 -> Body 순서.
     */
    private String extractRefreshToken(HttpServletRequest request, RefreshRequest body) {
        // 1. Cookie
        if (request.getCookies() != null) {
            for (Cookie cookie : request.getCookies()) {
                if (REFRESH_COOKIE_NAME.equals(cookie.getName())) {
                    return cookie.getValue();
                }
            }
        }
        // 2. Header
        String header = request.getHeader(REFRESH_HEADER_NAME);
        if (header != null && !header.isBlank()) {
            return header;
        }
        // 3. Body fallback
        if (body != null && body.getRefreshToken() != null && !body.getRefreshToken().isBlank()) {
            return body.getRefreshToken();
        }
        return null;
    }
}
