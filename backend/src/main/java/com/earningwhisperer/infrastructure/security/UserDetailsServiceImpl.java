package com.earningwhisperer.infrastructure.security;

import com.earningwhisperer.domain.user.User;
import com.earningwhisperer.domain.user.UserRepository;
import lombok.RequiredArgsConstructor;
import org.springframework.security.core.authority.SimpleGrantedAuthority;
import org.springframework.security.core.userdetails.UserDetails;
import org.springframework.security.core.userdetails.UserDetailsService;
import org.springframework.security.core.userdetails.UsernameNotFoundException;
import org.springframework.stereotype.Service;

import java.util.List;

/**
 * Spring Security의 UserDetailsService 구현체.
 *
 * Spring Boot가 자동으로 PasswordEncoder + DaoAuthenticationProvider를 구성할 때 사용한다.
 * JWT 기반 인증 플로우(JwtAuthenticationFilter)에서는 직접 호출되지 않는다.
 * Spring Security가 UserDetailsService 빈을 요구하므로 빈 충돌 및 자동 생성 패스워드 경고를 방지하기 위해 등록한다.
 */
@Service
@RequiredArgsConstructor
public class UserDetailsServiceImpl implements UserDetailsService {

    private final UserRepository userRepository;

    @Override
    public UserDetails loadUserByUsername(String email) throws UsernameNotFoundException {
        User user = userRepository.findByEmail(email)
                .orElseThrow(() -> new UsernameNotFoundException("사용자를 찾을 수 없습니다: " + email));

        return new org.springframework.security.core.userdetails.User(
                user.getEmail(),
                user.getPassword(),
                List.of(new SimpleGrantedAuthority("ROLE_USER"))
        );
    }
}
