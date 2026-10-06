package com.earningwhisperer.infrastructure.assistant;

import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.io.ByteArrayInputStream;
import java.nio.charset.StandardCharsets;

import static org.assertj.core.api.Assertions.assertThat;

@DisplayName("SseFrameReader")
class SseFrameReaderTest {

    private static SseFrameReader reader(String text) {
        return new SseFrameReader(new ByteArrayInputStream(text.getBytes(StandardCharsets.UTF_8)));
    }

    @Test
    @DisplayName("event 와 data 를 빈 줄 단위로 묶는다")
    void frames() throws Exception {
        SseFrameReader reader = reader("event: meta\ndata: {\"scope\": \"call\"}\n\nevent: delta\ndata: {\"text\": \"매출\"}\n\n");

        assertThat(reader.next()).isEqualTo(new SseFrameReader.Frame("meta", "{\"scope\": \"call\"}"));
        assertThat(reader.next()).isEqualTo(new SseFrameReader.Frame("delta", "{\"text\": \"매출\"}"));
        assertThat(reader.next()).isNull();
    }

    @Test
    @DisplayName("여러 data 줄은 줄바꿈으로 잇고, 주석과 앞 공백 하나를 처리한다")
    void multiLineAndComments() throws Exception {
        SseFrameReader reader = reader(": keep-alive\n\nevent:done\ndata:a\ndata:  b\n\n");

        assertThat(reader.next()).isEqualTo(new SseFrameReader.Frame("done", "a\n b"));
    }

    @Test
    @DisplayName("event 가 없으면 message, 빈 줄 없이 끝난 프레임은 버린다")
    void defaultsAndIncomplete() throws Exception {
        SseFrameReader reader = reader("data: x\n\nevent: delta\ndata: cut");

        assertThat(reader.next()).isEqualTo(new SseFrameReader.Frame("message", "x"));
        assertThat(reader.next()).isNull();
    }

    @Test
    @DisplayName("CRLF 줄 끝도 처리한다")
    void crlf() throws Exception {
        assertThat(reader("event: meta\r\ndata: {}\r\n\r\n").next()).isEqualTo(new SseFrameReader.Frame("meta", "{}"));
    }
}
