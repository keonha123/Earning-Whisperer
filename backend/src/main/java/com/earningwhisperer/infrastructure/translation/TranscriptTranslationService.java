package com.earningwhisperer.infrastructure.translation;

import com.earningwhisperer.domain.transcript.TranscriptSegment;
import com.earningwhisperer.infrastructure.aiengine.AiEngineClient;
import com.earningwhisperer.infrastructure.aiengine.TranscriptTranslationModels;
import com.earningwhisperer.infrastructure.glossary.GlossaryService;
import com.earningwhisperer.infrastructure.websocket.TranscriptTranslationPublisher;
import jakarta.annotation.PreDestroy;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;

import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.TreeMap;
import java.util.concurrent.Executor;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.RejectedExecutionException;
import java.util.concurrent.ScheduledExecutorService;
import java.util.concurrent.TimeUnit;
import java.util.function.LongSupplier;

/**
 * 어닝콜 자막을 몇 문장씩 묶어 AI Engine 에 번역을 요청하고, 결과를 터미널로 발행한다(#110).
 *
 * <p>시연 재생과 실제 STT 인입이 모두 {@code TranscriptService} 를 지나므로 그 자리에서 받는다.
 *
 * <p><b>묶는 이유</b>: Gemini 무료 등급은 모델별 분당 15요청이고, 직전 콜 대조 · 팩트체크와 함께 쓴다.
 * 세그먼트마다 부르면 시연(6초 간격) 기준 번역만 분당 10요청이다. 아래 조건 중 하나가 되면 묶음을 보낸다.
 * <ul>
 *   <li>세그먼트 {@code batch-max-segments} 개가 모였을 때</li>
 *   <li>글자 수가 {@code batch-max-chars} 에 닿았을 때</li>
 *   <li>묶음의 첫 세그먼트가 들어온 지 {@code batch-max-wait-ms} 가 지났을 때 — 발언이 끊겨도 번역이 늦게 남지 않게</li>
 *   <li>세션 종료 세그먼트가 들어왔을 때</li>
 * </ul>
 *
 * <p><b>지연</b>: 번역 호출은 자막 발행 스레드가 아니라 전용 단일 스레드에서 순서대로 돈다. 원문 자막은 번역을
 * 기다리지 않는다. 직전 콜 대조와도 다른 스레드라 서로 기다리지 않는다. Gemini 가 느려 밀린 묶음이
 * {@code max-age-ms} 를 넘으면 보내지 않고 버린다 — 지나간 자막의 번역이 한참 뒤에 나오면 읽는 흐름을 깬다.
 * 기준은 묶음이 대기열에 들어간 시각이다.
 *
 * <p><b>순서</b>: 실제 STT 인입은 HTTP 스레드 여럿에서 들어와 {@code submit} 순서가 sequence 순서와 어긋날 수
 * 있다. 묶음 안에서는 sequence 순으로 정렬하고, 묶음을 대기열에 넣는 일은 락 안에서 해 묶음 간 순서도 지킨다.
 *
 * <p>실패(비활성화 · 호출 실패 · 번역 실패)는 로그만 남기고 발행하지 않는다. 원문을 번역 대신 내보내지 않는다.
 */
@Slf4j
@Service
public class TranscriptTranslationService {

    /** 엔진 계약(Contract 9.10) 상한. */
    static final int MAX_TERMS = 50;
    static final int MAX_TEXT_CHARS = 4000;

    /** 묶음 만료 타이머. 테스트에서 시간을 직접 돌리려고 분리했다. */
    interface Scheduler {
        void schedule(Runnable task, long delayMs);
    }

    private final AiEngineClient aiEngineClient;
    private final GlossaryService glossaryService;
    private final TranscriptTranslationPublisher publisher;
    private final int maxSegments;
    private final int maxChars;
    private final long maxWaitMs;
    private final long maxAgeMs;
    private final Scheduler scheduler;
    private final Executor worker;
    private final LongSupplier nowMs;
    private final List<ExecutorService> owned = new ArrayList<>();

    /** ticker + call_id → 아직 보내지 않은 묶음. {@code this} 로 동기화한다. */
    private final Map<String, Batch> pending = new HashMap<>();

    @Autowired
    public TranscriptTranslationService(
            AiEngineClient aiEngineClient,
            GlossaryService glossaryService,
            TranscriptTranslationPublisher publisher,
            @Value("${transcript-translation.batch-max-segments:3}") int maxSegments,
            @Value("${transcript-translation.batch-max-chars:1200}") int maxChars,
            @Value("${transcript-translation.batch-max-wait-ms:10000}") long maxWaitMs,
            @Value("${transcript-translation.max-age-ms:30000}") long maxAgeMs) {
        this(aiEngineClient, glossaryService, publisher, maxSegments, maxChars, maxWaitMs, maxAgeMs,
                null, null, System::currentTimeMillis);
    }

    /** 테스트용. scheduler · worker 가 null 이면 데몬 스레드로 만든다. */
    TranscriptTranslationService(
            AiEngineClient aiEngineClient,
            GlossaryService glossaryService,
            TranscriptTranslationPublisher publisher,
            int maxSegments, int maxChars, long maxWaitMs, long maxAgeMs,
            Scheduler scheduler, Executor worker, LongSupplier nowMs) {
        if (maxSegments < 1 || maxChars < 1 || maxChars > MAX_TEXT_CHARS || maxWaitMs < 1 || maxAgeMs < 1) {
            throw new IllegalArgumentException("transcript-translation 설정이 올바르지 않습니다: batch-max-segments="
                    + maxSegments + " batch-max-chars=" + maxChars + "(최대 " + MAX_TEXT_CHARS + ") batch-max-wait-ms="
                    + maxWaitMs + " max-age-ms=" + maxAgeMs);
        }
        this.aiEngineClient = aiEngineClient;
        this.glossaryService = glossaryService;
        this.publisher = publisher;
        this.maxSegments = maxSegments;
        this.maxChars = maxChars;
        this.maxWaitMs = maxWaitMs;
        this.maxAgeMs = maxAgeMs;
        this.nowMs = nowMs;
        if (scheduler == null) {
            ScheduledExecutorService timer = Executors.newSingleThreadScheduledExecutor(daemon("transcript-translate-timer"));
            owned.add(timer);
            scheduler = (task, delayMs) -> timer.schedule(task, delayMs, TimeUnit.MILLISECONDS);
        }
        if (worker == null) {
            ExecutorService single = Executors.newSingleThreadExecutor(daemon("transcript-translate"));
            owned.add(single);
            worker = single;
        }
        this.scheduler = scheduler;
        this.worker = worker;
        log.info("[Translation] 번역 연결 - enabled={} batchMaxSegments={} batchMaxChars={} batchMaxWaitMs={} maxAgeMs={}",
                aiEngineClient.isTranslationEnabled(), maxSegments, maxChars, maxWaitMs, maxAgeMs);
    }

    /**
     * 발행된 자막 세그먼트를 받는다. 자막 발행 스레드에서 불리므로 바로 돌아온다.
     */
    public void submit(TranscriptSegment segment) {
        if (!aiEngineClient.isTranslationEnabled() || segment == null) {
            return;
        }
        String text = segment.text() == null ? "" : segment.text().strip();
        if (text.isEmpty()) {
            return;
        }
        String key = segment.ticker() + "|" + segment.callId();
        synchronized (this) {
            Batch batch = pending.get(key);
            if (batch != null && batch.chars + 1 + text.length() > maxChars) {
                // 붙이면 상한을 넘는다. 지금까지 모은 것을 먼저 보낸다.
                pending.remove(key);
                dispatch(batch);
                batch = null;
            }
            if (batch == null) {
                batch = new Batch(segment.ticker(), segment.callId());
                pending.put(key, batch);
                Batch scheduled = batch;
                try {
                    scheduler.schedule(() -> expire(key, scheduled), maxWaitMs);
                } catch (RejectedExecutionException e) {
                    // 종료 중. 타이머가 없으면 이 묶음은 영영 나가지 않으므로 받지 않는다.
                    pending.remove(key);
                    return;
                }
            }
            batch.add(segment.sequence(), text);
            if (batch.size() >= maxSegments || batch.chars >= maxChars || segment.isSessionEnd()) {
                pending.remove(key);
                dispatch(batch);
            }
        }
    }

    private void expire(String key, Batch batch) {
        synchronized (this) {
            if (pending.get(key) != batch) {
                return; // 이미 다른 조건으로 보냈다
            }
            pending.remove(key);
            dispatch(batch);
        }
    }

    /** 락 안에서 부른다. 단일 스레드 대기열은 무제한이라 execute 가 막히지 않는다. */
    private void dispatch(Batch batch) {
        batch.dispatchedAtMs = nowMs.getAsLong();
        try {
            worker.execute(() -> translate(batch));
        } catch (RejectedExecutionException e) {
            log.warn("[Translation] 종료 중이라 번역을 건너뜁니다 - ticker={} call_id={} sequences={}",
                    batch.ticker, batch.callId, batch.sequences());
        }
    }

    void translate(Batch batch) {
        try {
            long waited = nowMs.getAsLong() - batch.dispatchedAtMs;
            if (waited > maxAgeMs) {
                log.warn("[Translation] 너무 늦어 번역을 버립니다 - ticker={} call_id={} sequences={} waited={}ms",
                        batch.ticker, batch.callId, batch.sequences(), waited);
                return;
            }
            String text = clip(batch.text(), MAX_TEXT_CHARS);
            List<TranscriptTranslationModels.Term> terms = glossaryService.findTerms(text, MAX_TERMS).stream()
                    .map(m -> new TranscriptTranslationModels.Term(m.spelling(), m.ko()))
                    .toList();
            List<Integer> sequences = batch.sequences();
            TranscriptTranslationModels.TranslateRequest request = new TranscriptTranslationModels.TranslateRequest(
                    batch.ticker, batch.callId, sequences.get(0), text, terms);
            aiEngineClient.translate(request).ifPresent(response -> {
                if (!response.hasText()) {
                    log.warn("[Translation] 번역 실패 - ticker={} call_id={} sequences={} warnings={}",
                            batch.ticker, batch.callId, sequences, response.warnings());
                    return;
                }
                if (response.sequence() != request.sequence()) {
                    log.warn("[Translation] 다른 세그먼트의 번역이 돌아와 버립니다 - ticker={} 요청={} 응답={}",
                            batch.ticker, request.sequence(), response.sequence());
                    return;
                }
                publisher.publish(TranscriptTranslationPublisher.Payload.builder()
                        .ticker(batch.ticker)
                        .callId(batch.callId)
                        .sequences(sequences)
                        .textKo(response.textKo())
                        .termsUsed(response.termsUsed() == null ? List.of() : List.copyOf(response.termsUsed()))
                        .build());
            });
        } catch (Exception e) {
            // 단일 스레드 executor 에서 예외가 새면 이 묶음만 사라지지만, 원인은 남겨야 한다.
            log.error("[Translation] 번역 처리 오류 - ticker={} call_id={} sequences={}",
                    batch.ticker, batch.callId, batch.sequences(), e);
        }
    }

    /** 서로게이트 쌍 가운데를 자르지 않는다. */
    static String clip(String text, int limit) {
        if (text.length() <= limit) {
            return text;
        }
        int end = Character.isHighSurrogate(text.charAt(limit - 1)) ? limit - 1 : limit;
        return text.substring(0, end);
    }

    @PreDestroy
    void shutdown() {
        owned.forEach(ExecutorService::shutdownNow);
    }

    private static java.util.concurrent.ThreadFactory daemon(String name) {
        return r -> {
            Thread t = new Thread(r, name);
            t.setDaemon(true);
            return t;
        };
    }

    /**
     * 아직 보내지 않은 세그먼트 묶음. 추가는 서비스 락 안에서만 하고, 대기열에 넣은 뒤에는 바꾸지 않는다.
     * 세그먼트는 sequence 순으로 정렬해 둔다.
     */
    static final class Batch {
        final String ticker;
        final String callId;
        private final TreeMap<Integer, String> texts = new TreeMap<>();
        int chars;
        volatile long dispatchedAtMs;

        Batch(String ticker, String callId) {
            this.ticker = ticker;
            this.callId = callId;
        }

        void add(int sequence, String text) {
            chars += (texts.isEmpty() ? 0 : 1) + text.length();
            texts.put(sequence, text);
        }

        int size() {
            return texts.size();
        }

        List<Integer> sequences() {
            return List.copyOf(texts.keySet());
        }

        String text() {
            return String.join(" ", texts.values());
        }
    }
}
