package com.earningwhisperer.domain.user;

import com.earningwhisperer.domain.portfolio.PortfolioSettings;
import com.earningwhisperer.domain.portfolio.PortfolioSettingsRepository;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.ArgumentCaptor;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.security.crypto.password.PasswordEncoder;

import java.util.Optional;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.BDDMockito.given;
import static org.mockito.Mockito.*;

@ExtendWith(MockitoExtension.class)
@DisplayName("OAuthService 단위 테스트")
class OAuthServiceTest {

    @Mock private UserRepository userRepository;
    @Mock private PortfolioSettingsRepository portfolioSettingsRepository;
    @Mock private PasswordEncoder passwordEncoder;
    @Mock private RefreshTokenService refreshTokenService;

    @InjectMocks
    private OAuthService oAuthService;

    private final OAuthUserProfile googleProfile = new OAuthUserProfile(
            "google-sub-123", "user@gmail.com", "Test User", OAuthProvider.GOOGLE);

    @Test
    @DisplayName("기존 소셜 사용자 → 바로 토큰 발급")
    void 기존_소셜_사용자_로그인() {
        User existing = User.builder().email("user@gmail.com").password("enc").nickname("Test").build();
        given(userRepository.findByProviderAndProviderId(OAuthProvider.GOOGLE, "google-sub-123"))
                .willReturn(Optional.of(existing));
        given(refreshTokenService.issue(existing.getId()))
                .willReturn(new TokenPair("at", "rt"));

        TokenPair result = oAuthService.socialLogin(googleProfile);

        assertThat(result.accessToken()).isEqualTo("at");
        verify(userRepository, never()).save(any());
    }

    @Test
    @DisplayName("이메일 중복 LOCAL 사용자 → 소셜 계정 연동")
    void 기존_이메일_사용자_소셜_연동() {
        given(userRepository.findByProviderAndProviderId(any(), anyString()))
                .willReturn(Optional.empty());

        User localUser = User.builder().email("user@gmail.com").password("enc").nickname("Test").build();
        given(userRepository.findByEmail("user@gmail.com")).willReturn(Optional.of(localUser));
        given(refreshTokenService.issue(localUser.getId()))
                .willReturn(new TokenPair("at", "rt"));

        oAuthService.socialLogin(googleProfile);

        assertThat(localUser.getProvider()).isEqualTo(OAuthProvider.GOOGLE);
        assertThat(localUser.getProviderId()).isEqualTo("google-sub-123");
    }

    @Test
    @DisplayName("신규 사용자 → 자동 생성 + 기본 PortfolioSettings")
    void 신규_소셜_사용자_생성() {
        given(userRepository.findByProviderAndProviderId(any(), anyString()))
                .willReturn(Optional.empty());
        given(userRepository.findByEmail(anyString())).willReturn(Optional.empty());
        given(passwordEncoder.encode(anyString())).willReturn("encoded-sentinel");

        User savedUser = User.builder().email("user@gmail.com").password("enc").nickname("Test").build();
        given(userRepository.save(any(User.class))).willReturn(savedUser);
        given(refreshTokenService.issue(savedUser.getId()))
                .willReturn(new TokenPair("at", "rt"));

        oAuthService.socialLogin(googleProfile);

        ArgumentCaptor<User> userCaptor = ArgumentCaptor.forClass(User.class);
        verify(userRepository).save(userCaptor.capture());
        User created = userCaptor.getValue();
        assertThat(created.getProvider()).isEqualTo(OAuthProvider.GOOGLE);
        assertThat(created.getProviderId()).isEqualTo("google-sub-123");

        verify(portfolioSettingsRepository).save(any(PortfolioSettings.class));
    }
}
