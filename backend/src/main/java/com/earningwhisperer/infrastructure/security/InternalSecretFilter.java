package com.earningwhisperer.infrastructure.security;

import jakarta.servlet.FilterChain;
import jakarta.servlet.ServletException;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.stereotype.Component;
import org.springframework.util.StringUtils;
import org.springframework.web.filter.OncePerRequestFilter;

import java.io.IOException;

/**
 * Data Pipeline → Backend 내부 전용 엔드포인트(`/api/v1/internal/**`)의 시크릿 검증 필터.
 *
 * <p>Common Rules 8.3 — Data Pipeline → 백엔드 내부 엔드포인트는 {@code X-Internal-Secret} 헤더로
 * 공유 시크릿을 검증한다.
 *
 * <p>동작:
 * <ul>
 *   <li>요청 경로가 {@code /api/v1/internal/} 으로 시작하지 않으면 그대로 통과시킨다.</li>
 *   <li>경로가 internal 이고 {@code app.internal.secret} 이 비어 있으면 401(미설정 = 미허용).</li>
 *   <li>헤더 미일치 시 401 + {@code {"error": "..."}} JSON 본문 반환.</li>
 * </ul>
 *
 * <p>JWT 필터와 함께 SecurityFilterChain 에 등록되며, internal 경로는 인증된 사용자가 아닌
 * 시크릿 보유자(=Pipeline 서비스)만 접근 가능하다.
 */
@Slf4j
@Component
public class InternalSecretFilter extends OncePerRequestFilter {

    private static final String INTERNAL_PREFIX = "/api/v1/internal/";
    private static final String HEADER_NAME = "X-Internal-Secret";

    private final String configuredSecret;

    public InternalSecretFilter(@Value("${app.internal.secret:}") String configuredSecret) {
        this.configuredSecret = configuredSecret;
    }

    @Override
    protected void doFilterInternal(
            HttpServletRequest request,
            HttpServletResponse response,
            FilterChain filterChain) throws ServletException, IOException {

        String path = request.getRequestURI();
        if (path == null || !path.startsWith(INTERNAL_PREFIX)) {
            filterChain.doFilter(request, response);
            return;
        }

        if (!StringUtils.hasText(configuredSecret)) {
            log.warn("[InternalSecret] app.internal.secret 미설정 — internal 경로 차단. path={}", path);
            writeUnauthorized(response, "internal secret not configured");
            return;
        }

        String provided = request.getHeader(HEADER_NAME);
        if (!configuredSecret.equals(provided)) {
            log.warn("[InternalSecret] 시크릿 불일치 — path={}", path);
            writeUnauthorized(response, "invalid internal secret");
            return;
        }

        filterChain.doFilter(request, response);
    }

    private void writeUnauthorized(HttpServletResponse response, String message) throws IOException {
        response.setStatus(HttpStatus.UNAUTHORIZED.value());
        response.setContentType(MediaType.APPLICATION_JSON_VALUE);
        response.setCharacterEncoding("UTF-8");
        // GlobalExceptionHandler 와 동일한 {"error": "..."} 형식 유지
        response.getWriter().write("{\"error\":\"" + escape(message) + "\"}");
    }

    /**
     * 메시지에 따옴표/역슬래시가 포함될 가능성에 대비한 최소 이스케이프.
     */
    private String escape(String s) {
        return s.replace("\\", "\\\\").replace("\"", "\\\"");
    }
}
