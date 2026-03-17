package com.earningwhisperer.domain.user;

import com.earningwhisperer.global.config.JpaConfig;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.orm.jpa.DataJpaTest;
import org.springframework.context.annotation.Import;

import java.util.Optional;

import static org.assertj.core.api.Assertions.assertThat;

@DataJpaTest
@Import(JpaConfig.class)
@DisplayName("UserRepository 슬라이스 테스트")
class UserRepositoryTest {

    @Autowired
    private UserRepository userRepository;

    @Test
    @DisplayName("findByEmail - 존재하는 이메일로 조회 시 사용자를 반환한다")
    void findByEmail_존재하는_이메일로_조회시_사용자를_반환한다() {
        // Arrange
        User user = User.builder()
                .email("test@test.com")
                .password("encodedPassword")
                .nickname("tester")
                .build();
        userRepository.save(user);

        // Act
        Optional<User> result = userRepository.findByEmail("test@test.com");

        // Assert
        assertThat(result).isPresent();
        assertThat(result.get().getEmail()).isEqualTo("test@test.com");
        assertThat(result.get().getNickname()).isEqualTo("tester");
    }

    @Test
    @DisplayName("findByEmail - 존재하지 않는 이메일로 조회 시 빈 Optional을 반환한다")
    void findByEmail_존재하지_않는_이메일로_조회시_빈값을_반환한다() {
        // Act
        Optional<User> result = userRepository.findByEmail("notexist@test.com");

        // Assert
        assertThat(result).isEmpty();
    }

    @Test
    @DisplayName("existsByEmail - 이미 가입된 이메일이면 true를 반환한다")
    void existsByEmail_가입된_이메일이면_true를_반환한다() {
        // Arrange
        User user = User.builder()
                .email("exists@test.com")
                .password("encodedPassword")
                .nickname("tester")
                .build();
        userRepository.save(user);

        // Act
        boolean result = userRepository.existsByEmail("exists@test.com");

        // Assert
        assertThat(result).isTrue();
    }

    @Test
    @DisplayName("existsByEmail - 가입되지 않은 이메일이면 false를 반환한다")
    void existsByEmail_가입되지_않은_이메일이면_false를_반환한다() {
        // Act
        boolean result = userRepository.existsByEmail("notexist@test.com");

        // Assert
        assertThat(result).isFalse();
    }
}
