package com.earningwhisperer.presentation.auth;

import jakarta.validation.ConstraintViolation;
import jakarta.validation.Validation;
import jakarta.validation.Validator;
import jakarta.validation.ValidatorFactory;
import org.junit.jupiter.api.AfterAll;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.ValueSource;

import java.lang.reflect.Field;
import java.util.Set;

import static org.assertj.core.api.Assertions.assertThat;

@DisplayName("SignupRequest 이메일 도메인 검증")
class SignupRequestTest {

    private static ValidatorFactory factory;
    private static Validator validator;

    @BeforeAll
    static void initValidator() {
        factory = Validation.buildDefaultValidatorFactory();
        validator = factory.getValidator();
    }

    @AfterAll
    static void closeValidator() {
        if (factory != null) {
            factory.close();
        }
    }

    private SignupRequest newRequest(String email) throws Exception {
        SignupRequest req = new SignupRequest();
        Field emailField = SignupRequest.class.getDeclaredField("email");
        emailField.setAccessible(true);
        emailField.set(req, email);

        Field passwordField = SignupRequest.class.getDeclaredField("password");
        passwordField.setAccessible(true);
        passwordField.set(req, "password123");

        Field nicknameField = SignupRequest.class.getDeclaredField("nickname");
        nicknameField.setAccessible(true);
        nicknameField.set(req, "테스터");
        return req;
    }

    @ParameterizedTest
    @ValueSource(strings = {
            "user@example.local",
            "user@earningwhisperer.local",
            "user@foo.invalid",
            "user@bar.test",
            "user@x.example",
            "USER@TEST.LOCAL",
            "Mixed@Domain.Invalid"
    })
    @DisplayName("Reserved TLD 도메인은 거부된다 (대소문자 무관)")
    void reserved_TLD_도메인은_거부된다(String email) throws Exception {
        SignupRequest req = newRequest(email);

        Set<ConstraintViolation<SignupRequest>> violations = validator.validate(req);

        assertThat(violations)
                .extracting(ConstraintViolation::getMessage)
                .contains("사용할 수 없는 이메일 도메인입니다");
    }

    @ParameterizedTest
    @ValueSource(strings = {
            "user@gmail.com",
            "user@naver.com",
            "user@kakao.com",
            "user@example.com",
            "USER@GMAIL.COM"
    })
    @DisplayName("정상 도메인은 허용된다")
    void 정상_도메인은_허용된다(String email) throws Exception {
        SignupRequest req = newRequest(email);

        Set<ConstraintViolation<SignupRequest>> violations = validator.validate(req);

        assertThat(violations)
                .extracting(ConstraintViolation::getMessage)
                .doesNotContain("사용할 수 없는 이메일 도메인입니다");
    }

    @ParameterizedTest
    @ValueSource(strings = {
            "user@earningwhisperer.local.",
            "user@foo.invalid.",
            "user@bar.test.",
            "USER@X.LOCAL.",
            "user@example.local..",
            "user@earningwhisperer.LOCAL."
    })
    @DisplayName("Reserved TLD + trailing dot 도메인도 거부된다")
    void trailing_dot_reserved_TLD_거부(String email) throws Exception {
        SignupRequest req = newRequest(email);

        Set<ConstraintViolation<SignupRequest>> violations = validator.validate(req);

        assertThat(violations)
                .extracting(ConstraintViolation::getMessage)
                .contains("사용할 수 없는 이메일 도메인입니다");
    }
}
