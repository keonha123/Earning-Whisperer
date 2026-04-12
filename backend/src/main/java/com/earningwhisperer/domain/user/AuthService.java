package com.earningwhisperer.domain.user;

import com.earningwhisperer.domain.portfolio.PortfolioSettings;
import com.earningwhisperer.domain.portfolio.PortfolioSettingsRepository;
import com.earningwhisperer.domain.portfolio.TradingMode;
import lombok.RequiredArgsConstructor;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

/**
 * 회원가입 · 로그인 · 토큰 갱신 · 로그아웃 서비스.
 *
 * JWT 토큰 생성은 TokenProvider 인터페이스를 통해 위임하여
 * domain 레이어가 infrastructure에 직접 의존하지 않도록 한다.
 */
@Service
@RequiredArgsConstructor
public class AuthService {

    private final UserRepository userRepository;
    private final PortfolioSettingsRepository portfolioSettingsRepository;
    private final PasswordEncoder passwordEncoder;
    private final RefreshTokenService refreshTokenService;

    /**
     * 회원가입: 이메일 중복 확인 → User 저장 → 기본 PortfolioSettings 생성.
     *
     * @return 생성된 User ID
     * @throws IllegalArgumentException 이메일 중복 시
     */
    @Transactional
    public Long signup(String email, String rawPassword, String nickname) {
        if (userRepository.existsByEmail(email)) {
            throw new IllegalArgumentException("이미 사용 중인 이메일입니다.");
        }

        User user = User.builder()
                .email(email)
                .password(passwordEncoder.encode(rawPassword))
                .nickname(nickname)
                .build();
        User saved = userRepository.save(user);

        PortfolioSettings defaultSettings = PortfolioSettings.builder()
                .user(saved)
                .buyAmountRatio(0.1)
                .maxPositionRatio(0.3)
                .cooldownMinutes(5)
                .emaThreshold(0.6)
                .tradingMode(TradingMode.MANUAL)
                .build();
        portfolioSettingsRepository.save(defaultSettings);

        return saved.getId();
    }

    /**
     * 로그인: 자격 증명 검증 후 Access + Refresh 토큰 쌍 반환.
     */
    @Transactional(readOnly = true)
    public TokenPair login(String email, String rawPassword) {
        User user = userRepository.findByEmail(email)
                .orElseThrow(() -> new IllegalArgumentException("이메일 또는 비밀번호가 올바르지 않습니다."));

        if (!passwordEncoder.matches(rawPassword, user.getPassword())) {
            throw new IllegalArgumentException("이메일 또는 비밀번호가 올바르지 않습니다.");
        }

        return refreshTokenService.issue(user.getId());
    }

    /**
     * 토큰 갱신: Refresh Token 로테이션 후 새 토큰 쌍 반환.
     */
    public TokenPair refresh(String refreshToken) {
        return refreshTokenService.rotate(refreshToken);
    }

    /**
     * 로그아웃: Refresh Token 폐기.
     */
    public void logout(String refreshToken) {
        refreshTokenService.revoke(refreshToken);
    }
}
