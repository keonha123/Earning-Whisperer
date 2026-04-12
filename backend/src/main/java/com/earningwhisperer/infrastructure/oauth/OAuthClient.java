package com.earningwhisperer.infrastructure.oauth;

import com.earningwhisperer.domain.user.OAuthProvider;
import com.earningwhisperer.domain.user.OAuthUserProfile;

/**
 * OAuth 제공자별 code → 사용자 프로필 교환 인터페이스.
 * 구현체: GoogleOAuthClient, (향후) KakaoOAuthClient
 */
public interface OAuthClient {

    OAuthProvider provider();

    OAuthUserProfile exchange(String code, String redirectUri);
}
