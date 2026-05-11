package com.earningwhisperer.infrastructure.security;

import jakarta.servlet.FilterChain;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.mock.web.MockHttpServletRequest;
import org.springframework.mock.web.MockHttpServletResponse;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.times;
import static org.mockito.Mockito.verify;

@DisplayName("InternalSecretFilter — timing-safe 비교 + 미설정 차단")
class InternalSecretFilterTest {

    @Test
    void internal_경로가_아니면_필터를_그대로_통과() throws Exception {
        InternalSecretFilter filter = new InternalSecretFilter("configured");
        MockHttpServletRequest req = new MockHttpServletRequest("GET", "/api/v1/users/me");
        MockHttpServletResponse res = new MockHttpServletResponse();
        FilterChain chain = mock(FilterChain.class);

        filter.doFilter(req, res, chain);

        verify(chain, times(1)).doFilter(req, res);
        assertThat(res.getStatus()).isEqualTo(HttpServletResponse.SC_OK);
    }

    @Test
    void 시크릿_미설정_시_internal_요청을_401() throws Exception {
        InternalSecretFilter filter = new InternalSecretFilter("");
        MockHttpServletRequest req = new MockHttpServletRequest("POST", "/api/v1/internal/sync");
        req.addHeader("X-Internal-Secret", "any");
        MockHttpServletResponse res = new MockHttpServletResponse();
        FilterChain chain = mock(FilterChain.class);

        filter.doFilter(req, res, chain);

        verify(chain, never()).doFilter(req, res);
        assertThat(res.getStatus()).isEqualTo(HttpServletResponse.SC_UNAUTHORIZED);
    }

    @Test
    void 시크릿_일치_시_통과() throws Exception {
        InternalSecretFilter filter = new InternalSecretFilter("super-secret");
        MockHttpServletRequest req = new MockHttpServletRequest("POST", "/api/v1/internal/sync");
        req.addHeader("X-Internal-Secret", "super-secret");
        MockHttpServletResponse res = new MockHttpServletResponse();
        FilterChain chain = mock(FilterChain.class);

        filter.doFilter(req, res, chain);

        verify(chain, times(1)).doFilter(req, res);
    }

    @Test
    void 시크릿_불일치_시_401() throws Exception {
        InternalSecretFilter filter = new InternalSecretFilter("super-secret");
        MockHttpServletRequest req = new MockHttpServletRequest("POST", "/api/v1/internal/sync");
        req.addHeader("X-Internal-Secret", "wrong");
        MockHttpServletResponse res = new MockHttpServletResponse();
        FilterChain chain = mock(FilterChain.class);

        filter.doFilter(req, res, chain);

        verify(chain, never()).doFilter(req, res);
        assertThat(res.getStatus()).isEqualTo(HttpServletResponse.SC_UNAUTHORIZED);
    }

    @Test
    void 시크릿_헤더_누락_시_401() throws Exception {
        InternalSecretFilter filter = new InternalSecretFilter("super-secret");
        MockHttpServletRequest req = new MockHttpServletRequest("POST", "/api/v1/internal/sync");
        MockHttpServletResponse res = new MockHttpServletResponse();
        FilterChain chain = mock(FilterChain.class);

        filter.doFilter(req, res, chain);

        verify(chain, never()).doFilter(req, res);
        assertThat(res.getStatus()).isEqualTo(HttpServletResponse.SC_UNAUTHORIZED);
    }

    @Test
    void 길이가_다른_시크릿도_안전하게_거부() throws Exception {
        // timing-safe 비교: MessageDigest.isEqual 은 길이가 달라도 NullPointer / IndexOutOfBounds 없이 처리
        InternalSecretFilter filter = new InternalSecretFilter("super-secret-1234");
        MockHttpServletRequest req = new MockHttpServletRequest("POST", "/api/v1/internal/sync");
        req.addHeader("X-Internal-Secret", "short");
        MockHttpServletResponse res = new MockHttpServletResponse();
        FilterChain chain = mock(FilterChain.class);

        filter.doFilter(req, res, chain);

        verify(chain, never()).doFilter(req, res);
        assertThat(res.getStatus()).isEqualTo(HttpServletResponse.SC_UNAUTHORIZED);
    }
}
