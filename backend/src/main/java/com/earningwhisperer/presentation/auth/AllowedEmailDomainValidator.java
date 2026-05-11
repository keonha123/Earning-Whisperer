package com.earningwhisperer.presentation.auth;

import com.earningwhisperer.domain.user.EmailDomainPolicy;
import jakarta.validation.ConstraintValidator;
import jakarta.validation.ConstraintValidatorContext;

public class AllowedEmailDomainValidator implements ConstraintValidator<AllowedEmailDomain, String> {

    @Override
    public boolean isValid(String email, ConstraintValidatorContext context) {
        return EmailDomainPolicy.isAllowed(email);
    }
}
