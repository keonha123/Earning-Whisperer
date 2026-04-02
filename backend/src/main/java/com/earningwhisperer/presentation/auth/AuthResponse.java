package com.earningwhisperer.presentation.auth;

import lombok.Getter;
import lombok.RequiredArgsConstructor;

@Getter
@RequiredArgsConstructor
public class AuthResponse {

    private final String accessToken;
    private final String tokenType = "Bearer";
}
