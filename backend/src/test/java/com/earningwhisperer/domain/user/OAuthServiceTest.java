package com.earningwhisperer.domain.user;

import com.earningwhisperer.domain.portfolio.BrokerAccount;
import com.earningwhisperer.domain.portfolio.BrokerAccountService;
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
import static org.mockito.ArgumentMatchers.anyBoolean;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.BDDMockito.given;
import static org.mockito.Mockito.*;

@ExtendWith(MockitoExtension.class)
@DisplayName("OAuthService 단위 테스트")
class OAuthServiceTest {

    @Mock private UserRepository userRepository;
    @Mock private PortfolioSettingsRepository portfolioSettingsRepository;
    @Mock private BrokerAccountService brokerAccountService;
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
    @DisplayName("카카오 sentinel 이메일 신규 사용자 → 자동 생성")
    void 카카오_sentinel_이메일_신규_사용자_생성() {
        OAuthUserProfile kakaoProfile = new OAuthUserProfile(
                "9876543210",
                "kakao_9876543210@earningwhisperer.local",
                "카카오사용자_3210",
                OAuthProvider.KAKAO);

        given(userRepository.findByProviderAndProviderId(OAuthProvider.KAKAO, "9876543210"))
                .willReturn(Optional.empty());
        given(userRepository.findByEmail("kakao_9876543210@earningwhisperer.local"))
                .willReturn(Optional.empty());
        given(passwordEncoder.encode(anyString())).willReturn("encoded-sentinel");

        User savedUser = mock(User.class);
        given(savedUser.getId()).willReturn(50L);
        given(userRepository.save(any(User.class))).willReturn(savedUser);
        given(refreshTokenService.issue(50L))
                .willReturn(new TokenPair("at", "rt"));
        BrokerAccount brokerAccount = mock(BrokerAccount.class);
        given(brokerAccount.getId()).willReturn(100L);
        given(brokerAccountService.ensure(any(), any(), anyBoolean())).willReturn(brokerAccount);

        TokenPair result = oAuthService.socialLogin(kakaoProfile);

        assertThat(result.accessToken()).isEqualTo("at");

        ArgumentCaptor<User> userCaptor = ArgumentCaptor.forClass(User.class);
        verify(userRepository).save(userCaptor.capture());
        User created = userCaptor.getValue();
        assertThat(created.getProvider()).isEqualTo(OAuthProvider.KAKAO);
        assertThat(created.getProviderId()).isEqualTo("9876543210");
        assertThat(created.getEmail()).isEqualTo("kakao_9876543210@earningwhisperer.local");
        assertThat(created.getNickname()).isEqualTo("카카오사용자_3210");
        verify(brokerAccountService).activateIfFirst(50L, 100L);
    }

    @Test
    @DisplayName("신규 사용자 → 자동 생성 + 기본 PortfolioSettings + KIS 모의 BrokerAccount")
    void 신규_소셜_사용자_생성() {
        given(userRepository.findByProviderAndProviderId(any(), anyString()))
                .willReturn(Optional.empty());
        given(userRepository.findByEmail(anyString())).willReturn(Optional.empty());
        given(passwordEncoder.encode(anyString())).willReturn("encoded-sentinel");

        User savedUser = mock(User.class);
        given(savedUser.getId()).willReturn(60L);
        given(userRepository.save(any(User.class))).willReturn(savedUser);
        given(refreshTokenService.issue(60L))
                .willReturn(new TokenPair("at", "rt"));
        BrokerAccount brokerAccount = mock(BrokerAccount.class);
        given(brokerAccount.getId()).willReturn(100L);
        given(brokerAccountService.ensure(any(), any(), anyBoolean())).willReturn(brokerAccount);

        oAuthService.socialLogin(googleProfile);

        ArgumentCaptor<User> userCaptor = ArgumentCaptor.forClass(User.class);
        verify(userRepository).save(userCaptor.capture());
        User created = userCaptor.getValue();
        assertThat(created.getProvider()).isEqualTo(OAuthProvider.GOOGLE);
        assertThat(created.getProviderId()).isEqualTo("google-sub-123");

        verify(portfolioSettingsRepository).save(any(PortfolioSettings.class));
        verify(brokerAccountService).activateIfFirst(60L, 100L);
    }
}
