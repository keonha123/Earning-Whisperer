package com.earningwhisperer.presentation.user;

import com.earningwhisperer.domain.user.OAuthProvider;
import com.earningwhisperer.domain.user.User;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.lang.reflect.Field;

import static org.assertj.core.api.Assertions.assertThat;

@DisplayName("UserResponse provider 직렬화 테스트")
class UserResponseTest {

    private ObjectMapper objectMapper;

    @BeforeEach
    void setUp() {
        objectMapper = new ObjectMapper();
    }

    private User newUser(OAuthProvider provider) throws Exception {
        User user = User.builder()
                .email("user@example.com")
                .password("encoded")
                .nickname("테스터")
                .build();
        if (provider != null) {
            Field providerField = User.class.getDeclaredField("provider");
            providerField.setAccessible(true);
            providerField.set(user, provider);
        }
        return user;
    }

    @Test
    @DisplayName("provider == null 사용자 → response.provider == LOCAL")
    void provider_null이면_LOCAL_폴백() throws Exception {
        User user = newUser(null);

        UserResponse response = new UserResponse(user);

        assertThat(response.getProvider()).isEqualTo(OAuthProvider.LOCAL);
    }

    @Test
    @DisplayName("provider == KAKAO 사용자 → response.provider == KAKAO")
    void provider_KAKAO_그대로_노출() throws Exception {
        User user = newUser(OAuthProvider.KAKAO);

        UserResponse response = new UserResponse(user);

        assertThat(response.getProvider()).isEqualTo(OAuthProvider.KAKAO);
    }

    @Test
    @DisplayName("provider == null 직렬화 결과에 \"provider\":\"LOCAL\" 포함")
    void 직렬화_LOCAL_포함() throws Exception {
        User user = newUser(null);

        String json = objectMapper.writeValueAsString(new UserResponse(user));

        assertThat(json).contains("\"provider\":\"LOCAL\"");
    }

    @Test
    @DisplayName("provider == KAKAO 직렬화 결과에 \"provider\":\"KAKAO\" 포함")
    void 직렬화_KAKAO_포함() throws Exception {
        User user = newUser(OAuthProvider.KAKAO);

        String json = objectMapper.writeValueAsString(new UserResponse(user));

        assertThat(json).contains("\"provider\":\"KAKAO\"");
    }
}
