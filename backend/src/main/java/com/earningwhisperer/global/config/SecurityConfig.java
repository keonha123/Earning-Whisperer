package com.earningwhisperer.global.config;

import com.earningwhisperer.infrastructure.security.InternalSecretFilter;
import com.earningwhisperer.infrastructure.security.JwtAuthenticationFilter;
import com.earningwhisperer.infrastructure.security.JwtProvider;
import lombok.RequiredArgsConstructor;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.security.config.annotation.web.builders.HttpSecurity;
import org.springframework.security.config.annotation.web.configuration.EnableWebSecurity;
import org.springframework.security.config.annotation.web.configurers.AbstractHttpConfigurer;
import org.springframework.security.config.http.SessionCreationPolicy;
import org.springframework.security.crypto.bcrypt.BCryptPasswordEncoder;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.security.web.SecurityFilterChain;
import org.springframework.security.web.authentication.UsernamePasswordAuthenticationFilter;
import org.springframework.web.cors.CorsConfiguration;
import org.springframework.web.cors.CorsConfigurationSource;
import org.springframework.web.cors.UrlBasedCorsConfigurationSource;

import java.util.Arrays;
import java.util.List;

/**
 * Spring Security 설정.
 *
 * - Stateless 세션 (JWT 기반 인증)
 * - JwtAuthenticationFilter: 요청마다 Bearer 토큰 검증 후 SecurityContext에 userId 저장
 * - 공개 엔드포인트: /api/v1/auth/**, /ws/**, /actuator/health
 * - 나머지 모든 요청: 인증 필요
 */
@Configuration
@EnableWebSecurity
@RequiredArgsConstructor
public class SecurityConfig {

    private final JwtProvider jwtProvider;
    private final InternalSecretFilter internalSecretFilter;

    @Value("${app.cors.allowed-origins:http://localhost:3000,http://localhost:5173}")
    private String allowedOriginsRaw;

    @Bean
    public PasswordEncoder passwordEncoder() {
        return new BCryptPasswordEncoder();
    }

    @Bean
    public SecurityFilterChain filterChain(HttpSecurity http) throws Exception {
        http
            .cors(cors -> cors.configurationSource(corsConfigurationSource()))
            .csrf(AbstractHttpConfigurer::disable)
            .sessionManagement(session ->
                session.sessionCreationPolicy(SessionCreationPolicy.STATELESS))
            .authorizeHttpRequests(auth -> auth
                .requestMatchers("/api/v1/auth/**").permitAll()
                .requestMatchers("/api/v1/market/indices", "/api/v1/market/indices/**").permitAll()
                .requestMatchers("/api/v1/stocks/sp500", "/api/v1/stocks/prices").permitAll()
                .requestMatchers("/ws/**", "/ws-native/**").permitAll()
                .requestMatchers("/actuator/health").permitAll()
                // /api/v1/internal/** 는 InternalSecretFilter 가 X-Internal-Secret 으로 검증한다.
                // Spring Security 단계에서는 인증 객체 없이 통과시키고, 시크릿 검증은 필터가 책임진다.
                .requestMatchers("/api/v1/internal/**").permitAll()
                .anyRequest().authenticated())
            .addFilterBefore(
                internalSecretFilter,
                UsernamePasswordAuthenticationFilter.class)
            .addFilterBefore(
                new JwtAuthenticationFilter(jwtProvider),
                UsernamePasswordAuthenticationFilter.class);

        return http.build();
    }

    @Bean
    public CorsConfigurationSource corsConfigurationSource() {
        CorsConfiguration config = new CorsConfiguration();
        // 환경변수 CORS_ALLOWED_ORIGINS 콤마 분리. 와일드카드 패턴(*) 도 허용하므로 setAllowedOriginPatterns 사용.
        // 운영 시 본인 도메인 / vercel 프리뷰 prefix 만 좁게 주입할 것.
        List<String> origins = Arrays.stream(allowedOriginsRaw.split(","))
                .map(String::trim)
                .filter(s -> !s.isEmpty())
                .toList();
        config.setAllowedOriginPatterns(origins);
        config.setAllowedMethods(List.of("GET", "POST", "PUT", "DELETE", "OPTIONS"));
        config.setAllowedHeaders(List.of("*"));
        // refresh_token 은 HttpOnly 쿠키로만 전송하므로 응답 헤더에 노출하지 않는다.
        config.setAllowCredentials(true);

        UrlBasedCorsConfigurationSource source = new UrlBasedCorsConfigurationSource();
        source.registerCorsConfiguration("/**", config);
        return source;
    }
}
