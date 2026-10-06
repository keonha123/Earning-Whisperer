package com.earningwhisperer.infrastructure.translation;

import com.earningwhisperer.domain.transcript.TranscriptSegment;
import com.earningwhisperer.infrastructure.aiengine.AiEngineClient;
import com.earningwhisperer.infrastructure.aiengine.TranscriptTranslationModels;
import com.earningwhisperer.infrastructure.glossary.GlossaryService;
import com.earningwhisperer.infrastructure.websocket.TranscriptTranslationPublisher;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.util.ArrayList;
import java.util.List;
import java.util.Optional;
import java.util.concurrent.CopyOnWriteArrayList;
import java.util.concurrent.atomic.AtomicLong;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatCode;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

/**
 * TranscriptTranslationService 단위 테스트.
 *
 * 타이머와 작업 스레드를 가짜로 바꿔 시간을 직접 돌린다. 묶는 조건, 늦은 묶음 버리기,
 * 실패 시 발행하지 않는 것을 확인한다.
 */
@DisplayName("TranscriptTranslationService")
class TranscriptTranslationServiceTest {

    private static final GlossaryService GLOSSARY = new GlossaryService(new ObjectMapper(), "data/glossary_ko.json");

    private final AtomicLong now = new AtomicLong(1_000_000L);
    private final List<Runnable> timers = new ArrayList<>();
    private final List<Long> timerDelays = new ArrayList<>();
    private final List<Runnable> queued = new ArrayList<>();
    private final List<TranscriptTranslationPublisher.Payload> published = new CopyOnWriteArrayList<>();
    private StubClient client;

    @BeforeEach
    void setUp() {
        client = new StubClient(true);
    }

    private TranscriptTranslationService service() {
        return service(client);
    }

    private TranscriptTranslationService service(AiEngineClient aiEngineClient) {
        return service(aiEngineClient, 200);
    }

    private TranscriptTranslationService service(AiEngineClient aiEngineClient, int maxChars) {
        TranscriptTranslationPublisher publisher = new TranscriptTranslationPublisher(null) {
            @Override
            public void publish(Payload payload) {
                published.add(payload);
            }
        };
        return new TranscriptTranslationService(aiEngineClient, GLOSSARY, publisher,
                3, maxChars, 10_000, 30_000,
                (task, delayMs) -> {
                    timers.add(task);
                    timerDelays.add(delayMs);
                },
                queued::add,
                now::get);
    }

    private static TranscriptSegment segment(int sequence, String text) {
        return segment("demo-1", sequence, text, false);
    }

    private static TranscriptSegment segment(String callId, int sequence, String text, boolean end) {
        return new TranscriptSegment("WMT", callId, sequence, sequence * 6000L, sequence * 6000L + 6000L,
                text, "CFO", 1_787_227_200L + sequence, end);
    }

    private void runQueued() {
        List<Runnable> tasks = new ArrayList<>(queued);
        queued.clear();
        tasks.forEach(Runnable::run);
    }

    @Test
    void emptyLiveSessionEndFlushesOnlyItsPendingWords() {
        TranscriptTranslationService service = service();
        service.submit(segment("live-1", 0, "Revenue grew.", false));
        service.submit(segment("live-2", 0, "Costs fell.", false));
        service.submit(segment("live-1", 1, "", true));
        runQueued();

        assertThat(client.requests).hasSize(1);
        assertThat(client.requests.get(0).callId()).isEqualTo("live-1");
        assertThat(client.requests.get(0).text()).isEqualTo("Revenue grew.");
        assertThat(published.get(0).getSequences()).containsExactly(0);
        timers.get(0).run();
        runQueued();
        assertThat(client.requests).hasSize(1);
    }

    @Test
    @DisplayName("세 세그먼트가 모이면 한 번에 번역을 요청하고 발행한다")
    void 세_개_묶음() {
        TranscriptTranslationService service = service();

        service.submit(segment(0, "Comp sales were 2.6%."));
        service.submit(segment(1, "Transactions grew."));
        assertThat(queued).isEmpty();
        service.submit(segment(2, "We raised guidance."));
        runQueued();

        assertThat(client.requests).hasSize(1);
        TranscriptTranslationModels.TranslateRequest request = client.requests.get(0);
        assertThat(request.sequence()).isZero();
        assertThat(request.callId()).isEqualTo("demo-1");
        assertThat(request.text()).isEqualTo("Comp sales were 2.6%. Transactions grew. We raised guidance.");
        // 용어 목록 전체는 사전 데이터에 따라 바뀐다. 원문 표기 그대로 실리는지만 본다.
        assertThat(request.terms()).extracting(TranscriptTranslationModels.Term::term).contains("Comp sales");
        assertThat(published).hasSize(1);
        assertThat(published.get(0).getSequences()).containsExactly(0, 1, 2);
        assertThat(published.get(0).getTextKo()).isEqualTo("번역문");
        assertThat(published.get(0).getCallId()).isEqualTo("demo-1");
    }

    @Test
    @DisplayName("덜 찼어도 대기 시간이 지나면 보낸다")
    void 대기_시간_만료() {
        TranscriptTranslationService service = service();

        service.submit(segment(0, "Comp sales were 2.6%."));
        assertThat(timerDelays).containsExactly(10_000L);
        timers.get(0).run();
        runQueued();

        assertThat(published).hasSize(1);
        assertThat(published.get(0).getSequences()).containsExactly(0);
    }

    @Test
    @DisplayName("이미 보낸 묶음의 타이머는 아무것도 하지 않는다")
    void 지난_타이머() {
        TranscriptTranslationService service = service();

        service.submit(segment(0, "One."));
        service.submit(segment(1, "Two."));
        service.submit(segment(2, "Three."));
        service.submit(segment(3, "Four."));
        timers.get(0).run();
        runQueued();

        assertThat(client.requests).hasSize(1);
        assertThat(published.get(0).getSequences()).containsExactly(0, 1, 2);
    }

    @Test
    @DisplayName("세션 종료 세그먼트는 남은 묶음을 바로 보낸다")
    void 세션_종료() {
        TranscriptTranslationService service = service();

        service.submit(segment(0, "One."));
        service.submit(segment("demo-1", 1, "Thank you.", true));
        runQueued();

        assertThat(published).hasSize(1);
        assertThat(published.get(0).getSequences()).containsExactly(0, 1);
    }

    @Test
    @DisplayName("붙이면 글자 수 상한을 넘을 때는 모은 것을 먼저 보낸다")
    void 글자_수_상한() {
        TranscriptTranslationService service = service();
        String long120 = "a".repeat(119) + ".";

        service.submit(segment(0, long120));
        service.submit(segment(1, long120));
        runQueued();

        assertThat(client.requests).hasSize(1);
        assertThat(client.requests.get(0).text()).isEqualTo(long120);
        assertThat(published.get(0).getSequences()).containsExactly(0);
    }

    @Test
    @DisplayName("콜이 다르면 따로 묶는다")
    void 콜별_묶음() {
        TranscriptTranslationService service = service();

        service.submit(segment("call-a", 0, "One.", false));
        service.submit(segment("call-b", 0, "Uno.", false));
        timers.forEach(Runnable::run);
        runQueued();

        assertThat(published).extracting(TranscriptTranslationPublisher.Payload::getCallId)
                .containsExactlyInAnyOrder("call-a", "call-b");
    }

    @Test
    @DisplayName("대기열에서 너무 오래 밀린 묶음은 보내지 않는다")
    void 늦은_묶음_버림() {
        TranscriptTranslationService service = service();

        service.submit(segment(0, "One."));
        service.submit(segment(1, "Two."));
        service.submit(segment(2, "Three."));
        now.addAndGet(30_001);
        runQueued();

        assertThat(client.requests).isEmpty();
        assertThat(published).isEmpty();
    }

    @Test
    @DisplayName("번역이 실패하면 발행하지 않는다")
    void 번역_실패() {
        client.response = Optional.of(new TranscriptTranslationModels.TranslateResponse(
                false, 0, null, List.of(), List.of("translation_llm_failed")));
        TranscriptTranslationService service = service();

        service.submit(segment("demo-1", 0, "One.", true));
        runQueued();

        assertThat(client.requests).hasSize(1);
        assertThat(published).isEmpty();
    }

    @Test
    @DisplayName("호출이 실패하면 발행하지 않는다")
    void 호출_실패() {
        client.response = Optional.empty();
        TranscriptTranslationService service = service();

        service.submit(segment("demo-1", 0, "One.", true));
        runQueued();

        assertThat(published).isEmpty();
    }

    @Test
    @DisplayName("번역이 꺼져 있으면 아무것도 하지 않는다")
    void 비활성화() {
        StubClient disabled = new StubClient(false);
        TranscriptTranslationService service = service(disabled);

        service.submit(segment("demo-1", 0, "One.", true));

        assertThat(queued).isEmpty();
        assertThat(timers).isEmpty();
    }

    @Test
    @DisplayName("terms_used 가 null 이어도 빈 목록으로 발행한다")
    void terms_used_null() {
        client.response = Optional.of(new TranscriptTranslationModels.TranslateResponse(
                true, 0, "번역문", null, List.of()));
        TranscriptTranslationService service = service();

        service.submit(segment("demo-1", 0, "One.", true));
        runQueued();

        assertThat(published.get(0).getTermsUsed()).isEmpty();
    }

    @Test
    @DisplayName("작업 중 예외가 나도 밖으로 새지 않는다")
    void 처리_중_예외() {
        AiEngineClient throwing = new StubClient(true) {
            @Override
            public Optional<TranscriptTranslationModels.TranslateResponse> translate(
                    TranscriptTranslationModels.TranslateRequest request) {
                throw new IllegalStateException("boom");
            }
        };
        TranscriptTranslationService service = service(throwing);

        service.submit(segment("demo-1", 0, "One.", true));
        runQueued();

        assertThat(published).isEmpty();
    }

    private static class StubClient extends AiEngineClient {
        final List<TranscriptTranslationModels.TranslateRequest> requests = new CopyOnWriteArrayList<>();
        Optional<TranscriptTranslationModels.TranslateResponse> response = Optional.of(
                new TranscriptTranslationModels.TranslateResponse(true, 0, "번역문", List.of("comp sales"), List.of()));

        StubClient(boolean translationEnabled) {
            super(null, false, false, false, translationEnabled);
        }

        @Override
        public Optional<TranscriptTranslationModels.TranslateResponse> translate(
                TranscriptTranslationModels.TranslateRequest request) {
            requests.add(request);
            return response;
        }
    }

    @Test
    @DisplayName("늦게 들어온 앞 세그먼트도 묶음 안에서는 sequence 순으로 정렬한다")
    void 묶음_내_정렬() {
        TranscriptTranslationService service = service();

        service.submit(segment(1, "Second."));
        service.submit(segment(0, "First."));
        service.submit(segment(2, "Third."));
        runQueued();

        assertThat(client.requests.get(0).sequence()).isZero();
        assertThat(client.requests.get(0).text()).isEqualTo("First. Second. Third.");
        assertThat(published.get(0).getSequences()).containsExactly(0, 1, 2);
    }

    @Test
    @DisplayName("응답의 sequence 가 요청과 다르면 발행하지 않는다")
    void 응답_sequence_불일치() {
        client.response = Optional.of(new TranscriptTranslationModels.TranslateResponse(
                true, 99, "번역문", List.of(), List.of()));
        TranscriptTranslationService service = service();

        service.submit(segment("demo-1", 0, "One.", true));
        runQueued();

        assertThat(published).isEmpty();
    }

    @Test
    @DisplayName("공백뿐인 세그먼트는 묶지 않는다")
    void 공백_세그먼트() {
        TranscriptTranslationService service = service();

        service.submit(segment("demo-1", 0, "   ", true));

        assertThat(timers).isEmpty();
        assertThat(queued).isEmpty();
    }

    @Test
    @DisplayName("엔진 상한(4000자)을 넘는 원문은 잘라 보낸다")
    void 원문_절단() {
        TranscriptTranslationService service = service(client, 4000);

        service.submit(segment(0, "a".repeat(4500)));
        runQueued();

        assertThat(client.requests.get(0).text()).hasSize(4000);
        assertThat(published.get(0).getSequences()).containsExactly(0);
    }

    @Test
    @DisplayName("서로게이트 쌍 가운데를 자르지 않는다")
    void 서로게이트_절단() {
        String text = "a".repeat(3) + "\uD83D\uDE00";

        assertThat(TranscriptTranslationService.clip(text, 4)).isEqualTo("aaa");
        assertThat(TranscriptTranslationService.clip(text, 5)).isEqualTo(text);
    }

    @Test
    @DisplayName("설정이 엔진 상한을 넘거나 0 이하면 기동을 실패시킨다")
    void 설정_검증() {
        TranscriptTranslationPublisher publisher = new TranscriptTranslationPublisher(null);
        assertThatThrownBy(() -> new TranscriptTranslationService(client, GLOSSARY, publisher, 3, 5000, 10_000, 30_000))
                .isInstanceOf(IllegalArgumentException.class);
        assertThatThrownBy(() -> new TranscriptTranslationService(client, GLOSSARY, publisher, 0, 1200, 10_000, 30_000))
                .isInstanceOf(IllegalArgumentException.class);
        assertThatThrownBy(() -> new TranscriptTranslationService(client, GLOSSARY, publisher, 3, 1200, 0, 30_000))
                .isInstanceOf(IllegalArgumentException.class);
    }

    @Test
    @DisplayName("실제 스레드로 타이머 만료 후 발행하고, 종료 뒤 submit 은 예외 없이 무시한다")
    void 실제_스레드와_종료() throws Exception {
        TranscriptTranslationPublisher publisher = new TranscriptTranslationPublisher(null) {
            @Override
            public void publish(Payload payload) {
                published.add(payload);
            }
        };
        TranscriptTranslationService service = new TranscriptTranslationService(
                client, GLOSSARY, publisher, 3, 1200, 50, 30_000);

        service.submit(segment(0, "One."));
        long deadline = System.currentTimeMillis() + 5_000;
        while (published.isEmpty() && System.currentTimeMillis() < deadline) {
            Thread.sleep(20);
        }
        assertThat(published).hasSize(1);

        service.shutdown();
        assertThatCode(() -> service.submit(segment(1, "Two."))).doesNotThrowAnyException();
    }
}
