package com.earningwhisperer.domain.user;

import com.earningwhisperer.domain.portfolio.PortfolioSettings;
import com.earningwhisperer.domain.portfolio.PortfolioSettingsRepository;
import com.earningwhisperer.domain.portfolio.TradingMode;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.util.Optional;
import java.util.UUID;

/**
 * 소셜 로그인 서비스.
 *
 * 1. provider+providerId로 기존 소셜 사용자 조회 → 바로 토큰 발급
 * 2. 이메일로 기존 LOCAL 사용자 조회 → 소셜 계정 연동 후 토큰 발급
 * 3. 신규 사용자 → 자동 생성 후 토큰 발급
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class OAuthService {

    private final UserRepository userRepository;
    private final PortfolioSettingsRepository portfolioSettingsRepository;
    private final PasswordEncoder passwordEncoder;
    private final RefreshTokenService refreshTokenService;

    @Transactional
    public TokenPair socialLogin(OAuthUserProfile profile) {
        // 1. 기존 소셜 사용자
        Optional<User> byProvider = userRepository.findByProviderAndProviderId(
                profile.provider(), profile.providerId());
        if (byProvider.isPresent()) {
            log.info("[OAuthService] 기존 소셜 사용자 로그인 — userId={}", byProvider.get().getId());
            return refreshTokenService.issue(byProvider.get().getId());
        }

        // 2. 이메일로 기존 사용자 조회 → 소셜 계정 연동
        Optional<User> byEmail = userRepository.findByEmail(profile.email());
        if (byEmail.isPresent()) {
            User existing = byEmail.get();
            existing.linkSocialProvider(profile.provider(), profile.providerId());
            log.info("[OAuthService] 기존 계정에 소셜 연동 — userId={} provider={}",
                    existing.getId(), profile.provider());
            return refreshTokenService.issue(existing.getId());
        }

        // 3. 신규 사용자 생성
        String sentinelPassword = passwordEncoder.encode(UUID.randomUUID().toString());
        User newUser = User.ofSocial(
                profile.email(),
                profile.nickname(),
                profile.provider(),
                profile.providerId(),
                sentinelPassword);
        User saved = userRepository.save(newUser);

        PortfolioSettings defaultSettings = PortfolioSettings.builder()
                .user(saved)
                .buyAmountRatio(0.1)
                .maxPositionRatio(0.3)
                .cooldownMinutes(5)
                .emaThreshold(0.6)
                .tradingMode(TradingMode.MANUAL)
                .build();
        portfolioSettingsRepository.save(defaultSettings);

        log.info("[OAuthService] 소셜 신규 사용자 생성 — userId={} provider={}",
                saved.getId(), profile.provider());
        return refreshTokenService.issue(saved.getId());
    }
}
