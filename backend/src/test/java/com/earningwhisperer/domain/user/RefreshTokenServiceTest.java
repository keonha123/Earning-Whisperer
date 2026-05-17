package com.earningwhisperer.domain.user;

import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.test.util.ReflectionTestUtils;

import java.util.Optional;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.*;
import static org.mockito.BDDMockito.given;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;

@ExtendWith(MockitoExtension.class)
@DisplayName("RefreshTokenService 단위 테스트")
class RefreshTokenServiceTest {

    @Mock private RefreshTokenRepository refreshTokenRepository;
    @Mock private TokenProvider tokenProvider;

    @InjectMocks
    private RefreshTokenService refreshTokenService;

    @Test
    @DisplayName("issue: Access + Refresh 토큰 쌍을 발급하고 Redis에 저장한다")
    void issue_토큰쌍_발급() {
        ReflectionTestUtils.setField(refreshTokenService, "refreshTtlSeconds", 604800L);
        given(tokenProvider.generateToken(1L)).willReturn("access-jwt");
        given(tokenProvider.generateRefreshToken()).willReturn("refresh-uuid");

        TokenPair result = refreshTokenService.issue(1L);

        assertThat(result.accessToken()).isEqualTo("access-jwt");
        assertThat(result.refreshToken()).isEqualTo("refresh-uuid");
        verify(refreshTokenRepository).save(eq("refresh-uuid"), contains("1:"), eq(604800L));
    }

    @Test
    @DisplayName("rotate: 정상 RT로 새 토큰 쌍을 발급하고 이전 RT를 삭제+used 마킹한다")
    void rotate_정상_로테이션() {
        ReflectionTestUtils.setField(refreshTokenService, "refreshTtlSeconds", 604800L);
        given(refreshTokenRepository.findByToken("old-rt")).willReturn(Optional.of("1:family-123"));
        given(refreshTokenRepository.isFamilyBlacklisted("family-123")).willReturn(false);
        given(refreshTokenRepository.tryLock("family-123", 500)).willReturn(true);
        given(tokenProvider.generateToken(1L)).willReturn("new-access");
        given(tokenProvider.generateRefreshToken()).willReturn("new-refresh");

        TokenPair result = refreshTokenService.rotate("old-rt");

        assertThat(result.accessToken()).isEqualTo("new-access");
        assertThat(result.refreshToken()).isEqualTo("new-refresh");
        verify(refreshTokenRepository).deleteByToken("old-rt");
        verify(refreshTokenRepository).markUsed("old-rt", "family-123", 604800L);
        verify(refreshTokenRepository).save(eq("new-refresh"), eq("1:family-123"), eq(604800L));
        verify(refreshTokenRepository).releaseLock("family-123");
    }

    @Test
    @DisplayName("rotate: 이미 사용된 RT이면 재사용 감지 → family 전체 블랙리스트")
    void rotate_재사용_감지_family_블랙리스트() {
        ReflectionTestUtils.setField(refreshTokenService, "refreshTtlSeconds", 604800L);
        given(refreshTokenRepository.findByToken("reused-rt")).willReturn(Optional.empty());
        given(refreshTokenRepository.findUsedFamily("reused-rt")).willReturn(Optional.of("family-stolen"));

        assertThatThrownBy(() -> refreshTokenService.rotate("reused-rt"))
                .isInstanceOf(RefreshTokenService.InvalidRefreshTokenException.class);
        verify(refreshTokenRepository).blacklistFamily("family-stolen", 604800L);
    }

    @Test
    @DisplayName("rotate: 존재하지 않고 used 기록도 없으면 단순 거부")
    void rotate_존재하지않는_RT() {
        given(refreshTokenRepository.findByToken("unknown")).willReturn(Optional.empty());
        given(refreshTokenRepository.findUsedFamily("unknown")).willReturn(Optional.empty());

        assertThatThrownBy(() -> refreshTokenService.rotate("unknown"))
                .isInstanceOf(RefreshTokenService.InvalidRefreshTokenException.class);
        verify(refreshTokenRepository, never()).blacklistFamily(any(), anyLong());
    }

    @Test
    @DisplayName("rotate: 블랙리스트 family이면 InvalidRefreshTokenException")
    void rotate_블랙리스트_family() {
        given(refreshTokenRepository.findByToken("old-rt")).willReturn(Optional.of("1:bad-family"));
        given(refreshTokenRepository.isFamilyBlacklisted("bad-family")).willReturn(true);

        assertThatThrownBy(() -> refreshTokenService.rotate("old-rt"))
                .isInstanceOf(RefreshTokenService.InvalidRefreshTokenException.class);
        verify(refreshTokenRepository).deleteByToken("old-rt");
    }

    @Test
    @DisplayName("rotate: 락 획득 실패 시 ConcurrentRefreshException")
    void rotate_동시_갱신_경합() {
        given(refreshTokenRepository.findByToken("old-rt")).willReturn(Optional.of("1:family-123"));
        given(refreshTokenRepository.isFamilyBlacklisted("family-123")).willReturn(false);
        given(refreshTokenRepository.tryLock("family-123", 500)).willReturn(false);

        assertThatThrownBy(() -> refreshTokenService.rotate("old-rt"))
                .isInstanceOf(RefreshTokenService.ConcurrentRefreshException.class);
    }

    @Test
    @DisplayName("revoke: RT 삭제 + family 블랙리스트")
    void revoke_토큰삭제_및_family_블랙리스트() {
        ReflectionTestUtils.setField(refreshTokenService, "refreshTtlSeconds", 604800L);
        given(refreshTokenRepository.findByToken("some-rt")).willReturn(Optional.of("1:fam-abc"));

        refreshTokenService.revoke("some-rt");

        verify(refreshTokenRepository).blacklistFamily("fam-abc", 604800L);
        verify(refreshTokenRepository).deleteByToken("some-rt");
    }

    @Test
    @DisplayName("revoke: 이미 만료된 RT이면 삭제만 시도")
    void revoke_이미만료된_RT() {
        given(refreshTokenRepository.findByToken("expired-rt")).willReturn(Optional.empty());

        refreshTokenService.revoke("expired-rt");

        verify(refreshTokenRepository).deleteByToken("expired-rt");
        verify(refreshTokenRepository, never()).blacklistFamily(any(), anyLong());
    }
}
