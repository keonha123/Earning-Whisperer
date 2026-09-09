package com.earningwhisperer.infrastructure.demo;

import com.earningwhisperer.domain.transcript.TranscriptSegment;
import com.earningwhisperer.domain.transcript.TranscriptService;
import com.earningwhisperer.domain.transcript.TranscriptSessionRegistry;
import com.earningwhisperer.infrastructure.aiengine.AiEngineClient;
import com.earningwhisperer.infrastructure.aiengine.LiveFactCheckModels;
import com.earningwhisperer.infrastructure.websocket.FactCheckPublisher;
import com.fasterxml.jackson.databind.ObjectMapper;
import jakarta.annotation.PreDestroy;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.core.io.ClassPathResource;
import org.springframework.stereotype.Service;

import java.io.IOException;
import java.io.InputStream;
import java.time.Instant;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Future;
import java.util.concurrent.LinkedBlockingQueue;
import java.util.concurrent.RejectedExecutionException;
import java.util.concurrent.ThreadPoolExecutor;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.concurrent.atomic.AtomicLong;

/**
 * 시연용 어닝콜 재생 서비스.
 *
 * <p>준비된 스크립트를 일정 간격으로 <b>실제 인입 경로</b>({@link TranscriptService})에
 * 밀어넣는다. 프론트가 가짜 데이터를 그리는 것이 아니라, 진짜 검증을 거쳐 진짜 STOMP 로
 * 나간다. Data Pipeline 의 STT 단계만 사전 녹취록으로 대체되는 구조다.
 *
 * <p>기존 {@link DemoReplayService}(서버 기동 시 자동 시작 후 무한 반복하는 웹 쇼케이스용)
 * 와는 별개다. 이쪽은 API 로 시작하고, 1회 재생 후 스스로 끝나며, 중지할 수 있다.
 *
 * <h2>스레드 구조</h2>
 * 세션마다 스레드 2개를 쓴다.
 * <ul>
 *   <li><b>재생 스레드</b> — 세그먼트를 간격마다 발행. 트랜스크립트 표시가 최우선이므로
 *       AI Engine 응답을 절대 기다리지 않는다.</li>
 *   <li><b>팩트체크 스레드</b> — 단일 스레드. AI Engine 이 ticker 별 3문장 버퍼를 유지하고
 *       sequence 역행을 REJECTED 로 처리하므로, 제출은 <b>반드시 순서대로 직렬화</b>되어야
 *       한다. 단일 스레드 executor 가 그 순서를 보장한다.</li>
 * </ul>
 */
@Slf4j
@Service
public class DemoEarningsCallService {

    /** 이 이상 큐가 쌓이면 팩트체크가 스크립트를 따라가지 못하고 있다는 뜻이다. */
    private static final int FACT_CHECK_QUEUE_WARN_THRESHOLD = 3;

    private final TranscriptService transcriptService;
    private final AiEngineClient aiEngineClient;
    private final FactCheckPublisher factCheckPublisher;
    private final EarningsSummaryService summaryService;
    private final ObjectMapper objectMapper;
    private final String scriptPath;
    private final long intervalMs;
    /** 정상 종료 시 팩트체크 큐를 비우기 위해 기다려 줄 시간의 기준값. */
    private final long aiEngineTimeoutMs;

    /** ticker → 진행 중인 세션. 같은 종목의 중복 재생을 막는다. */
    private final Map<String, Session> sessions = new ConcurrentHashMap<>();

    /**
     * callId 유일성 보강용 카운터. 밀리초 타임스탬프만으로는 중지 직후 재시작이 같은
     * 밀리초에 걸려 callId 가 겹칠 수 있고, 그러면 TranscriptSessionRegistry 가 이전 세션의
     * 종료 상태를 보고 새 재생의 모든 세그먼트를 SESSION_ENDED 로 거부한다(조용한 실패).
     */
    private final AtomicLong callIdSequence = new AtomicLong();

    /**
     * 종합 판단 전용 스레드.
     *
     * <p>재생 스레드에서 부르지 않는 이유: 재생 종료 시 {@code session.shutdown} 이
     * playback executor 에 shutdownNow 를 걸어 자기 자신을 인터럽트한다. 그 상태에서
     * 수 초짜리 HTTP 호출을 이어 붙이면 인터럽트 플래그를 안고 도는 셈이 된다.
     * 세션 수명과 무관한 단일 스레드에 넘겨 회차마다 순서대로 처리한다.
     */
    private final ExecutorService summaryExecutor = new ThreadPoolExecutor(
            1, 1, 0L, TimeUnit.MILLISECONDS, new LinkedBlockingQueue<>(), r -> {
        Thread thread = new Thread(r, "demo-call-summary");
        thread.setDaemon(true);
        return thread;
    });

    /**
     * ticker → 마지막으로 끝난 재생의 요약. 재생이 끝나면 세션은 map 에서 사라지므로,
     * 이것이 없으면 "정상 완료", "시작한 적 없음", "첫 세그먼트부터 전부 거부되어 즉시 끝남"
     * 이 status API 에서 전부 똑같이 보인다. 시연 중 "버튼을 눌렀는데 화면에 아무것도
     * 안 나온다" 의 원인을 로그 없이 확인할 수 있게 한다.
     */
    private final Map<String, LastRun> lastRuns = new ConcurrentHashMap<>();

    /**
     * ticker → 가장 최근에 시작된 회차의 callId.
     *
     * <p>종합 판단은 재생이 끝난 뒤 수십 초까지 걸릴 수 있고, 그동안 시연자가 같은 종목을
     * 다시 재생할 수 있다. 그러면 <b>이전 회차의 판단이 새 회차 재생 도중에 발행된다</b> —
     * 어닝콜이 진행 중인데 결론 카드가 뜨는 셈이다. 발행 직전에 이 값과 대조해 막는다.
     */
    private final Map<String, String> latestCallIds = new ConcurrentHashMap<>();

    public DemoEarningsCallService(
            TranscriptService transcriptService,
            AiEngineClient aiEngineClient,
            FactCheckPublisher factCheckPublisher,
            EarningsSummaryService summaryService,
            ObjectMapper objectMapper,
            @Value("${demo.earnings-call.script-path:data/demo-earnings-call.json}") String scriptPath,
            @Value("${demo.earnings-call.interval-ms:6000}") long intervalMs,
            @Value("${ai-engine.timeout-ms:8000}") long aiEngineTimeoutMs
    ) {
        this.transcriptService = transcriptService;
        this.aiEngineClient = aiEngineClient;
        this.factCheckPublisher = factCheckPublisher;
        this.summaryService = summaryService;
        this.objectMapper = objectMapper;
        this.scriptPath = scriptPath;
        // 음수 간격은 Thread.sleep 에서 IllegalArgumentException 이 되고, 재생이 세그먼트
        // 0개로 조용히 끝난다. 설정 오타를 기동 시점에 잡는다.
        if (intervalMs < 0) {
            throw new IllegalArgumentException("demo.earnings-call.interval-ms 는 음수일 수 없습니다: " + intervalMs);
        }
        this.intervalMs = intervalMs;
        this.aiEngineTimeoutMs = Math.max(0, aiEngineTimeoutMs);
    }

    /**
     * 재생을 시작한다.
     *
     * @param requestedTicker 재생할 종목. null/공백이면 스크립트의 기본 종목을 쓴다.
     * @return 시작 결과. 이미 재생 중이면 {@link StartResult#alreadyRunning}.
     */
    public StartResult start(String requestedTicker) {
        DemoEarningsCallScript script;
        try {
            script = loadScript();
        } catch (IOException e) {
            log.error("[DemoCall] 스크립트 로드 실패 - path={} error={}", scriptPath, e.getMessage(), e);
            return StartResult.scriptUnavailable(e.getMessage());
        }
        String defect = validateSegments(script);
        if (defect != null) {
            return StartResult.scriptUnavailable(defect);
        }

        String ticker = normalizeTicker(requestedTicker, script.ticker());
        if (ticker == null) {
            return StartResult.scriptUnavailable("ticker 가 지정되지 않았고 스크립트에도 없습니다.");
        }

        // callId 는 매 회차 새로 만든다. 재사용하면 TranscriptSessionRegistry 가
        // 종료된 세션으로 보고 SESSION_ENDED 로 전부 거부한다(재생이 조용히 실패).
        String prefix = script.callIdPrefix() != null && !script.callIdPrefix().isBlank()
                ? script.callIdPrefix()
                : "demo-" + ticker.toLowerCase();
        String callId = prefix + "-" + Instant.now().toEpochMilli() + "-" + callIdSequence.incrementAndGet();

        Session created = new Session(ticker, callId, script.segments().size());
        Session existing = sessions.putIfAbsent(ticker, created);
        if (existing != null) {
            // putIfAbsent 실패 = 이 Session 은 쓰이지 않는다. 생성자가 만든 executor 2개를
            // 반드시 회수한다. 버튼 연타 시 요청마다 누적되기 때문이다.
            created.shutdown(0);
            return StartResult.alreadyRunning(existing.ticker, existing.callId);
        }

        latestCallIds.put(ticker, callId);
        try {
            created.playbackFuture = created.playback.submit(() -> runPlayback(created, script));
        } catch (RuntimeException e) {
            // 재생 스레드를 못 띄웠는데 세션이 map 에 남으면 이후 start 가 영원히
            // ALREADY_RUNNING 을 반환한다.
            sessions.remove(ticker, created);
            created.shutdown(0);
            log.error("[DemoCall] 재생 스레드 기동 실패 - ticker={} error={}", ticker, e.getMessage(), e);
            return StartResult.scriptUnavailable("재생을 시작하지 못했습니다: " + e.getMessage());
        }
        if (script.segments().size() % 3 != 0 && aiEngineClient.isFactCheckEnabled()) {
            // AI Engine 은 3문장 단위로 검증한다. 나머지 1~2문장은 DISCARDED 되어
            // 마지막 발언들의 팩트체크가 나오지 않는다.
            log.warn("[DemoCall] 세그먼트 수가 3의 배수가 아닙니다 - count={} 나머지 {}문장은 "
                    + "팩트체크되지 않습니다", script.segments().size(), script.segments().size() % 3);
        }
        log.info("[DemoCall] 재생 시작 - ticker={} call_id={} segments={} interval={}ms factCheck={}",
                ticker, callId, script.segments().size(), intervalMs, aiEngineClient.isFactCheckEnabled());
        return StartResult.started(ticker, callId, script.segments().size(), intervalMs);
    }

    /** 재생을 중지한다. 진행 중인 세션이 없으면 false. */
    public boolean stop(String ticker) {
        String key = normalizeKey(ticker);
        if (key == null) {
            return false;
        }
        Session session = sessions.get(key);
        if (session == null) {
            return false;
        }
        session.stopRequested.set(true);
        if (session.playbackFuture != null) {
            session.playbackFuture.cancel(true);
        }
        // grace 0 — 중지는 HTTP 워커 스레드에서 호출된다. 여기서 기다리면 "중지" 버튼이
        // 멈춘 것처럼 보인다. 큐에 남은 팩트체크는 어차피 stopRequested 로 버려진다.
        session.shutdown(0);
        recordLastRun(session, "STOPPED");
        sessions.remove(key, session);
        log.info("[DemoCall] 재생 중지 - ticker={} call_id={}", session.ticker, session.callId);
        return true;
    }

    /** 진행 중인 세션 상태. 없으면 empty. */
    public Optional<Status> status(String ticker) {
        String key = normalizeKey(ticker);
        if (key == null) {
            return Optional.empty();
        }
        return Optional.ofNullable(sessions.get(key))
                .map(s -> new Status(s.ticker, s.callId, s.publishedCount, s.totalSegments));
    }

    /** 마지막으로 끝난 재생의 요약. 재생한 적이 없으면 empty. */
    public Optional<LastRun> lastRun(String ticker) {
        String key = normalizeKey(ticker);
        return key == null ? Optional.empty() : Optional.ofNullable(lastRuns.get(key));
    }

    private void recordLastRun(Session session, String outcome) {
        lastRuns.put(session.ticker, new LastRun(
                session.ticker, session.callId, outcome, session.publishedCount, session.totalSegments));
        if ("NO_SEGMENT_PUBLISHED".equals(outcome)) {
            // 스크립트가 잘못되었거나 인입이 전부 거부된 경우. 조용히 넘기면 안 된다.
            log.error("[DemoCall] 세그먼트를 하나도 발행하지 못하고 종료 - ticker={} call_id={} "
                    + "(스크립트 sequence 또는 인입 검증을 확인하세요)", session.ticker, session.callId);
        }
    }

    private static String normalizeKey(String ticker) {
        return ticker == null || ticker.isBlank() ? null : ticker.trim().toUpperCase();
    }

    private void runPlayback(Session session, DemoEarningsCallScript script) {
        try {
            int lastIndex = script.segments().size() - 1;
            for (int i = 0; i <= lastIndex; i++) {
                if (session.stopRequested.get() || Thread.currentThread().isInterrupted()) {
                    return;
                }
                DemoEarningsCallScript.Segment raw = script.segments().get(i);
                boolean isLast = i == lastIndex;
                long nowEpochSecond = Instant.now().getEpochSecond();

                TranscriptSegment segment = new TranscriptSegment(
                        session.ticker,
                        session.callId,
                        raw.sequence(),
                        raw.startMs(),
                        raw.endMs(),
                        raw.text(),
                        raw.speaker(),
                        nowEpochSecond,
                        isLast
                );

                // 루프 상단 체크 이후 중지가 들어왔을 수 있다. 발행 직전에 한 번 더 본다 —
                // 옛 세션의 세그먼트가 새 callId 세그먼트 사이에 끼는 창을 좁힌다.
                if (session.stopRequested.get()) {
                    return;
                }
                TranscriptSessionRegistry.Result result = transcriptService.accept(segment);
                if (result != TranscriptSessionRegistry.Result.OK) {
                    // 스크립트가 잘못되었다는 뜻(sequence 중복 등). 조용히 넘기면 원인을 못 찾는다.
                    log.warn("[DemoCall] 세그먼트 거부 - ticker={} sequence={} reason={}",
                            session.ticker, raw.sequence(), result);
                } else {
                    session.publishedCount = i + 1;
                    submitForFactCheck(session, raw, nowEpochSecond, isLast);
                }

                if (!isLast) {
                    Thread.sleep(intervalMs);
                }
            }
            log.info("[DemoCall] 재생 완료 - ticker={} call_id={}", session.ticker, session.callId);
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
            log.info("[DemoCall] 재생 인터럽트 - ticker={} call_id={}", session.ticker, session.callId);
        } catch (Exception e) {
            log.error("[DemoCall] 재생 중 오류 - ticker={} call_id={} error={}",
                    session.ticker, session.callId, e.getMessage(), e);
        } finally {
            // 정상 종료 시에는 마지막 문장의 팩트체크가 아직 큐/호출 중이다. 여기서 바로
            // 끊으면 그 배치(마지막 3문장 = is_session_end 플러시)가 통째로 사라지고,
            // 실패가 로그 한 줄로만 남아 시연 중 원인을 찾을 수 없다.
            // AI Engine 타임아웃보다 넉넉히 기다린 뒤 종료한다.
            // 중지 경로는 이미 stop() 이 grace 0 으로 정리했으므로 여기서는 남은 것이 없다.
            // stopRequested 를 한 번만 읽는다. 세 곳에서 따로 읽으면, 마지막 세그먼트가
            // 나간 직후 중지 버튼이 눌린 순간에 "COMPLETED 로 기록됐는데 종합 판단은
            // 안 나가는" 상태가 만들어진다. 콜은 다 재생됐는데 결론이 없는 셈이다.
            boolean stopped = session.stopRequested.get();

            // 종합 판단은 shutdown 보다 <b>먼저</b> 제출한다. 이유가 둘이다.
            //  (1) 정상 경로의 grace 는 AI Engine 타임아웃 + 2초라 기본 설정에서 52초다.
            //      뒤에 두면 종합 판단이 그만큼 늦게 시작한다.
            //  (2) shutdown 안의 playback.shutdownNow() 가 이 스레드를 인터럽트한다.
            //      인터럽트된 스레드에서 executor 에 제출하는 상태를 만들지 않는다.
            // 요약 태스크는 다른 스레드에서 돌고 script 는 불변이라 순서를 앞당겨도 안전하다.
            if (!stopped && session.publishedCount > 0) {
                submitSummary(session, script);
            }

            long grace = stopped ? 0 : aiEngineTimeoutMs + 2_000;
            session.shutdown(grace);
            if (!stopped) {
                recordLastRun(session, session.publishedCount == 0 ? "NO_SEGMENT_PUBLISHED" : "COMPLETED");
            }
            sessions.remove(session.ticker, session);
        }
    }

    /**
     * 종합 판단 생성을 전용 스레드에 넘긴다. 실패해도 재생 종료 자체는 이미 끝났다.
     */
    private void submitSummary(Session session, DemoEarningsCallScript script) {
        try {
            // submit 이 아니라 execute 다. submit 은 Throwable 을 아무도 보지 않는 Future 에
            // 가둬 버려서 Error 계열이 로그 한 줄 없이 사라진다. 팩트체크 제출도 execute 를 쓴다.
            summaryExecutor.execute(() -> {
                // 이 태스크가 큐에서 기다리는 동안 같은 종목이 다시 재생을 시작했을 수 있다.
                // 그대로 발행하면 진행 중인 어닝콜 위에 지난 회차의 결론이 덮인다.
                String latest = latestCallIds.get(session.ticker);
                if (latest != null && !latest.equals(session.callId)) {
                    log.warn("[DemoCall] 지난 회차의 종합 판단을 버립니다 - ticker={} call_id={} 최신={}",
                            session.ticker, session.callId, latest);
                    return;
                }
                try {
                    summaryService.summarizeAndPublish(session.ticker, session.callId, script);
                } catch (Throwable e) {
                    // Exception 만 잡으면 Error 계열이 스레드를 조용히 죽이고, 다음 회차부터
                    // 종합 판단이 통째로 사라진다.
                    log.error("[DemoCall] 종합 판단 실패 - ticker={} call_id={} error={}",
                            session.ticker, session.callId, e.toString(), e);
                }
            });
        } catch (RejectedExecutionException e) {
            // 종료 중. 시연이 끝나는 상황이므로 경고로 충분하다.
            log.warn("[DemoCall] 종합 판단을 제출하지 못했습니다(종료 중) - ticker={} call_id={} error={}",
                    session.ticker, session.callId, e.toString());
        }
    }

    /**
     * 팩트체크 제출을 팩트체크 스레드에 넘긴다. 재생 스레드는 여기서 대기하지 않는다.
     * 큐잉 순서가 곧 제출 순서이고, 단일 스레드가 그 순서를 유지한다.
     */
    private void submitForFactCheck(Session session, DemoEarningsCallScript.Segment raw,
                                    long timestamp, boolean isLast) {
        if (!aiEngineClient.isFactCheckEnabled()) {
            return;
        }
        LiveFactCheckModels.SentenceRequest request = new LiveFactCheckModels.SentenceRequest(
                session.ticker, raw.text(), raw.sequence(), timestamp, isLast);
        int queued = session.factCheck.getQueue().size();
        if (queued >= FACT_CHECK_QUEUE_WARN_THRESHOLD) {
            log.warn("[DemoCall] 팩트체크 큐 적체 - ticker={} queued={} (AI Engine 응답이 재생 간격보다 느립니다. "
                    + "카드가 스크립트보다 점점 뒤처집니다)", session.ticker, queued);
        }
        try {
            session.factCheck.execute(() -> {
                if (session.stopRequested.get()) {
                    return;
                }
                aiEngineClient.submitSentence(request)
                        .ifPresent(batch -> factCheckPublisher.publish(session.ticker, session.callId, batch));
            });
        } catch (RejectedExecutionException e) {
            // 중지 직후의 정상 상황. 재생은 계속되어야 한다.
            log.debug("[DemoCall] 팩트체크 제출 생략(종료 중) - ticker={} sequence={}",
                    session.ticker, raw.sequence());
        } catch (Exception e) {
            log.warn("[DemoCall] 팩트체크 제출 실패 - ticker={} sequence={} error={}",
                    session.ticker, raw.sequence(), e.toString());
        }
    }

    /**
     * 스크립트 세그먼트를 검증한다. 문제가 없으면 null, 있으면 사유 문자열.
     *
     * <p>여기서 잡지 않으면 시연 당일에야 드러나는 것들이다.
     * <ul>
     *   <li>sequence 가 0 에서 시작하지 않으면 AI Engine 의 ticker 버퍼가 초기화되지 않는다.
     *       AI Engine 은 callId 가 아니라 ticker 로 버퍼를 잡고 {@code sentence_sequence=0}
     *       에서만 리셋하므로, 중지 후 재시작 시 트랜스크립트는 정상인데 팩트체크만 전부
     *       REJECTED 로 조용히 사라진다.</li>
     *   <li>sequence 가 1씩 증가하지 않으면 TranscriptSessionRegistry 가 거부한다.</li>
     * </ul>
     */
    static String validateSegments(DemoEarningsCallScript script) {
        List<DemoEarningsCallScript.Segment> segments = script.segments();
        if (segments == null || segments.isEmpty()) {
            return "스크립트에 세그먼트가 없습니다.";
        }
        for (int i = 0; i < segments.size(); i++) {
            DemoEarningsCallScript.Segment segment = segments.get(i);
            if (segment.sequence() != i) {
                return "세그먼트 sequence 는 0 부터 1씩 증가해야 합니다. index=" + i
                        + " sequence=" + segment.sequence();
            }
            if (segment.text() == null || segment.text().isBlank()) {
                return "세그먼트 text 가 비어 있습니다. sequence=" + segment.sequence();
            }
        }
        return null;
    }

    DemoEarningsCallScript loadScript() throws IOException {
        try (InputStream in = new ClassPathResource(scriptPath).getInputStream()) {
            return objectMapper.readValue(in, DemoEarningsCallScript.class);
        }
    }

    private static String normalizeTicker(String requested, String fallback) {
        if (requested != null && !requested.isBlank()) {
            return requested.trim().toUpperCase();
        }
        if (fallback != null && !fallback.isBlank()) {
            return fallback.trim().toUpperCase();
        }
        return null;
    }

    @PreDestroy
    void shutdownAll() {
        sessions.values().forEach(session -> {
            session.stopRequested.set(true);
            if (session.playbackFuture != null) {
                session.playbackFuture.cancel(true);
            }
            session.shutdown(0);
        });
        sessions.clear();
        lastRuns.clear();
        latestCallIds.clear();
        shutdownSummaryExecutor();
    }

    /**
     * 종합 판단 스레드 회수.
     *
     * <p>그냥 shutdownNow 만 하면 "마지막 회차 종합 판단이 안 왔다" 의 원인이 로그에
     * 아무것도 남지 않는다. 짧게 한 번 기다려 보고, 그래도 남은 것이 있으면 몇 건인지 남긴다.
     */
    private void shutdownSummaryExecutor() {
        summaryExecutor.shutdown();
        try {
            if (!summaryExecutor.awaitTermination(1_500, TimeUnit.MILLISECONDS)) {
                List<Runnable> dropped = summaryExecutor.shutdownNow();
                log.warn("[DemoCall] 종료 중 종합 판단 {}건을 버렸습니다(진행 중 1건 포함 가능)",
                        dropped.size());
            }
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
            summaryExecutor.shutdownNow();
        }
    }

    /** 재생 1회분의 상태와 전용 스레드. */
    private static final class Session {
        final String ticker;
        final String callId;
        final int totalSegments;
        final AtomicBoolean stopRequested = new AtomicBoolean(false);
        final ExecutorService playback;
        /** 큐 깊이를 관찰해야 하므로 ThreadPoolExecutor 로 직접 만든다. */
        final ThreadPoolExecutor factCheck;
        volatile Future<?> playbackFuture;
        volatile int publishedCount;

        Session(String ticker, String callId, int totalSegments) {
            this.ticker = ticker;
            this.callId = callId;
            this.totalSegments = totalSegments;
            this.playback = singleThread("demo-call-play-" + ticker);
            this.factCheck = singleThread("demo-call-fc-" + ticker);
        }

        /**
         * executor 2개를 종료한다.
         *
         * <p>{@code graceMillis} 는 <b>팩트체크 큐</b>에만 적용된다. 0 이면 대기 없이 즉시
         * 폐기한다(중지 경로 — HTTP 워커 스레드를 붙들지 않기 위해). 정상 종료 경로에서는
         * 마지막 배치가 유실되지 않도록 AI Engine 타임아웃보다 넉넉한 값을 넘긴다.
         *
         * <p>주의: 이 메서드는 재생 스레드 자신이 호출하기도 한다. 따라서 여기에
         * {@code playback.awaitTermination} 을 추가하면 자기 자신을 기다리는 데드락이 된다.
         */
        void shutdown(long graceMillis) {
            factCheck.shutdown();
            playback.shutdown();
            if (graceMillis > 0) {
                try {
                    if (!factCheck.awaitTermination(graceMillis, TimeUnit.MILLISECONDS)) {
                        log.warn("[DemoCall] 팩트체크 큐를 {}ms 내에 비우지 못했습니다 - ticker={} 남은 작업={}",
                                graceMillis, ticker, factCheck.getQueue().size());
                    }
                } catch (InterruptedException e) {
                    Thread.currentThread().interrupt();
                }
            }
            factCheck.shutdownNow();
            playback.shutdownNow();
        }

        private static ThreadPoolExecutor singleThread(String name) {
            return new ThreadPoolExecutor(1, 1, 0L, TimeUnit.MILLISECONDS,
                    new LinkedBlockingQueue<>(), r -> {
                Thread t = new Thread(r, name);
                t.setDaemon(true);
                return t;
            });
        }
    }

    /** 재생 시작 결과. */
    public record StartResult(
            Outcome outcome,
            String ticker,
            String callId,
            int segmentCount,
            long intervalMs,
            String message
    ) {
        public enum Outcome { STARTED, ALREADY_RUNNING, SCRIPT_UNAVAILABLE }

        static StartResult started(String ticker, String callId, int segmentCount, long intervalMs) {
            return new StartResult(Outcome.STARTED, ticker, callId, segmentCount, intervalMs, null);
        }

        static StartResult alreadyRunning(String ticker, String callId) {
            return new StartResult(Outcome.ALREADY_RUNNING, ticker, callId, 0, 0,
                    "이미 재생 중입니다. 먼저 중지하세요.");
        }

        static StartResult scriptUnavailable(String message) {
            return new StartResult(Outcome.SCRIPT_UNAVAILABLE, null, null, 0, 0, message);
        }
    }

    /** 진행 중인 재생의 상태. */
    public record Status(String ticker, String callId, int publishedCount, int totalSegments) {
    }

    /**
     * 마지막으로 끝난 재생의 요약.
     *
     * @param outcome COMPLETED / STOPPED / NO_SEGMENT_PUBLISHED
     */
    public record LastRun(String ticker, String callId, String outcome,
                          int publishedCount, int totalSegments) {
    }
}
