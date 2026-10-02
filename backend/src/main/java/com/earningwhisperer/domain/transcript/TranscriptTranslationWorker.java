package com.earningwhisperer.domain.transcript;
import com.earningwhisperer.infrastructure.aiengine.AiEngineClient;
import com.earningwhisperer.infrastructure.glossary.GlossaryService;
import com.earningwhisperer.infrastructure.websocket.TranscriptPublisher;
import jakarta.annotation.PreDestroy;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;
import java.util.Map;
import java.util.concurrent.*;

/** Separate bounded workers keep STT and fact checking independent of translation latency. */
@Component
public class TranscriptTranslationWorker {
    private final AiEngineClient client;
    private final TranscriptPublisher publisher;
    private final boolean enabled;
    private final GlossaryService glossary;
    private final ThreadPoolExecutor executor = new ThreadPoolExecutor(2, 2, 0, TimeUnit.MILLISECONDS,
            new ArrayBlockingQueue<>(128), r -> { Thread t = new Thread(r, "transcript-translation"); t.setDaemon(true); return t; });
    public TranscriptTranslationWorker(AiEngineClient client, TranscriptPublisher publisher, GlossaryService glossary,
            @Value("${ai-engine.translation-enabled:true}") boolean enabled) {
        this.client = client; this.publisher = publisher; this.glossary = glossary; this.enabled = enabled;
    }
    public void submit(TranscriptSegment s) {
        if (!enabled || s.text().isBlank()) return;
        try {
            executor.execute(() -> client.transcriptRequest("/v1/engine/transcript/translate", Map.of(
                    "ticker", s.ticker(), "call_id", s.callId(), "sequence", s.sequence(), "text", s.text(),
                    "terms", glossary.matchingTerms(s.text()).stream().map(t -> Map.of(
                            "term", t.term(), "aliases", t.aliases(), "ko", t.ko())).toList())).ifPresent(r -> {
                if (r.path("available").asBoolean() && r.path("text_ko").isTextual()
                        && r.path("ticker").asText().equals(s.ticker()) && r.path("call_id").asText().equals(s.callId())
                        && r.path("sequence").asInt(-1) == s.sequence() && r.path("original_text").asText().equals(s.text()))
                    publisher.publishTranslation(s, r.path("text_ko").asText());
            }));
        } catch (RejectedExecutionException ignored) { /* Original STT remains available under overload. */ }
    }
    @PreDestroy public void close() { executor.shutdownNow(); }
}
