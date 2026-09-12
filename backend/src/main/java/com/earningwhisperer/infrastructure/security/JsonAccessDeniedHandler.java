package com.earningwhisperer.infrastructure.security;

import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import org.springframework.security.access.AccessDeniedException;
import org.springframework.security.web.access.AccessDeniedHandler;

import java.io.IOException;

/**
 * 권한 부족 응답(403).
 *
 * <p>현재 모든 엔드포인트 규칙이 {@code permitAll} 아니면 {@code authenticated()} 라서
 * 이 핸들러에 도달하는 경로는 아직 없다. api-spec §8.2 의 FREE/PRO 접근 제어를 넣을 때
 * 쓰인다. 미리 두는 이유는, 그때 기본값으로 되돌아가 401/403 규약이 다시 흐려지는 것을
 * 막기 위해서다.
 */
public class JsonAccessDeniedHandler implements AccessDeniedHandler {


    @Override
    public void handle(
            HttpServletRequest request,
            HttpServletResponse response,
            AccessDeniedException accessDeniedException) throws IOException {
        JsonErrorResponseWriter.write(response, HttpServletResponse.SC_FORBIDDEN, "접근 권한이 없습니다.");
    }
}
