package com.earningwhisperer.domain.user;

import com.earningwhisperer.domain.portfolio.PortfolioSettings;
import com.earningwhisperer.domain.portfolio.PortfolioSettingsRepository;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.ArgumentCaptor;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.security.crypto.password.PasswordEncoder;

import java.util.Optional;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.*;

@ExtendWith(MockitoExtension.class)
class AuthServiceTest {

    @Mock private UserRepository userRepository;
    @Mock private PortfolioSettingsRepository portfolioSettingsRepository;
    @Mock private PasswordEncoder passwordEncoder;
    @Mock private TokenProvider tokenProvider;

    @InjectMocks
    private AuthService authService;

    @Test
    void signup_신규_이메일_회원가입_성공() {
        // Arrange
        when(userRepository.existsByEmail("test@example.com")).thenReturn(false);
        when(passwordEncoder.encode("password123")).thenReturn("encoded");
        User savedUser = User.builder().email("test@example.com").password("encoded").nickname("테스터").build();
        when(userRepository.save(any(User.class))).thenReturn(savedUser);

        // Act
        authService.signup("test@example.com", "password123", "테스터");

        // Assert
        ArgumentCaptor<PortfolioSettings> settingsCaptor = ArgumentCaptor.forClass(PortfolioSettings.class);
        verify(portfolioSettingsRepository).save(settingsCaptor.capture());
        PortfolioSettings saved = settingsCaptor.getValue();
        assertThat(saved.getBuyAmountRatio()).isEqualTo(0.1);
        assertThat(saved.getCooldownMinutes()).isEqualTo(5);
    }

    @Test
    void signup_중복_이메일_예외_발생() {
        // Arrange
        when(userRepository.existsByEmail("dup@example.com")).thenReturn(true);

        // Act & Assert
        assertThatThrownBy(() -> authService.signup("dup@example.com", "password123", "테스터"))
                .isInstanceOf(IllegalArgumentException.class)
                .hasMessage("이미 사용 중인 이메일입니다.");
        verify(userRepository, never()).save(any());
    }

    @Test
    void login_올바른_자격증명_JWT_반환() {
        // Arrange
        User user = User.builder().email("test@example.com").password("encoded").nickname("테스터").build();
        when(userRepository.findByEmail("test@example.com")).thenReturn(Optional.of(user));
        when(passwordEncoder.matches("password123", "encoded")).thenReturn(true);
        when(tokenProvider.generateToken(user.getId())).thenReturn("jwt-token");

        // Act
        String token = authService.login("test@example.com", "password123");

        // Assert
        assertThat(token).isEqualTo("jwt-token");
    }

    @Test
    void login_존재하지_않는_이메일_예외_발생() {
        // Arrange
        when(userRepository.findByEmail(anyString())).thenReturn(Optional.empty());

        // Act & Assert
        assertThatThrownBy(() -> authService.login("none@example.com", "password123"))
                .isInstanceOf(IllegalArgumentException.class)
                .hasMessage("이메일 또는 비밀번호가 올바르지 않습니다.");
    }

    @Test
    void login_비밀번호_불일치_예외_발생() {
        // Arrange
        User user = User.builder().email("test@example.com").password("encoded").nickname("테스터").build();
        when(userRepository.findByEmail("test@example.com")).thenReturn(Optional.of(user));
        when(passwordEncoder.matches("wrong", "encoded")).thenReturn(false);

        // Act & Assert
        assertThatThrownBy(() -> authService.login("test@example.com", "wrong"))
                .isInstanceOf(IllegalArgumentException.class)
                .hasMessage("이메일 또는 비밀번호가 올바르지 않습니다.");
        verify(tokenProvider, never()).generateToken(any());
    }
}
