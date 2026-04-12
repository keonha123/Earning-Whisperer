package com.earningwhisperer.presentation.auth;

import com.fasterxml.jackson.annotation.JsonProperty;
import jakarta.validation.constraints.NotBlank;
import lombok.Getter;
import lombok.NoArgsConstructor;

@Getter
@NoArgsConstructor
public class OAuthCallbackRequest {

    @NotBlank
    private String code;

    @NotBlank
    @JsonProperty("redirect_uri")
    private String redirectUri;

    @NotBlank
    private String provider;
}
