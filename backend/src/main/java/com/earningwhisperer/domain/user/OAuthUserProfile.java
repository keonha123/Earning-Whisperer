package com.earningwhisperer.domain.user;

/**
 * OAuth 제공자에서 받은 사용자 프로필.
 * GoogleOAuthClient, KakaoOAuthClient 등이 이 레코드를 반환한다.
 */
public record OAuthUserProfile(
        String providerId,
        String email,
        String nickname,
        OAuthProvider provider
) {
}
