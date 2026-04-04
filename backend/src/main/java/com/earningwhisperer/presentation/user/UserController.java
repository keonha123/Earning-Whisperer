package com.earningwhisperer.presentation.user;

import com.earningwhisperer.domain.portfolio.PortfolioSettings;
import com.earningwhisperer.domain.portfolio.PortfolioSettingsService;
import com.earningwhisperer.domain.user.UserService;
import jakarta.validation.Valid;
import lombok.RequiredArgsConstructor;
import org.springframework.http.ResponseEntity;
import org.springframework.security.core.Authentication;
import org.springframework.web.bind.annotation.*;

/**
 * 사용자 정보 REST API.
 *
 * GET /api/v1/users/me             — 로그인한 사용자 프로필 조회
 * PUT /api/v1/users/settings       — Trading Terminal 전용 설정 업데이트 (Contract 5)
 */
@RestController
@RequestMapping("/api/v1/users")
@RequiredArgsConstructor
public class UserController {

    private final UserService userService;
    private final PortfolioSettingsService portfolioSettingsService;

    @GetMapping("/me")
    public ResponseEntity<UserResponse> getMe(Authentication auth) {
        Long userId = (Long) auth.getPrincipal();
        return ResponseEntity.ok(new UserResponse(userService.getUser(userId)));
    }

    @PutMapping("/settings")
    public ResponseEntity<PortfolioSettings> updateSettings(
            Authentication auth,
            @Valid @RequestBody UserSettingsUpdateRequest request) {
        Long userId = (Long) auth.getPrincipal();
        return ResponseEntity.ok(portfolioSettingsService.updateFromTerminal(
                userId,
                request.getMax_buy_ratio(),
                request.getMax_holding_ratio(),
                request.getCooldown_minutes(),
                request.getTrading_mode()
        ));
    }
}
