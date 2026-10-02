package com.earningwhisperer.domain.transcript;

import com.earningwhisperer.infrastructure.aiengine.AiEngineClient;
import com.earningwhisperer.infrastructure.aiengine.LiveFactCheckModels;
import com.earningwhisperer.infrastructure.websocket.FactCheckPublisher;
import jakarta.annotation.PreDestroy;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;
import java.util.concurrent.*;

/** Internal live ingress only. Demo owns its existing submission loop and must not call this service. */
@Slf4j
@Service
public class LiveTranscriptFactCheckService {
    private final TranscriptService transcripts;
    private final AiEngineClient client;
    private final FactCheckPublisher publisher;
    private final ThreadPoolExecutor[] lanes = new ThreadPoolExecutor[4];

    public LiveTranscriptFactCheckService(TranscriptService transcripts, AiEngineClient client, FactCheckPublisher publisher) {
        this.transcripts = transcripts; this.client = client; this.publisher = publisher;
        for (int i = 0; i < lanes.length; i++) {
            final int index = i;
            lanes[i] = new ThreadPoolExecutor(1, 1, 0, TimeUnit.MILLISECONDS, new ArrayBlockingQueue<>(128),
                    r -> { Thread t = new Thread(r, "live-factcheck-" + index); t.setDaemon(true); return t; });
        }
    }

    public TranscriptSessionRegistry.Result accept(TranscriptSegment segment) {
        ThreadPoolExecutor lane = lanes[Math.floorMod(segment.ticker().hashCode(), lanes.length)];
        // Validation and enqueue share a lock: concurrent HTTP requests cannot invert accepted sequences.
        synchronized (lane) {
            var result = transcripts.accept(segment);
            if (result != TranscriptSessionRegistry.Result.OK || !client.isFactCheckEnabled()) return result;
            try {
                lane.execute(() -> {
                    var request = new LiveFactCheckModels.SentenceRequest(segment.ticker(), segment.text(),
                            segment.sequence(), segment.timestamp(), segment.isSessionEnd(), segment.callId());
                    client.submitSentence(request).filter(batch -> segment.ticker().equals(batch.ticker()))
                            .ifPresent(batch -> publisher.publish(segment.ticker(), segment.callId(), batch));
                });
            } catch (RejectedExecutionException rejected) {
                log.warn("[LiveFactCheck] Queue full/stopping; original transcript retained: ticker={} call={} sequence={}",
                        segment.ticker(), segment.callId(), segment.sequence());
            }
            return result;
        }
    }

    @PreDestroy public void close() {
        for (ThreadPoolExecutor lane : lanes) lane.shutdownNow();
    }
}
