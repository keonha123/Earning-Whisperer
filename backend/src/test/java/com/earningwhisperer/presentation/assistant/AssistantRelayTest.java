package com.earningwhisperer.presentation.assistant;

import com.earningwhisperer.domain.assistant.AssistantAskService.PreparedAsk;
import com.earningwhisperer.domain.assistant.AssistantQuota;
import com.earningwhisperer.global.config.AssistantProperties;
import com.earningwhisperer.infrastructure.assistant.AssistantStreamClient;
import com.earningwhisperer.infrastructure.assistant.AssistantUnavailableException;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;

import java.io.ByteArrayInputStream;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.List;
import java.util.concurrent.Executor;
import java.util.concurrent.RejectedExecutionException;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.times;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

@ExtendWith(MockitoExtension.class)
@DisplayName("AssistantRelay")
class AssistantRelayTest {

    @Mock AssistantStreamClient client;
    @Mock AssistantQuota quota;

    private AssistantRelay relay;

    private static final PreparedAsk ASK = new PreparedAsk(7L, "WMT", "call-1", 17, 1_787_227_218L, null, false,
            "요약해 줘", null, List.of());

    /** 닫혔는지 기록하는 본문 스트림. */
    static class TrackingStream extends ByteArrayInputStream {
        boolean closed;
        TrackingStream(String text) { super(text.getBytes(StandardCharsets.UTF_8)); }
        @Override public void close() throws IOException { closed = true; super.close(); }
    }

    /** 보낸 이벤트를 기록하고, failOn 번째 send 에서 IOException(사용자 연결 끊김)을 던진다. */
    static class RecordingSink implements AssistantRelay.EventSink {
        final List<String> events = new ArrayList<>();
        int completed;
        int failOn = -1;
        @Override public void send(String event, String data) throws IOException {
            if (events.size() == failOn) throw new IOException("client gone");
            events.add(event + " " + data);
        }
        @Override public void complete() { completed++; }
    }

    @BeforeEach
    void setUp() {
        relay = new AssistantRelay(client, quota, new ObjectMapper(), (Executor) Runnable::run,
                new AssistantProperties(null, 50, 60));
    }

    @Test
    @DisplayName("assistant 이벤트를 순서대로 넘기고 끝나면 닫고 잠금을 푼다")
    void relaysEvents() throws Exception {
        TrackingStream body = new TrackingStream("event: meta\ndata: {\"scope\": \"call\"}\n\n"
                + "event: delta\ndata: {\"text\": \"매출\"}\n\n"
                + "event: done\ndata: {\"status\": \"answered\", \"usage\": {\"input_tokens\": 1030, \"output_tokens\": 60, \"cached_tokens\": 800}, \"latency_ms\": 1250}\n\n");
        when(client.open(ASK)).thenReturn(body);
        RecordingSink sink = new RecordingSink();

        relay.relay(ASK, sink, relay.newSession(7L));

        assertThat(sink.events).containsExactly(
                "meta {\"scope\": \"call\"}",
                "delta {\"text\": \"매출\"}",
                "done {\"status\": \"answered\", \"usage\": {\"input_tokens\": 1030, \"output_tokens\": 60, \"cached_tokens\": 800}, \"latency_ms\": 1250}");
        assertThat(sink.completed).isEqualTo(1);
        assertThat(body.closed).isTrue();
        verify(quota).unlock(7L);
    }

    @Test
    @DisplayName("done·error 없이 끝나면 assistant_stream_interrupted 를 보낸다")
    void streamEndsWithoutDone() throws Exception {
        when(client.open(ASK)).thenReturn(new TrackingStream("event: delta\ndata: {\"text\": \"앞\"}\n\n"));
        RecordingSink sink = new RecordingSink();

        relay.relay(ASK, sink, relay.newSession(7L));

        assertThat(sink.events).hasSize(2);
        assertThat(sink.events.get(1)).startsWith("error ").contains("\"code\":\"assistant_stream_interrupted\"");
        assertThat(sink.completed).isEqualTo(1);
    }

    @Test
    @DisplayName("assistant 가 보낸 error 로 끝나면 덧붙이지 않는다")
    void assistantErrorIsTerminal() throws Exception {
        when(client.open(ASK)).thenReturn(new TrackingStream("event: error\ndata: {\"code\": \"llm_timeout\", \"message\": \"m\"}\n\n"));
        RecordingSink sink = new RecordingSink();

        relay.relay(ASK, sink, relay.newSession(7L));

        assertThat(sink.events).containsExactly("error {\"code\": \"llm_timeout\", \"message\": \"m\"}");
    }

    @Test
    @DisplayName("연결하지 못하면 assistant_unavailable 을 보내고 잠금을 푼다")
    void unavailable() throws Exception {
        when(client.open(ASK)).thenThrow(new AssistantUnavailableException("connect_failed"));
        RecordingSink sink = new RecordingSink();

        relay.relay(ASK, sink, relay.newSession(7L));

        assertThat(sink.events).hasSize(1);
        assertThat(sink.events.get(0)).startsWith("error ").contains("\"code\":\"assistant_unavailable\"");
        assertThat(sink.completed).isEqualTo(1);
        verify(quota).unlock(7L);
    }

    @Test
    @DisplayName("사용자가 끊으면(전송 실패) assistant 본문을 닫고 더 보내지 않는다")
    void clientDisconnectClosesUpstream() throws Exception {
        TrackingStream body = new TrackingStream("event: meta\ndata: {}\n\nevent: delta\ndata: {}\n\nevent: done\ndata: {}\n\n");
        when(client.open(ASK)).thenReturn(body);
        RecordingSink sink = new RecordingSink();
        sink.failOn = 1;

        relay.relay(ASK, sink, relay.newSession(7L));

        assertThat(sink.events).containsExactly("meta {}");
        assertThat(body.closed).isTrue();
        verify(quota).unlock(7L);
    }

    @Test
    @DisplayName("세션은 여러 번 닫혀도 잠금을 한 번만 풀고, 닫힌 뒤 붙은 본문은 바로 닫는다")
    void sessionCloseIsIdempotent() {
        AssistantRelay.Session session = relay.newSession(7L);
        session.close();
        session.close();
        TrackingStream late = new TrackingStream("");
        session.attach(late);

        verify(quota, times(1)).unlock(7L);
        assertThat(late.closed).isTrue();
    }

    @Test
    @DisplayName("스레드풀이 가득 차면 잠금을 풀고 RejectedExecutionException 을 던진다")
    void rejected() {
        AssistantRelay full = new AssistantRelay(client, quota, new ObjectMapper(),
                command -> { throw new RejectedExecutionException("full"); }, new AssistantProperties(null, 50, 60));

        assertThatThrownBy(() -> full.start(ASK)).isInstanceOf(RejectedExecutionException.class);
        verify(quota).unlock(7L);
    }

    @Test
    @DisplayName("사용량 로그가 실패해도(잘못된 done JSON) 중계는 끝까지 간다")
    void badDoneJsonDoesNotBreakRelay() throws Exception {
        when(client.open(any())).thenReturn(new TrackingStream("event: done\ndata: not-json\n\n"));
        RecordingSink sink = new RecordingSink();

        relay.relay(ASK, sink, relay.newSession(7L));

        assertThat(sink.events).containsExactly("done not-json");
        assertThat(sink.completed).isEqualTo(1);
    }
}
