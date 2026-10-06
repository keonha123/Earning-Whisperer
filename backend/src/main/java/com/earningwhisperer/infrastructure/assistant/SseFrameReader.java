package com.earningwhisperer.infrastructure.assistant;

import java.io.BufferedReader;
import java.io.Closeable;
import java.io.IOException;
import java.io.InputStream;
import java.io.InputStreamReader;
import java.nio.charset.StandardCharsets;

/**
 * text/event-stream 본문을 이벤트 단위로 읽는다. 빈 줄로 끝난 프레임만 내보내고, 끝에 걸린 미완성 프레임은 버린다(SSE 규칙).
 */
public final class SseFrameReader implements Closeable {

    public record Frame(String event, String data) {}

    private final BufferedReader reader;

    public SseFrameReader(InputStream in) {
        this.reader = new BufferedReader(new InputStreamReader(in, StandardCharsets.UTF_8));
    }

    /** 다음 이벤트. 스트림이 끝나면 null. */
    public Frame next() throws IOException {
        String event = null;
        StringBuilder data = null;
        String line;
        while ((line = reader.readLine()) != null) {
            if (line.isEmpty()) {
                if (event != null || data != null) {
                    return new Frame(event == null ? "message" : event, data == null ? "" : data.toString());
                }
                continue;
            }
            if (line.startsWith(":")) {
                continue;
            }
            int colon = line.indexOf(':');
            String field = colon < 0 ? line : line.substring(0, colon);
            String value = colon < 0 ? "" : line.substring(colon + 1);
            if (value.startsWith(" ")) {
                value = value.substring(1);
            }
            if (field.equals("event")) {
                event = value;
            } else if (field.equals("data")) {
                data = data == null ? new StringBuilder(value) : data.append('\n').append(value);
            }
        }
        return null;
    }

    @Override
    public void close() throws IOException {
        reader.close();
    }
}
