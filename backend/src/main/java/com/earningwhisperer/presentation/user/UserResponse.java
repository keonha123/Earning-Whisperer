package com.earningwhisperer.presentation.user;

import com.earningwhisperer.domain.user.User;
import com.earningwhisperer.domain.user.UserRole;
import lombok.Getter;

import java.time.LocalDateTime;

/**
 * GET /api/v1/users/me 응답 DTO.
 */
@Getter
public class UserResponse {

    private final Long id;
    private final String email;
    private final String nickname;
    private final UserRole role;
    private final LocalDateTime createdAt;

    public UserResponse(User user) {
        this.id = user.getId();
        this.email = user.getEmail();
        this.nickname = user.getNickname();
        this.role = user.getRole();
        this.createdAt = user.getCreatedAt();
    }
}
