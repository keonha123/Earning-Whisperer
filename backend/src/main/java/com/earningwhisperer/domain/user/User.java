package com.earningwhisperer.domain.user;

import com.earningwhisperer.global.common.BaseEntity;
import jakarta.persistence.*;
import lombok.AccessLevel;
import lombok.Builder;
import lombok.Getter;
import lombok.NoArgsConstructor;
import lombok.Setter;

@Getter
@NoArgsConstructor(access = AccessLevel.PROTECTED)
@Entity
@Table(name = "users")
public class User extends BaseEntity {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @Column(nullable = false, unique = true, length = 100)
    private String email;

    @Column(nullable = false)
    private String password;

    @Column(nullable = false, length = 50)
    private String nickname;

    @Enumerated(EnumType.STRING)
    @Column(nullable = false, length = 10)
    private UserRole role;

    @Enumerated(EnumType.STRING)
    @Column(length = 20)
    private OAuthProvider provider;

    @Column(length = 255)
    private String providerId;

    @Builder
    public User(String email, String password, String nickname) {
        this.email = email;
        this.password = password;
        this.nickname = nickname;
        this.role = UserRole.FREE;
    }

    /**
     * 소셜 로그인 사용자 생성.
     * password는 sentinel 값 — BCrypt matches()가 항상 false를 반환하도록 보장.
     */
    public static User ofSocial(String email, String nickname,
                                OAuthProvider provider, String providerId,
                                String encodedSentinelPassword) {
        User u = User.builder()
                .email(email)
                .password(encodedSentinelPassword)
                .nickname(nickname)
                .build();
        u.provider = provider;
        u.providerId = providerId;
        return u;
    }

    public void linkSocialProvider(OAuthProvider provider, String providerId) {
        if (!isLocal()) {
            throw new IllegalStateException("이미 소셜 계정이 연동된 사용자입니다: " + this.provider);
        }
        this.provider = provider;
        this.providerId = providerId;
    }

    public boolean isLocal() {
        return provider == null || provider == OAuthProvider.LOCAL;
    }

    public void upgradeToPro() {
        this.role = UserRole.PRO;
    }
}
