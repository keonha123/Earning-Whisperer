package com.earningwhisperer.infrastructure.security;

import com.fasterxml.jackson.databind.ObjectMapper;
import jakarta.servlet.http.HttpServletResponse;
import lombok.extern.slf4j.Slf4j;
import org.springframework.http.MediaType;

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.util.Map;

/**
 * 시큐리티 필터 단계에서 공통 에러 형식({@code {"error": "..."}})을 쓰는 유일한 통로.
 *
 * <p>필터에서 던진 예외는 {@code GlobalExceptionHandler} 에 도달하지 않아서, 여기서만
 * 응답을 직접 조립하게 된다. 그 조립이 여러 곳에 흩어지면 이스케이프·charset·
 * Content-Type 처리가 조금씩 달라진다. 실제로 그런 상태였다.
 *
 * <p>본문은 {@link ObjectMapper} 로 만든다. 문자열을 이어 붙이면 메시지에 따옴표나
 * 역슬래시가 섞이는 순간 깨진 JSON 이 나간다 — 지금 메시지가 고정 리터럴이라 문제가
 * 없을 뿐이고, 나중에 예외 메시지나 요청 경로를 넣고 싶어지면 바로 터진다.
 *
 * <p>스프링 빈이 아니라 정적 유틸이다. 시큐리티 필터는 {@code @WebMvcTest} 슬라이스에
 * 자동으로 딸려 오는데, 여기에 주입 대상을 만들면 {@code SecurityConfig} 를 임포트하는
 * 모든 슬라이스 테스트가 빈 하나 때문에 컨텍스트 로딩에 실패한다.
 */
@Slf4j
public final class JsonErrorResponseWriter {

    /** 설정 후 읽기 전용으로만 쓰므로 스레드 안전하다. */
    private static final ObjectMapper MAPPER = new ObjectMapper();

    private JsonErrorResponseWriter() {
    }

    public static void write(HttpServletResponse response, int status, String message)
            throws IOException {
        if (response.isCommitted()) {
            // 여기까지 왔다는 건 앞선 단계가 이미 응답을 내보냈다는 뜻이다. 조용히 넘기면
            // "왜 응답이 이상한지" 를 추적할 단서가 남지 않는다.
            log.warn("[Security] 응답이 이미 커밋되어 에러 본문을 쓰지 못했습니다 - status={}", status);
            return;
        }
        // 앞선 필터가 버퍼에 남긴 부분 출력이 있으면 "쓰레기 + 에러 JSON" 이 된다.
        response.resetBuffer();
        // setContentType -> setCharacterEncoding -> getWriter 순서를 지켜야 한다.
        // 순서를 바꾸면 charset 지정이 조용히 무시되어 한글이 깨진다.
        response.setStatus(status);
        response.setContentType(MediaType.APPLICATION_JSON_VALUE);
        response.setCharacterEncoding(StandardCharsets.UTF_8.name());
        MAPPER.writeValue(response.getWriter(), Map.of("error", message));
    }
}
