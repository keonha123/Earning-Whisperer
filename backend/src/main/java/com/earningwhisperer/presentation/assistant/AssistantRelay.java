package com.earningwhisperer.presentation.assistant;

import com.earningwhisperer.domain.assistant.AssistantAskService.PreparedAsk;
import com.earningwhisperer.domain.assistant.AssistantQuota;
import com.earningwhisperer.global.config.AssistantProperties;
import com.earningwhisperer.infrastructure.assistant.AssistantStreamClient;
import com.earningwhisperer.infrastructure.assistant.AssistantUnavailableException;
import com.earningwhisperer.infrastructure.assistant.SseFrameReader;
import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import lombok.extern.slf4j.Slf4j;
import jakarta.annotation.PreDestroy;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.scheduling.concurrent.CustomizableThreadFactory;
import org.springframework.stereotype.Component;
import org.springframework.web.servlet.mvc.method.annotation.SseEmitter;

import java.io.IOException;
import java.io.InputStream;
import java.time.Duration;
import java.util.Map;
import java.util.concurrent.Executor;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.RejectedExecutionException;
import java.util.concurrent.ScheduledExecutorService;
import java.util.concurrent.ScheduledFuture;
import java.util.concurrent.ScheduledThreadPoolExecutor;
import java.util.concurrent.SynchronousQueue;
import java.util.concurrent.ThreadPoolExecutor;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicBoolean;

/**
 * logothea-assistant 의 SSE 를 터미널로 그대로 넘긴다 (#112).
 *
 * <p>정리 규칙: 답이 끝나든, 사용자가 끊든, 60초가 지나든 assistant 본문을 닫고(→ assistant 가 OpenAI 스트림을 닫음)
 * 동시 질문 잠금을 한 번만 푼다. 끝을 알리는 이벤트(done·error) 없이 끊기면 error 를 덧붙여 터미널이 기다리지 않게 한다.
 */
@Slf4j
@Component
public class AssistantRelay {

    private static final Map<String, String> MESSAGES = Map.of(
            "assistant_unavailable", "질의응답 서비스에 연결하지 못했습니다. 잠시 후 다시 질문해 주세요.",
            "assistant_stream_interrupted", "답변 전송이 중간에 끊겼습니다.",
            "timeout", "답변 시간이 제한을 넘어 중단했습니다.");

    private static final long HEARTBEAT_SECONDS = 2;

    private final AssistantStreamClient client;
    private final AssistantQuota quota;
    private final ObjectMapper objectMapper;
    private final Executor executor;
    private final ScheduledExecutorService scheduler;
    private final ScheduledExecutorService heartbeatScheduler;
    private final Duration streamTimeout;

    @Autowired
    public AssistantRelay(AssistantStreamClient client, AssistantQuota quota, ObjectMapper objectMapper,
                          AssistantProperties properties) {
        this(client, quota, objectMapper, newRelayExecutor(), newTimeoutScheduler(), newHeartbeatScheduler(), properties);
    }

    AssistantRelay(AssistantStreamClient client, AssistantQuota quota, ObjectMapper objectMapper,
                   Executor executor, ScheduledExecutorService scheduler, ScheduledExecutorService heartbeatScheduler,
                   AssistantProperties properties) {
        this.client = client;
        this.quota = quota;
        this.objectMapper = objectMapper;
        this.executor = executor;
        this.scheduler = scheduler;
        this.heartbeatScheduler = heartbeatScheduler;
        this.streamTimeout = Duration.ofSeconds(properties.streamTimeoutSeconds());
    }

    /**
     * 중계 스레드는 답이 끝날 때까지(최대 60초) assistant 스트림을 읽으며 붙잡혀 있어 요청 처리 스레드와 분리한다.
     * 사용자당 동시 질문이 1개라 개인 사용 규모에서는 8개로 충분하고, 넘치면 대기열에 쌓지 않고 바로 거절(503)한다.
     */
    private static ThreadPoolExecutor newRelayExecutor() {
        return new ThreadPoolExecutor(2, 8, 60, TimeUnit.SECONDS, new SynchronousQueue<>(),
                new CustomizableThreadFactory("assistant-relay-"), new ThreadPoolExecutor.AbortPolicy());
    }

    /** 60초 제한을 재는 단일 데몬 스레드. 컨테이너의 emitter 타임아웃은 이미 완료 처리된 뒤에 불려 이벤트를 보낼 수 없어 직접 잰다. */
    private static ScheduledExecutorService newTimeoutScheduler() {
        CustomizableThreadFactory factory = new CustomizableThreadFactory("assistant-timeout-");
        factory.setDaemon(true);
        ScheduledThreadPoolExecutor timeoutScheduler = new ScheduledThreadPoolExecutor(1, factory);
        timeoutScheduler.setRemoveOnCancelPolicy(true);
        return timeoutScheduler;
    }

    /** 끊김 확인용 keep-alive 를 보내는 스레드. 막힌 쓰기가 타임아웃 측정을 늦추지 않도록 타임아웃 스케줄러와 분리한다. */
    private static ScheduledExecutorService newHeartbeatScheduler() {
        CustomizableThreadFactory factory = new CustomizableThreadFactory("assistant-heartbeat-");
        factory.setDaemon(true);
        ScheduledThreadPoolExecutor heartbeatScheduler = new ScheduledThreadPoolExecutor(2, factory);
        heartbeatScheduler.setRemoveOnCancelPolicy(true);
        return heartbeatScheduler;
    }

    @PreDestroy
    void shutdown() {
        if (executor instanceof ExecutorService service) {
            service.shutdownNow();
        }
        scheduler.shutdownNow();
        heartbeatScheduler.shutdownNow();
    }

    /** 터미널로 나가는 이벤트 통로. 운영에서는 SseEmitter, 테스트에서는 기록용 구현. */
    interface EventSink {
        void send(String event, String data) throws IOException;

        /** 데이터 없이 연결이 살아 있는지 확인하는 SSE 주석 줄(:)을 보낸다. 끊겼으면 예외. */
        void heartbeat() throws IOException;

        void complete();
    }

    /** 질문 하나의 정리 상태. 여러 경로(완료·끊김·타임아웃)에서 닫혀도 한 번만 정리한다. */
    final class Session {
        private final Long userId;
        private final AtomicBoolean closed = new AtomicBoolean(false);
        private final AtomicBoolean terminated = new AtomicBoolean(false);
        private volatile InputStream body;
        private volatile ScheduledFuture<?> timeoutTask;
        private volatile ScheduledFuture<?> heartbeatTask;

        private Session(Long userId) {
            this.userId = userId;
        }

        void attach(InputStream in) {
            body = in;
            if (closed.get()) {
                closeQuietly(in);
            }
        }

        void watch(ScheduledFuture<?> task) {
            timeoutTask = task;
            if (closed.get() && task != null) {
                task.cancel(false);
            }
        }

        void watchHeartbeat(ScheduledFuture<?> task) {
            heartbeatTask = task;
            if (closed.get() && task != null) {
                task.cancel(false);
            }
        }

        /** 끝을 알리는 이벤트(done·error)를 보낼 권리. 처음 부른 쪽만 true. */
        boolean tryTerminate() {
            return terminated.compareAndSet(false, true);
        }

        boolean isClosed() {
            return closed.get();
        }

        void close() {
            if (closed.compareAndSet(false, true)) {
                ScheduledFuture<?> task = timeoutTask;
                if (task != null) {
                    task.cancel(false);
                }
                ScheduledFuture<?> beat = heartbeatTask;
                if (beat != null) {
                    beat.cancel(false);
                }
                closeQuietly(body);
                try {
                    quota.unlock(userId);
                } catch (RuntimeException e) {
                    // 잠금 해제 실패(Redis 장애 등)가 중계 스레드나 start() 의 다른 예외를 가리지 않게 한다. 잠금은 TTL 로 풀린다.
                    log.warn("동시 질문 잠금을 풀지 못했습니다 user_id={}", userId, e);
                }
            }
        }
    }

    Session newSession(Long userId) {
        return new Session(userId);
    }

    public SseEmitter start(PreparedAsk ask) {
        SseEmitter emitter = new SseEmitter(streamTimeout.plusSeconds(5).toMillis());
        EventSink sink = new EmitterSink(emitter);
        Session session = newSession(ask.userId());
        emitter.onCompletion(session::close);
        emitter.onError(error -> session.close());
        // 컨테이너 타임아웃은 이미 완료 처리된 뒤라 이벤트를 보낼 수 없다. 정리만 하고 60초는 직접 잰다.
        emitter.onTimeout(session::close);
        session.watch(scheduler.schedule(() -> onStreamTimeout(sink, session, ask.callId()),
                streamTimeout.toSeconds(), TimeUnit.SECONDS));
        session.watchHeartbeat(heartbeatScheduler.scheduleAtFixedRate(() -> heartbeat(sink, session),
                HEARTBEAT_SECONDS, HEARTBEAT_SECONDS, TimeUnit.SECONDS));
        try {
            executor.execute(() -> relay(ask, sink, session));
        } catch (RejectedExecutionException e) {
            session.close();
            throw e;
        }
        return emitter;
    }

    /** 위쪽이 말이 없는 동안(분류·문맥 수집)에도 사용자가 끊었는지 알아채도록 주기적으로 연결을 확인한다. */
    void heartbeat(EventSink sink, Session session) {
        if (session.isClosed()) {
            return;
        }
        try {
            sink.heartbeat();
        } catch (IOException | IllegalStateException e) {
            session.close();
        }
    }

    void onStreamTimeout(EventSink sink, Session session, String callId) {
        try {
            if (session.tryTerminate()) {
                log.warn("질의응답 스트림이 제한 시간을 넘었습니다 user_id={} call_id={}", session.userId, callId);
                sendError(sink, "timeout");
                sink.complete();
            }
        } finally {
            session.close();
        }
    }

    void relay(PreparedAsk ask, EventSink sink, Session session) {
        try {
            InputStream in = client.open(ask);
            session.attach(in);
            boolean terminal = false;
            try (SseFrameReader reader = new SseFrameReader(in)) {
                SseFrameReader.Frame frame;
                while (!session.isClosed() && (frame = reader.next()) != null) {
                    boolean end = "done".equals(frame.event()) || "error".equals(frame.event());
                    if (end && !session.tryTerminate()) {
                        break;
                    }
                    sink.send(frame.event(), frame.data());
                    if (end) {
                        terminal = true;
                        if ("done".equals(frame.event())) {
                            logUsage(ask, frame.data());
                        }
                        break;
                    }
                }
            }
            if (!terminal && !session.isClosed() && session.tryTerminate()) {
                sendError(sink, "assistant_stream_interrupted");
                sink.complete();
            } else if (terminal) {
                sink.complete();
            }
        } catch (AssistantUnavailableException e) {
            log.warn("질의응답 서비스 호출 실패 reason={} user_id={} call_id={}", e.getMessage(), ask.userId(), ask.callId());
            if (session.tryTerminate()) {
                sendError(sink, "assistant_unavailable");
                sink.complete();
            }
        } catch (IOException | IllegalStateException e) {
            // 사용자가 연결을 끊어 전송이 실패했거나(IOException·이미 완료된 emitter), assistant 쪽 읽기가 끊겼다.
            log.info("질의응답 스트림 중단 user_id={} call_id={} cause={}", ask.userId(), ask.callId(), e.toString());
            if (!session.isClosed() && session.tryTerminate()) {
                sendError(sink, "assistant_stream_interrupted");
                sink.complete();
            }
        } catch (RuntimeException e) {
            log.error("질의응답 중계 중 예기치 않은 오류 user_id={} call_id={}", ask.userId(), ask.callId(), e);
            if (session.tryTerminate()) {
                sendError(sink, "assistant_stream_interrupted");
                sink.complete();
            }
        } finally {
            session.close();
        }
    }

    private void logUsage(PreparedAsk ask, String doneJson) {
        try {
            JsonNode done = objectMapper.readTree(doneJson);
            JsonNode usage = done.path("usage");
            log.info("assistant_usage user_id={} call_id={} status={} input_tokens={} output_tokens={} cached_tokens={} latency_ms={}",
                    ask.userId(), ask.callId(), done.path("status").asText(),
                    usage.path("input_tokens").asLong(), usage.path("output_tokens").asLong(),
                    usage.path("cached_tokens").asLong(), done.path("latency_ms").asLong());
        } catch (JsonProcessingException e) {
            // 사용량 기록 실패는 답에 영향을 주지 않는다.
            log.warn("질의응답 사용량을 읽지 못했습니다 user_id={} call_id={}", ask.userId(), ask.callId());
        }
    }

    private void sendError(EventSink sink, String code) {
        try {
            sink.send("error", objectMapper.writeValueAsString(Map.of("code", code, "message", MESSAGES.get(code))));
        } catch (IOException | IllegalStateException e) {
            // 받을 쪽이 이미 없다.
        }
    }

    private static void closeQuietly(InputStream in) {
        if (in == null) {
            return;
        }
        try {
            in.close();
        } catch (IOException ignored) {
            // 닫는 중 실패는 연결이 이미 끊겼다는 뜻이다.
        }
    }

    private record EmitterSink(SseEmitter emitter) implements EventSink {
        @Override
        public void send(String event, String data) throws IOException {
            emitter.send(SseEmitter.event().name(event).data(data));
        }

        @Override
        public void heartbeat() throws IOException {
            emitter.send(SseEmitter.event().comment(""));
        }

        @Override
        public void complete() {
            try {
                emitter.complete();
            } catch (IllegalStateException ignored) {
                // 타임아웃 등으로 이미 끝난 emitter.
            }
        }
    }
}
