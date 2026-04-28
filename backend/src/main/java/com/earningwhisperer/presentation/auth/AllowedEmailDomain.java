package com.earningwhisperer.presentation.auth;

import jakarta.validation.Constraint;
import jakarta.validation.Payload;

import java.lang.annotation.ElementType;
import java.lang.annotation.Retention;
import java.lang.annotation.RetentionPolicy;
import java.lang.annotation.Target;

/**
 * Reserved TLD(.local/.invalid/.test/.example) 차단 검증.
 * 카카오 sentinel 이메일(@earningwhisperer.local) 선점을 통한 계정 탈취 방지가 목적.
 */
@Target({ElementType.FIELD, ElementType.PARAMETER})
@Retention(RetentionPolicy.RUNTIME)
@Constraint(validatedBy = AllowedEmailDomainValidator.class)
public @interface AllowedEmailDomain {
    String message() default "사용할 수 없는 이메일 도메인입니다";

    Class<?>[] groups() default {};

    Class<? extends Payload>[] payload() default {};
}
