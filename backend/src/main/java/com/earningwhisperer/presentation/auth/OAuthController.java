package com.earningwhisperer.presentation.auth;

import com.earningwhisperer.domain.user.OAuthExchangeException;
import com.earningwhisperer.domain.user.OAuthProvider;
import com.earningwhisperer.domain.user.OAuthService;
import com.earningwhisperer.domain.user.OAuthUserProfile;
import com.earningwhisperer.domain.user.TokenPair;
import com.earningwhisperer.infrastructure.oauth.OAuthClient;
import jakarta.validation.Valid;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseCookie;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;

import java.util.List;
import java.util.Map;
import java.util.function.Function;
import java.util.stream.Collectors;

/**
 * OAuth 콜백 REST API.
 *
 * POST /api/v1/auth/oauth/callback — 프론트엔드에서 받은 authorization code를 교환
 */
@Slf4j
@RestController
@RequestMapping("/api/v1/auth/oauth")
public class OAuthController {

    private static final String REFRESH_COOKIE_NAME = "refresh_token";
    private static final String REFRESH_HEADER_NAME = "X-Refresh-Token";
    private static final String COOKIE_PATH = "/api/v1/auth";

    private final Map<OAuthProvider, OAuthClient> clients;
    private final OAuthService oAuthService;
    private final long refreshTtlSeconds;
    private final boolean cookieSecure;

    public OAuthController(
            List<OAuthClient> oAuthClients,
            OAuthService oAuthService,
            @Value("${jwt.refresh-expiration-seconds:604800}") long refreshTtlSeconds,
            @Value("${jwt.cookie-secure:false}") boolean cookieSecure) {
        this.clients = oAuthClients.stream()
                .collect(Collectors.toMap(OAuthClient::provider, Function.identity()));
        this.oAuthService = oAuthService;
        this.refreshTtlSeconds = refreshTtlSeconds;
        this.cookieSecure = cookieSecure;
    }

    @PostMapping("/callback")
    public ResponseEntity<AuthResponse> callback(@Valid @RequestBody OAuthCallbackRequest request) {
        OAuthProvider provider;
        try {
            provider = OAuthProvider.valueOf(request.getProvider().toUpperCase());
        } catch (IllegalArgumentException e) {
            return ResponseEntity.badRequest().build();
        }

        OAuthClient client = clients.get(provider);
        if (client == null) {
            return ResponseEntity.badRequest().build();
        }

        try {
            OAuthUserProfile profile = client.exchange(request.getCode(), request.getRedirectUri());
            TokenPair pair = oAuthService.socialLogin(profile);
            return buildTokenResponse(pair);
        } catch (OAuthExchangeException e) {
            log.warn("[OAuthController] OAuth 교환 실패: {}", e.getMessage());
            return ResponseEntity.status(HttpStatus.UNAUTHORIZED).build();
        } catch (Exception e) {
            log.error("[OAuthController] OAuth 처리 중 예기치 않은 오류", e);
            return ResponseEntity.status(HttpStatus.INTERNAL_SERVER_ERROR).build();
        }
    }

    private ResponseEntity<AuthResponse> buildTokenResponse(TokenPair pair) {
        ResponseCookie cookie = ResponseCookie.from(REFRESH_COOKIE_NAME, pair.refreshToken())
                .httpOnly(true)
                .secure(cookieSecure)
                .path(COOKIE_PATH)
                .maxAge(refreshTtlSeconds)
                .sameSite("Strict")
                .build();

        return ResponseEntity.ok()
                .header(HttpHeaders.SET_COOKIE, cookie.toString())
                .header(REFRESH_HEADER_NAME, pair.refreshToken())
                .body(new AuthResponse(pair.accessToken(), pair.refreshToken()));
    }
}
