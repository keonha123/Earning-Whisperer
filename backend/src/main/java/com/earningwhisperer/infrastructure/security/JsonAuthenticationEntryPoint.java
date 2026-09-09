package com.earningwhisperer.infrastructure.security;

import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import lombok.extern.slf4j.Slf4j;
import org.springframework.http.HttpHeaders;
import org.springframework.security.core.AuthenticationException;
import org.springframework.security.web.AuthenticationEntryPoint;

import java.io.IOException;

/**
 * 인증 실패 응답(401).
 *
 * <p>Spring Security 기본값({@code Http403ForbiddenEntryPoint})은 인증이 아예 없는
 * 요청에도 403 을 돌려준다. 그러면 클라이언트가 "토큰이 만료됐다" 와 "권한이 없다" 를
 * 구분할 수 없다. 터미널과 웹 프론트 모두 401 에서만 토큰을 갱신하고 재시도하도록
 * 만들어져 있어서, 403 이 오면 그 갱신 로직이 통째로 죽은 코드가 된다.
 */
@Slf4j
public class JsonAuthenticationEntryPoint implements AuthenticationEntryPoint {


    @Override
    public void commence(
            HttpServletRequest request,
            HttpServletResponse response,
            AuthenticationException authException) throws IOException {
        // 401 은 전 사용자 공통 경로다. 급증하면 토큰 스터핑 정황일 수 있으므로 흔적을 남긴다.
        // 토큰 값이나 예외 메시지는 남기지 않는다.
        log.debug("[Security] 인증 실패 - method={} path={}", request.getMethod(), request.getRequestURI());
        // RFC 9110 은 401 에 이 헤더를 요구한다. Bearer 는 Basic 과 달리 브라우저 로그인
        // 팝업을 띄우지 않으므로 부작용 없이 규격을 맞출 수 있다.
        response.setHeader(HttpHeaders.WWW_AUTHENTICATE, "Bearer realm=\"api\"");
        // 만료와 위조를 구분해 알려주지 않는다 — 공격자에게 토큰 추측의 단서가 된다.
        JsonErrorResponseWriter.write(response, HttpServletResponse.SC_UNAUTHORIZED, "인증이 필요합니다.");
    }
}
